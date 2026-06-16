"""MCP server (stdio JSON-RPC) for the Atelier context runtime.

Implements a minimal subset of the Model Context Protocol sufficient for
Codex / Claude Code to discover and call the runtime tools.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import inspect
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import types
import uuid as _uuid_mod
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal, Union, cast, get_args, get_origin, get_type_hints

from pydantic import Field, create_model

from atelier import __version__ as atelier_version
from atelier.core.capabilities.archival_recall import ArchivalRecallCapability
from atelier.core.capabilities.cross_vendor_routing.configuration import RouteConfigError
from atelier.core.capabilities.default_definitions import DefaultRegistry, build_default_registry
from atelier.core.capabilities.grounded_loop.grounding_evidence import (
    extract_grounding_targets,
    missing_grounding_targets,
    record_grounding_evidence,
)
from atelier.core.capabilities.host_runners import resolve_swarm_runner_command
from atelier.core.capabilities.memory import MemoryService
from atelier.core.capabilities.model_settings import normalize_model_for_host, resolve_host_model
from atelier.core.capabilities.owned_execution_cache_affinity import (
    cache_affinity_hint,
    latest_cache_affinity,
)
from atelier.core.capabilities.owned_execution_lanes import (
    OwnedExecutionError,
    execute_owned_prompt,
)
from atelier.core.capabilities.owned_execution_routing import (
    NoFeasibleRouteError,
    OwnedCachePolicy,
    OwnedRouteRequest,
    select_owned_route,
)
from atelier.core.capabilities.semantic_file_memory import SemanticFileMemoryCapability
from atelier.core.capabilities.source_projection import (
    CompactProjectionResult,
    MinifiedProjectionResult,
    SourceProjection,
)
from atelier.core.capabilities.workflow_context import WorkflowContextState
from atelier.core.capabilities.workflow_runner import WorkflowRunner
from atelier.core.capabilities.workflow_runtime_state import (
    coerce_workflow_review_decision as _coerce_workflow_review_decision,
)
from atelier.core.capabilities.workflow_runtime_state import (
    pause_workflow_runtime as _pause_workflow_runtime,
)
from atelier.core.capabilities.workflow_runtime_state import (
    require_active_workflow_runtime as _require_active_workflow_runtime,
)
from atelier.core.capabilities.workflow_runtime_state import (
    stop_workflow_runtime as _stop_workflow_runtime,
)
from atelier.core.capabilities.workflow_runtime_state import (
    workflow_runtime_state as _workflow_runtime_state,
)
from atelier.core.capabilities.workflow_runtime_state import (
    workflow_runtime_status as _coerce_workflow_runtime_status,
)
from atelier.core.capabilities.workflow_runtime_state import (
    write_workflow_runtime_state as _write_workflow_runtime_state,
)
from atelier.core.capabilities.workflow_schema import workflow_definition_from_mapping
from atelier.core.capabilities.workflow_spawn import build_spawn_envelope, compile_prompt_text
from atelier.core.environment import mcp_tool_description, mcp_tool_mode, mcp_tool_visible_to_llm
from atelier.core.foundation.memory_models import ArchivalPassage, MemoryBlock
from atelier.core.foundation.models import RawArtifact, Trace, to_jsonable
from atelier.core.foundation.redaction import redact
from atelier.core.foundation.rubric_gate import run_rubric
from atelier.gateway.adapters.runtime import ContextRuntime
from atelier.infra.embeddings.factory import make_embedder
from atelier.infra.runtime.realtime_context import RealtimeContextManager
from atelier.infra.runtime.run_ledger import (
    RunLedger,
    outcomes_path,
    session_run_dir,
)
from atelier.infra.storage.factory import make_memory_store
from atelier.infra.storage.memory_store import MemoryConcurrencyError, MemorySidecarUnavailable

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "atelier-context"
SERVER_VERSION = atelier_version
CONTEXT_WINDOW_TOKENS = 200_000
COMPACT_ADVISORY_THRESHOLD = 60.0
AUTO_COMPACT_THRESHOLD = 80.0
HANDOVER_THRESHOLD = 95.0
AUTO_COMPACT_MIN_TURNS = 15
# Bypass the min-turns gate when utilisation already exceeds this level —
# a few very large turns can fill the window just as fast as many small ones.
AUTO_COMPACT_HIGH_UTIL_OVERRIDE = 90.0


# --------------------------------------------------------------------------- #
# Tool Registry Decorator                                                     #
# --------------------------------------------------------------------------- #

TOOLS: dict[str, dict[str, Any]] = {}


def _tool_description(spec: dict[str, Any]) -> str:
    return mcp_tool_description(
        str(spec.get("name", "") or ""),
        str(spec.get("description", "") or ""),
    )


def _tool_visible_to_llm(tool_name: str, spec: dict[str, Any]) -> bool:
    return mcp_tool_visible_to_llm(tool_name)


def _tool_mode(spec: dict[str, Any]) -> str:
    return mcp_tool_mode(str(spec.get("name", "") or ""))


_COERCE_UNCHANGED: Any = object()


def _annotation_base_types(annotation: Any) -> set[Any]:
    """Resolve an annotation to the set of concrete base types it accepts.

    Unwraps Optional/Union (both ``Union[...]`` and ``X | Y``) and generic
    aliases (``list[str]`` -> ``list``). Returns an empty set for ``Any`` or
    anything unrecognised, signalling "leave the value alone".
    """
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        resolved: set[Any] = set()
        for arg in get_args(annotation):
            resolved |= _annotation_base_types(arg)
        return resolved
    if origin is not None:
        return {origin}
    if isinstance(annotation, type):
        return {annotation}
    return set()


def _coerce_str_to_annotation(value: Any, annotation: Any) -> Any:
    """Coerce a stringified value to its parameter's annotated type.

    Some MCP clients serialise argument *values* as strings (``"20"`` for an
    int, ``"true"`` for a bool, ``'["a"]'`` for a list). Returns the coerced
    value, or the ``_COERCE_UNCHANGED`` sentinel when the value should be left
    untouched (already acceptable as a str, ambiguous, or not coercible).
    """
    if not isinstance(value, str):
        return _COERCE_UNCHANGED
    base = _annotation_base_types(annotation)
    if not base or str in base:
        return _COERCE_UNCHANGED
    if bool in base:
        low = value.strip().lower()
        if low in {"true", "1", "yes", "on"}:
            return True
        if low in {"false", "0", "no", "off"}:
            return False
        return _COERCE_UNCHANGED
    if int in base:
        try:
            return int(value)
        except ValueError:
            return _COERCE_UNCHANGED
    if float in base:
        try:
            return float(value)
        except ValueError:
            return _COERCE_UNCHANGED
    if base & {list, dict, tuple, set}:
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(value)
            except (ValueError, SyntaxError):
                continue
            if isinstance(parsed, (list, dict, tuple, set)):
                return parsed
        return _COERCE_UNCHANGED
    return _COERCE_UNCHANGED


def _coerce_json_strings(args: dict[str, Any], param_annotations: dict[str, Any]) -> dict[str, Any]:
    """Self-heal stringified argument values before Pydantic validation.

    Some MCP clients serialise argument values as strings (``"20"`` instead of
    ``20``, ``"true"`` instead of ``True``, ``'["a"]'`` instead of ``["a"]``).
    Each value is coerced to its parameter's annotated type so otherwise-valid
    calls don't fail. This matters doubly for the mypyc-compiled build, whose
    handlers enforce argument types at runtime and reject a stringified value
    outright. ``param_annotations`` maps each parameter to its *resolved* type:
    resolution (``get_type_hints`` in ``mcp_tool``) is required because
    ``from __future__ import annotations`` makes raw annotations plain strings.
    """
    if not isinstance(args, dict):
        return args
    coerced = args
    for param_name, annotation in param_annotations.items():
        if param_name not in coerced:
            continue
        new_val = _coerce_str_to_annotation(coerced[param_name], annotation)
        if new_val is _COERCE_UNCHANGED:
            continue
        if coerced is args:
            coerced = dict(args)
        coerced[param_name] = new_val
    return coerced


def _slim_schema(node: Any) -> Any:
    """Shrink a generated JSON schema for LLM tool clients without changing its contract.

    Drops per-node ``title`` keys and collapses nullable ``anyOf`` unions
    (Pydantic's ``X | None``) down to ``X``: the parameter stays optional via
    its absence from ``required``, and the tool handler's Pydantic model is
    untouched, so omitted or ``None`` arguments are still accepted. Purely
    removes wire bytes that never guided the model.
    """
    if isinstance(node, dict):
        # Strip Pydantic's scalar `title` annotation, but keep a property that is
        # literally named `title` (its value is a schema dict, not a string).
        slimmed = {
            key: _slim_schema(value) for key, value in node.items() if not (key == "title" and isinstance(value, str))
        }
        branches = slimmed.get("anyOf")
        if isinstance(branches, list):
            non_null = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]
            if len(non_null) == 1 and len(non_null) < len(branches):
                collapsed = {key: value for key, value in slimmed.items() if key != "anyOf"}
                collapsed.update(non_null[0])
                if collapsed.get("default") is None:
                    collapsed.pop("default", None)
                return collapsed
        return slimmed
    if isinstance(node, list):
        return [_slim_schema(item) for item in node]
    return node


def mcp_tool(
    name: str | None = None,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
    hidden_params: tuple[str, ...] = (),
) -> Callable[[Callable[..., Any]], Callable[[dict[str, Any]], Any]]:
    """Decorator to register a tool and auto-derive its MCP schema."""

    def decorator(
        func: Callable[..., Any],
    ) -> Callable[[dict[str, Any]], Any]:
        tool_name = name or func.__name__.removeprefix("tool_")
        # Use the full docstring as the description so agents see all op detail.
        tool_description = description or (func.__doc__ or "").strip()

        sig = inspect.signature(func)
        # `from __future__ import annotations` makes raw signature annotations
        # plain strings; resolve them to real types so stringified scalar args
        # ("20" -> 20) can be coerced before the (mypyc-strict) handler runs.
        try:
            resolved_hints = get_type_hints(func)
        except Exception:  # noqa: BLE001 - fall back to raw annotations if hints don't resolve
            resolved_hints = {}
        param_annotations = {
            param_name: resolved_hints.get(param_name, param.annotation) for param_name, param in sig.parameters.items()
        }
        fields = {}
        for param_name, param in sig.parameters.items():
            annotation = param.annotation if param.annotation is not inspect.Parameter.empty else Any
            default = param.default if param.default is not inspect.Parameter.empty else ...
            fields[param_name] = (
                annotation,
                Field(default=default) if default is not ... else Field(...),
            )

        if fields:
            # Convert to format expected by create_model: (type, default/Field)
            field_defs = {k: (v[0], v[1]) for k, v in fields.items()}
            known_params = frozenset(field_defs)
            ArgsModel = create_model(f"{func.__name__}_Args", **field_defs)  # type: ignore[call-overload]
            schema = ArgsModel.model_json_schema()
            # Niche params stay accepted by the handler but are not published to LLMs.
            for hidden in hidden_params:
                schema.get("properties", {}).pop(hidden, None)
            # Strip Pydantic schema noise (per-node `title`, nullable `anyOf`
            # unions) that costs tokens on every request without guiding the
            # LLM. The handler's model is unchanged, so omitted/None args are
            # still accepted; this only shrinks the wire schema.
            schema = _slim_schema(schema)

            @wraps(func)
            def handler_wrapper(args: dict[str, Any]) -> Any:
                # Pydantic's default config silently drops unknown keys, so a
                # typo'd argument (e.g. codemod `dryrun` for `dry_run`) would be
                # discarded and the wrong default used while the call still
                # "succeeds". Surface those keys instead of forbidding them, so
                # callers that legitimately pass extras are not broken.
                if isinstance(args, dict):
                    unknown = [key for key in args if key not in known_params]
                    if unknown:
                        logger.warning(
                            "tool %s received unknown argument(s) %s (ignored; known: %s)",
                            tool_name,
                            sorted(unknown),
                            sorted(known_params),
                        )
                validated = ArgsModel.model_validate(_coerce_json_strings(args, param_annotations))
                return func(**validated.model_dump())

        else:
            schema = {"type": "object", "properties": {}}

            @wraps(func)
            def handler_wrapper(_args: dict[str, Any]) -> Any:
                return func()

        TOOLS[tool_name] = {
            "name": tool_name,
            "handler": handler_wrapper,
            "description": tool_description,
            "inputSchema": input_schema or schema,
        }
        return handler_wrapper

    return decorator


# G13 — caller-selectable output encoding shared by read/search/grep/symbols.
# Defined here (before the tool handlers) so the @mcp_tool decorator can resolve
# the Annotated default at import time. The handler ignores this arg; the MCP
# dispatcher reads `args["format"]` and applies the N6-gated N7 columnar
# encoding. `auto` (default) keeps today's byte-compatible output.
_FORMAT_SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": ["auto", "compact", "json"],
    "default": "auto",
    "description": (
        "Output encoding: `auto` (default) keeps current behavior; `json` forces raw JSON; "
        "`compact` emits a self-describing columnar form when it beats JSON by the savings "
        "threshold (never inflates small payloads)."
    ),
}
_FORMAT_FIELD = Field(
    default="auto",
    description=(
        "Output encoding: auto (default, unchanged), json (force raw JSON), or compact (N6-gated columnar encoding)."
    ),
)


# --------------------------------------------------------------------------- #
# session_state.json helpers                                                  #
# --------------------------------------------------------------------------- #

_current_ledger: RunLedger | None = None
_realtime_ctx: RealtimeContextManager | None = None
_product_session_id: str | None = None
_product_session_started_at: float | None = None
_last_plan_hash_by_session: dict[str, str] = {}
_last_plan_by_session: dict[str, dict[str, Any]] = {}
_last_blocked_plan_hash_by_session: dict[str, str] = {}

# --------------------------------------------------------------------------- #
# Trajectory monitor state (per session)                                      #
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class _MonitorSession:
    """Per-session DifficultyFSM + step history for trajectory monitoring."""

    fsm: Any = dataclasses.field(default=None)
    steps: list[str] = dataclasses.field(default_factory=list)
    composite: float = 0.0
    _call_count: int = 0

    def __post_init__(self) -> None:
        if self.fsm is None:
            from atelier.core.capabilities.monitors.fsm import DifficultyFSM

            self.fsm = DifficultyFSM()


_monitor_sessions: dict[str, _MonitorSession] = {}
_MAX_MONITOR_STEPS = 25
_MAX_MONITOR_SESSIONS = 64


def _advance_monitors(session_id: str, task: str, original_task: str) -> tuple[float, bool]:
    """Advance per-session trajectory monitors; return (composite, skip_etraces).

    Guards itself behind the bench kill-switch so monitors don't interfere with
    benchmark runs.  Runs ``evaluate_all`` once every ``monitor_cooldown_steps``
    calls (as determined by the FSM state) to amortise the regex cost.
    """
    try:
        from atelier.bench.mode import is_off as _bench_is_off

        if _bench_is_off():
            return 0.0, False

        from atelier.core.capabilities.monitors import evaluate_all
        from atelier.core.capabilities.monitors.fsm import score_step

        ms = _monitor_sessions.setdefault(session_id, _MonitorSession())
        if len(_monitor_sessions) > _MAX_MONITOR_SESSIONS:
            # Bound the session map: a marathon process seeing many session ids
            # must not leak _MonitorSession objects. Evict oldest (skip current).
            for _stale in list(_monitor_sessions)[: len(_monitor_sessions) - _MAX_MONITOR_SESSIONS]:
                if _stale != session_id:
                    _monitor_sessions.pop(_stale, None)
        ms.steps.append(task)
        if len(ms.steps) > _MAX_MONITOR_STEPS:
            ms.steps = ms.steps[-20:]
        ms.fsm.transition(score_step(task))
        ms._call_count += 1

        cooldown = ms.fsm.monitor_cooldown_steps
        if ms._call_count % cooldown == 0 or ms._call_count == 1:
            result = evaluate_all(ms.steps, task=original_task)
            ms.composite = result.composite
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return 0.0, False

    return ms.composite, ms.fsm.skip_etraces


# Atelier-internal MCP process identity — generated once at import, never changes.
# SessionStart hook finds this file and writes the Claude session UUID + model into it.
# _get_claude_session_id() reads it once then caches in _cached_claude_session_id.
_MCP_ID: str = f"atelier-{_uuid_mod.uuid4().hex[:16]}"
_cached_claude_session_id: str = ""
_cached_mcp_model: str = ""
# _current_context_state cache: session id -> (stat-signature, (ctx, model)).
# That probe runs on every savings-bearing tool call; without this it re-tails
# and JSON-parses a 64 KB transcript window every time. Keyed on the candidate
# transcripts' (path, mtime_ns, size) so any new turn / rewrite invalidates it.
_CONTEXT_STATE_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], tuple[int, str]]] = {}
_STDOUT_LOCK = threading.Lock()
_STATE_LOCK = threading.RLock()
# Per-file edit locks: concurrent edit calls (the MCP dispatcher runs a thread
# pool) that touch the same file must not interleave snapshot/apply/write, or one
# write clobbers the other (lost update). _EDIT_PATH_LOCKS maps a resolved file
# path to its Lock; _EDIT_PATH_LOCKS_GUARD serializes registry mutation only.
_EDIT_PATH_LOCKS: dict[str, threading.Lock] = {}
_EDIT_PATH_LOCKS_GUARD = threading.Lock()
_DEFAULT_MCP_MAX_WORKERS = 16


def _edit_path_locks(resolved_paths: list[Path]) -> list[threading.Lock]:
    """Return locks for *resolved_paths*, ordered deterministically to avoid
    deadlock when an edit batch touches several files at once."""
    keys = sorted({str(p) for p in resolved_paths})
    with _EDIT_PATH_LOCKS_GUARD:
        return [_EDIT_PATH_LOCKS.setdefault(key, threading.Lock()) for key in keys]


_MAX_MCP_MAX_WORKERS = 64

# Single JSON-RPC frames larger than the host's stdout guard (~16 MiB in Claude
# Code) make the client disconnect the entire MCP server, and it does not
# auto-reconnect mid-session. Cap per-result text well under that, and keep a
# hard frame ceiling as a backstop so no single message can ever trip the guard.
_DEFAULT_MAX_RESULT_BYTES = 6 * 1024 * 1024
_MAX_WIRE_BYTES = 14 * 1024 * 1024
# Context-hygiene bound (chars). Distinct from the multi-MB wire guards above,
# which only keep a JSON-RPC frame under the host's stdout limit: this caps a
# single runaway tool result (huge log, minified file, unbounded grep) that
# would otherwise flood the host prompt -- and the host re-pays for those bytes
# on every later turn. ~64k tokens. Set ATELIER_MCP_COMPACT_RESULT_CHARS=0 to
# disable.
_DEFAULT_COMPACT_RESULT_CHARS = 256 * 1024
# Per-read inline budget (bytes). A single file read larger than this is returned
# as a line-aligned prefix plus an EXACT continuation range, instead of being
# handed to the host whole -- where the host's own MCP-output guard would dump it
# to a temp file and force the agent to re-read the file in blind ranges. Keep it
# below the host limit (~50KB). Set ATELIER_READ_INLINE_BUDGET_BYTES=0 to disable.
_DEFAULT_READ_INLINE_BUDGET_BYTES = 40 * 1024


def _service_backed_state() -> bool:
    return True


def _detect_agent() -> str:
    """Derive the agent label from the runtime environment.

    Checks, in order:
    1. ATELIER_AGENT env var (explicit override - any host can set this)
    2. CLAUDE_CODE -> "claude"
    3. ANTIGRAVITY_SESSION_ID or AGY_SESSION_ID -> "antigravity"
    4. CODEX_SESSION_ID -> "codex"
    5. OPENCODE_SESSION_ID -> "opencode"
    6. Falls back to "claude" (the MCP wrapper is shipped with the Claude plugin)
    """
    explicit = os.environ.get("ATELIER_AGENT", "").strip()
    if explicit:
        return explicit
    if os.environ.get("CLAUDE_CODE"):
        return "claude"
    if (
        os.environ.get("ANTIGRAVITY_SESSION_ID")
        or os.environ.get("AGY_SESSION_ID")
        or os.environ.get("ANTIGRAVITY_CLI")
        or os.environ.get("AGY_CLI")
    ):
        return "antigravity"
    if os.environ.get("CODEX_SESSION_ID") or os.environ.get("CODEX_CLI"):
        return "codex"
    if os.environ.get("OPENCODE_SESSION_ID") or os.environ.get("OPENCODE_CLI"):
        return "opencode"
    if os.environ.get("CURSOR_SESSION_ID") or os.environ.get("CURSOR_TRACE_ID"):
        return "cursor"
    if os.environ.get("HERMES_HOME") or os.environ.get("HERMES_SESSION_ID") or os.environ.get("HERMES_CLI"):
        return "hermes"
    if os.environ.get("COPILOT_CLI") or os.environ.get("GITHUB_COPILOT_SESSION_ID"):
        return "copilot"
    # Default: the plugin lives in the Claude Code plugin system
    return "claude"


def _get_ledger() -> RunLedger:
    global _current_ledger
    if _current_ledger is not None:
        return _current_ledger
    # Bind the ledger to the host session id (Claude Code UUID, etc.) so
    # run.json lands at sessions/<host-id>/run.json — the same folder the
    # plugin hooks read and the savings sidecar writes. Computed outside the
    # lock since _get_claude_session_id touches shared state; non-host runs
    # fall back to RunLedger's own random uuid4.
    host_sid = _get_claude_session_id() or None
    with _STATE_LOCK:
        if _current_ledger is None:
            _current_ledger = RunLedger(root=_atelier_root(), agent=_detect_agent(), session_id=host_sid)
    return _current_ledger


def _get_realtime_context() -> RealtimeContextManager:
    global _realtime_ctx
    with _STATE_LOCK:
        if _realtime_ctx is None:
            _realtime_ctx = RealtimeContextManager(_atelier_root())
    return _realtime_ctx


def _get_product_session_id() -> str:
    global _product_session_id
    with _STATE_LOCK:
        if _product_session_id is None:
            from atelier.core.foundation.identity import new_session_id

            _product_session_id = new_session_id()
    return _product_session_id


def _emit_mcp_session_start() -> None:
    global _product_session_started_at
    if _product_session_started_at is not None:
        return
    _register_mcp_session()  # register Atelier MCP ID so SessionStart hook can find us
    from importlib.metadata import PackageNotFoundError, version

    from atelier.core.foundation.identity import get_anon_id, platform_payload
    from atelier.core.service.telemetry import emit_product

    try:
        service_version = version("atelier")
    except PackageNotFoundError:
        service_version = SERVER_VERSION
    # OTel is initialized lazily on first emit_product_log call.
    _product_session_started_at = time.perf_counter()
    emit_product(
        "session_start",
        agent_host=_detect_agent(),
        atelier_version=service_version,
        anon_id=get_anon_id(),
        session_id=_get_product_session_id(),
        **platform_payload(),
    )


def _emit_mcp_session_end(exit_reason: str = "success") -> None:
    if _product_session_started_at is None:
        return
    from atelier.core.service.telemetry import emit_product
    from atelier.core.service.telemetry.schema import bucket_duration_s

    elapsed = max(0.0, time.perf_counter() - _product_session_started_at)
    emit_product(
        "session_end",
        session_id=_get_product_session_id(),
        duration_s_bucket=bucket_duration_s(elapsed),
        exit_reason=exit_reason,
    )


def _match_mcp_lexical(args: dict[str, Any]) -> None:
    from atelier.core.service.telemetry.frustration import match_frustration

    for key in ("task", "query", "user_goal", "error"):
        value = args.get(key)
        if isinstance(value, str):
            match_frustration(value, surface="mcp_prompt", session_id=_get_product_session_id())


def _emit_playbook_retrieved(scored: list[Any], domain: str | None) -> None:
    from atelier.core.service.telemetry import emit_product
    from atelier.core.service.telemetry.schema import hash_identifier

    for rank, item in enumerate(scored, start=1):
        block = getattr(item, "block", None)
        emit_product(
            "playbook_retrieved",
            block_id_hash=hash_identifier(str(getattr(block, "id", ""))),
            domain=str(getattr(block, "domain", domain or "")),
            retrieval_score=float(getattr(item, "score", 0.0)),
            rank=rank,
            session_id=_get_product_session_id(),
        )


# --------------------------------------------------------------------------- #
# Tool implementations                                                        #
# --------------------------------------------------------------------------- #


def _atelier_root() -> Path:
    from atelier.core.foundation.paths import default_store_root

    return Path(os.environ.get("ATELIER_ROOT", str(default_store_root())))


def _make_outcome_writer(led: RunLedger) -> Any:
    """Return a FileStateWriter for outcomes alongside the run file, or None."""
    with contextlib.suppress(Exception):
        from atelier.infra.runtime.outcome_capture import FileStateWriter

        root = led._root
        if root is not None:
            return FileStateWriter(outcomes_path(root, led.session_id))
    return None


# --------------------------------------------------------------------------- #
# Zero-config background service                                              #
# --------------------------------------------------------------------------- #


def _detect_default_branch(repo: Path) -> str | None:
    """Detect the remote default branch (main/master) for *repo*."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "remote", "show", "origin"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("HEAD branch:"):
                branch = stripped.split(":")[-1].strip()
                if branch:
                    return branch
    except Exception:
        logging.exception("Recovered from broad exception handler")
        logger.warning(
            "Suppressed exception in _detect_default_branch",
            exc_info=True,
        )
    # Fallback: try main then master
    for candidate in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", f"origin/{candidate}"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            logging.exception("Recovered from broad exception handler")
            continue
    return None


_log = logging.getLogger("atelier.mcp")


def _check_auto_update() -> None:
    """Check git remote for a newer version and auto-update if found.

    Compares the version in the remote repo's ``pyproject.toml`` against the
    currently installed version.  If they differ, pulls the repo and runs
    the install script.  Logs errors and emits telemetry on failure but
    never blocks the MCP server.

    Opt-in only: does nothing unless ``ATELIER_AUTO_UPDATE=1`` is set in the
    environment. Running ``git pull`` + the install script from origin on every
    startup is a supply-chain/RCE risk, so it must be explicitly enabled.
    """
    import re
    import subprocess

    if os.environ.get("ATELIER_AUTO_UPDATE") != "1":
        _log.debug("auto-update disabled (set ATELIER_AUTO_UPDATE=1 to enable)")
        return

    _log.info("checking for auto-update...")

    try:
        # Determine the repo directory
        install_dir = os.environ.get("ATELIER_INSTALL_DIR", "")
        if install_dir:
            repo = Path(install_dir)
            _log.debug("repo from ATELIER_INSTALL_DIR: %s", repo)
        else:
            repo = Path(__file__).resolve().parents[4]
            _log.debug("repo from file path: %s", repo)

        if not (repo / ".git").exists():
            _log.debug("not a git checkout - skipping auto-update")
            return  # Not a git checkout, nothing to auto-update

        # Fetch latest remote info
        _log.info("fetching latest remote refs from origin...")
        result = subprocess.run(
            ["git", "fetch", "--tags", "--prune", "origin"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            _log.warning("git fetch exited %d: %s", result.returncode, result.stderr.strip())
            return

        default_branch = _detect_default_branch(repo)
        if default_branch is None:
            _log.warning("could not detect default remote branch")
            return

        # Read remote version from pyproject.toml
        result = subprocess.run(
            ["git", "show", f"origin/{default_branch}:pyproject.toml"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            _log.warning(
                "could not read remote pyproject.toml (exit %d): %s",
                result.returncode,
                result.stderr.strip(),
            )
            return

        match = re.search(r'^version\s*=\s*"([^"]+)"', result.stdout, re.MULTILINE)
        if not match:
            _log.warning("could not parse version from remote pyproject.toml")
            return

        remote_version = match.group(1)
        _log.info("current=%s  remote=%s", atelier_version, remote_version)

        if remote_version == atelier_version:
            _log.info("already up-to-date")
            return

        # Newer (or different) version detected - pull and reinstall
        _log.info("version changed - pulling %s/%s ...", default_branch, default_branch)
        subprocess.run(
            ["git", "pull", "--ff-only", "origin", default_branch],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )

        install_script = repo / "scripts" / "install.sh"
        if install_script.exists():
            _log.info("running install script...")
            subprocess.run(
                ["bash", str(install_script), "--local"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
            _log.info("auto-update complete")

            # Write update-state so SessionStart hooks can notify the user.
            # Re-read the version from pyproject.toml since the install script
            # may have updated it but the in-process version hasn't changed.
            try:
                from atelier.core.foundation.update_state import write_update_state

                new_pyproject = repo / "pyproject.toml"
                if new_pyproject.exists():
                    m2 = re.search(r'^version\s*=\s*"([^"]+)"', new_pyproject.read_text("utf-8"), re.MULTILINE)
                    new_ver = m2.group(1) if m2 else atelier_version
                else:
                    new_ver = atelier_version

                write_update_state(
                    previous_version=atelier_version,
                    current_version=new_ver,
                    method="git",
                )
            except Exception:  # noqa: BLE001
                _log.exception("failed to write update state")
        else:
            _log.warning("install script not found at %s", install_script)
    except Exception:
        logging.exception("Recovered from broad exception handler")
        _log.exception("auto-update failed")
        with contextlib.suppress(Exception):
            from atelier.core.service.telemetry import emit_product

            emit_product(
                "mcp_auto_update_failed",
                current_version=atelier_version,
                session_id=_get_product_session_id(),
            )


def _run_worker_tick_safe(root: Path) -> None:
    """Process up to 20 pending jobs for *root*.  Run in a daemon thread."""
    try:
        from atelier.core.service.worker import Worker
        from atelier.infra.storage.factory import create_store

        store = create_store(root)
        store.init()
        worker = Worker(store=store)
        for _ in range(20):
            if worker.run_once() is None:
                break
    except Exception:
        logging.exception("Recovered from broad exception handler")
        logger.warning(
            "Suppressed exception in _run_worker_tick_safe",
            exc_info=True,
        )


_last_worker_spawn_time: float = 0.0
_WORKER_SPAWN_THROTTLE_SECS: float = 30.0


def _spawn_worker_if_idle(root: Path) -> None:
    """Spawn a worker thread at most once per throttle window to avoid thread storms."""
    import time

    global _last_worker_spawn_time
    # Serialize the check-and-set so two concurrent light-pool callers can't both
    # pass the throttle window and spawn redundant workers. Spawn the thread
    # OUTSIDE the lock so thread creation doesn't run under _STATE_LOCK.
    with _STATE_LOCK:
        now = time.monotonic()
        if now - _last_worker_spawn_time < _WORKER_SPAWN_THROTTLE_SECS:
            return
        _last_worker_spawn_time = now
    threading.Thread(
        target=_run_worker_tick_safe,
        args=(root,),
        daemon=True,
    ).start()


_runtime_cache: ContextRuntime | None = None
_context_budget_recorder: Any = None


def _runtime() -> ContextRuntime:
    global _runtime_cache
    with _STATE_LOCK:
        if _runtime_cache is None:
            _runtime_cache = ContextRuntime(_atelier_root())
    return _runtime_cache


def _reset_runtime_cache_for_testing() -> None:
    global _current_ledger, _realtime_ctx, _product_session_id, _product_session_started_at
    global _runtime_cache, _remote_client, _context_budget_recorder
    global _last_worker_spawn_time
    _current_ledger = None
    _realtime_ctx = None
    _product_session_id = None
    _product_session_started_at = None
    _runtime_cache = None
    _remote_client = None
    _context_budget_recorder = None
    _last_worker_spawn_time = 0.0
    _last_plan_hash_by_session.clear()
    _last_plan_by_session.clear()
    _CONTEXT_STATE_CACHE.clear()
    _COMPACT_ADVISE_CACHE.clear()
    _last_blocked_plan_hash_by_session.clear()
    _code_engine_cache.clear()
    _scoped_context_cache.clear()


def _live_savings_events_path() -> Path:
    return _atelier_root() / "live_savings_events.jsonl"


# Cap the analytics log: full-file readers (audit_export, advisor, dashboard,
# session_report) O(n)-scan it per render, so unbounded growth is a real cost.
_LIVE_SAVINGS_MAX_BYTES = 8 * 1024 * 1024
_live_savings_dir_ready = False
_live_savings_append_count = 0


def _append_live_savings_event(event: dict[str, Any]) -> None:
    """Append a routing / compaction analytics event.

    Display savings ride the MCP response's content[].saved field into the
    transcript and are summed from there. This file remains the log for
    audit_export and cross_vendor_routing.advisor only.
    """
    global _live_savings_dir_ready, _live_savings_append_count
    path = _live_savings_events_path()
    if not _live_savings_dir_ready:
        # mkdir once per process instead of a syscall on every tool call.
        path.parent.mkdir(parents=True, exist_ok=True)
        _live_savings_dir_ready = True
    _live_savings_append_count += 1
    if _live_savings_append_count % 128 == 0:
        # Periodic size-based rotation (keep one prior generation) so the log
        # cannot grow without bound; checked rarely to avoid a per-call stat().
        try:
            if path.exists() and path.stat().st_size > _LIVE_SAVINGS_MAX_BYTES:
                path.replace(path.parent / (path.name + ".1"))
        except OSError:
            logging.exception("Recovered from broad exception handler")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _workspace_savings_path() -> Path:
    """Side log for per-session savings on Copilot CLI and other non-Claude hosts."""
    import hashlib

    workspace = str(Path(os.environ.get("ATELIER_WORKSPACE_ROOT") or os.getcwd()).resolve())
    h = hashlib.sha256(workspace.encode()).hexdigest()[:12]
    return _atelier_root() / "workspaces" / h / "session_savings.jsonl"


def _mcp_session_file() -> Path:
    """Path to this MCP process's registration file.

    Written at startup; SessionStart hook writes claude_session_id + model into it.
    """
    return _atelier_root() / "mcp_sessions" / f"{_MCP_ID}.json"


def _workspace_session_state_file() -> Path:
    import hashlib

    ws = str(Path(os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()).resolve())
    ws_hash = hashlib.sha256(ws.encode()).hexdigest()[:12]
    return _atelier_root() / "workspaces" / ws_hash / "session_state.json"


def _read_workspace_session_bridge() -> tuple[str, str]:
    """Read `(claude_session_id, model)` from workspace session_state.json."""
    try:
        data = _read_workspace_session_state()
        if not isinstance(data, dict):
            return "", ""
        sid = str(data.get("session_id") or "").strip()
        model = str(data.get("model") or "").strip()
        return sid, model
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return "", ""


def _claude_session_id() -> str:
    """Session UUID for *this* MCP server process.

    Claude Code sets ``CLAUDE_CODE_SESSION_ID`` in every MCP server's
    environment at launch, so it identifies the owning session even when
    several sessions run concurrently in one workspace. The workspace bridge
    (``workspaces/<hash>/session_state.json``) is a single shared slot the most
    recent SessionStart hook overwrites - keying per-call savings off it
    misattributes them to whichever sibling session last started. Prefer the
    per-process env var; fall back to the bridge only when the host does not
    set it. Empty when neither exists (non-Claude hosts).
    """
    env_sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if env_sid:
        return env_sid
    bridge_sid, _ = _read_workspace_session_bridge()
    return bridge_sid


def _read_workspace_session_state() -> dict[str, Any]:
    try:
        path = _workspace_session_state_file()
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return {}


def _write_workspace_session_state(state: dict[str, Any]) -> None:
    try:
        path = _workspace_session_state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: str | None = None
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(state, handle, indent=2)
            tmp_path = handle.name
        Path(tmp_path).replace(path)
    except Exception:
        logging.exception("Recovered from broad exception handler")


# Process-local hint for the fast path in _process_tool_accounting: when False, a
# call that is neither a read nor a credit-enabled code-intel tool has no pending
# credits to age, so it can skip the session_state read+write entirely. Safe
# because one MCP server process owns the session's pending list; re-derived
# after every real pass.
_tool_accounting_pending_hint: bool = True


def _process_tool_accounting(name: str, args: dict[str, Any], result: Any, rid: Any) -> None:
    """Per-call savings accounting that never touches the model-facing response.

    Two honest corrections share ONE session_state read/write:

    1. Read baseline de-dup: outline/range reads both credit ``tokens_saved``
       against the full-file baseline; crediting that more than once per file per
       session double-counts (you can only avoid reading a file once). The 2nd+
       baseline read of a file has its saving zeroed (via the thread-local)
       BEFORE budget recording. Switch: ATELIER_READ_BASELINE_DEDUP=0.
    2. Code-intel avoided-read credit: a deferred, observed credit booked to the
       sidecar after an unread observation window
       (``ATELIER_CODE_INTEL_CREDIT_AGE`` ticks). Switch: ATELIER_CODE_INTEL_CREDIT=0.

    Fast path: a call that is neither a read nor a credit-enabled code-intel tool,
    with no pending code-intel credits to age, skips all session_state I/O.
    """
    global _tool_accounting_pending_hint
    code_intel_on = os.environ.get("ATELIER_CODE_INTEL_CREDIT", "1") != "0"
    read_dedup_on = os.environ.get("ATELIER_READ_BASELINE_DEDUP", "1") != "0"
    if not code_intel_on and not read_dedup_on:
        return
    try:
        from atelier.core.capabilities import code_intel_credit, context_dedup, read_baseline_credit

        is_read = name == "read"
        is_code_intel = code_intel_on and name in code_intel_credit.CODE_INTEL_TOOLS
        if not is_read and not is_code_intel and not _tool_accounting_pending_hint:
            return  # nothing to net or record, and no pending credit to age

        # An in-band error means the handler did not actually surface usable
        # content, so its saving is illusory: don't credit it. Covers a
        # top-level `error` and any per-file `error` in a batch read.
        result_errored = isinstance(result, dict) and bool(result.get("error"))

        # The session_state read-modify-write (and the process-wide pending hint)
        # must be serialized: atomic os.replace prevents a torn file but not a
        # lost update when two tool calls interleave RMW. _STATE_LOCK is an
        # RLock, so reentrant helper calls below are safe.
        with _STATE_LOCK:
            state = _read_workspace_session_state()
            # Epoch guard: a compaction resets both ledgers so credits cannot leak
            # across context windows.
            epoch = context_dedup.current_epoch()
            if state.get("code_intel_epoch") != epoch:
                state = code_intel_credit.reset_pending(state)
                state = read_baseline_credit.reset(state)
                state["code_intel_epoch"] = epoch

            if is_read:
                if result_errored:
                    # Errored read earned nothing -> zero its saving outright.
                    _tool_call_tokens_saved.value = 0
                    if isinstance(result, dict):
                        result.pop("tokens_saved", None)
                elif read_dedup_on and isinstance(result, dict):
                    files_out = result.get("files")
                    if isinstance(files_out, list):
                        # Batch read: de-dup each file independently and re-sum the
                        # surviving per-file savings instead of bypassing dedup.
                        surviving = 0
                        for entry in files_out:
                            if not isinstance(entry, dict) or entry.get("error"):
                                continue
                            state, credit = read_baseline_credit.should_credit(
                                state, entry.get("path"), entry.get("mode")
                            )
                            if not credit:
                                entry.pop("tokens_saved", None)
                            else:
                                surviving += int(entry.get("tokens_saved", 0) or 0)
                        _tool_call_tokens_saved.value = surviving
                    else:
                        mode = result.get("mode")
                        path = result.get("path") or args.get("path")
                        state, credit = read_baseline_credit.should_credit(state, path, mode)
                        if not credit:
                            # Baseline already counted this session -> zero the
                            # saving in BOTH the thread-local and the result so
                            # neither the budget recorder nor the `saved` field
                            # (which reads result['tokens_saved'] first) re-counts it.
                            _tool_call_tokens_saved.value = 0
                            result.pop("tokens_saved", None)
                if code_intel_on and not result_errored:
                    read_paths: list[str] = []
                    single = args.get("path")
                    if isinstance(single, str) and single:
                        read_paths.append(single)
                    files = args.get("files")
                    if isinstance(files, list):
                        for entry in files:
                            if isinstance(entry, str) and entry:
                                read_paths.append(entry)
                            elif isinstance(entry, dict):
                                ep = entry.get("path")
                                if isinstance(ep, str) and ep:
                                    read_paths.append(ep)
                    state = code_intel_credit.consume_reads(state, read_paths)
            elif is_code_intel and isinstance(result, dict) and not result_errored:
                paths = code_intel_credit.extract_credited_paths(name, result)
                state = code_intel_credit.record_pending(state, name, paths)

            if code_intel_on:
                threshold = int(os.environ.get("ATELIER_CODE_INTEL_CREDIT_AGE", "8"))
                state, credits = code_intel_credit.tick_and_credit(state, threshold=threshold)
                for credit_entry in credits:
                    # Deferred credit for an EARLIER call -> sidecar only; never the
                    # current response's `saved` field.
                    _append_savings(credit_entry["tool"], 0, 1, rid=str(rid))

            _write_workspace_session_state(state)
            _tool_accounting_pending_hint = bool(state.get("code_intel_pending"))
    except Exception:
        logging.exception("Recovered from broad exception handler")


def _default_workflow_agent_executor(
    step: Any,
    prompt: str,
    context_state: Any,
    *,
    route: Mapping[str, Any] | None = None,
) -> Any:
    import subprocess

    from atelier.core.capabilities.cross_vendor_routing.configuration import RouteConfigError
    from atelier.core.capabilities.cross_vendor_routing.router import NoFeasibleRouteError

    workspace = _workspace_root().resolve()
    defaults = build_default_registry()
    decision: Any = None
    route_args = route if isinstance(route, Mapping) else {}
    route_mode = str(route_args.get("mode") or "native").strip() or "native"
    explicit_requested = any(str(route_args.get(field) or "").strip() for field in ("provider", "model", "runner"))
    explicit_requested = explicit_requested or route_mode == "explicit"
    cache_policy: OwnedCachePolicy = "fresh" if str(getattr(step, "context_mode", "") or "") == "fresh" else "inherit"
    compiled_prompt = compile_prompt_text(prompt)
    spawn_plan = context_state.spawn_plan_for_step(str(getattr(step, "step_id", "") or ""))
    spawn_envelope = build_spawn_envelope(
        step_id=str(getattr(step, "step_id", "") or ""),
        role_id=str(getattr(step, "role_id", "") or "general"),
        compiled_prompt=compiled_prompt,
        spawn_group_id=str(spawn_plan.get("spawn_group_id") or ""),
        cache_scope_id=str(spawn_plan.get("cache_scope_id") or ""),
        cache_policy=cache_policy,
    )
    affinity_state = (
        latest_cache_affinity(context_state.step_results, context_state.step_order) if cache_policy == "inherit" else {}
    )
    route_state = {
        "workflow_step": str(getattr(step, "step_id", "") or ""),
        "expected_input_tokens": max(1000, len(spawn_envelope.prompt) // 4),
        "session_phase": "execute",
        "spawn_group_id": spawn_envelope.spawn_group_id,
        "cache_scope_id": spawn_envelope.cache_scope_id,
        **cache_affinity_hint({"cache_affinity": affinity_state}),
    }
    if route_mode != "native":
        try:
            decision = _select_owned_execution_route(
                tool_name="agent",
                task_text=prompt,
                mode=route_mode,
                provider=str(route_args.get("provider") or ""),
                model=str(route_args.get("model") or ""),
                runner=str(route_args.get("runner") or ""),
                cache_policy=cache_policy,
                session_state=route_state,
            )
        except (RouteConfigError, NoFeasibleRouteError) as exc:
            if explicit_requested or route_mode == "auto":
                error = f"owned route selection failed: {exc}"
                return {
                    "status": "failed",
                    "output": "",
                    "output_json": {},
                    "execution_receipt": _native_workflow_execution_receipt(
                        defaults=defaults,
                        role_id=str(getattr(step, "role_id", "") or "general"),
                        compiled_prompt=compiled_prompt,
                        spawn_envelope=spawn_envelope.to_dict(),
                        status="failed",
                        error=error,
                        route_mode=route_mode,
                        attempted_route=True,
                    ),
                    "error": error,
                }
    if decision is not None:
        ledger = _get_ledger()
        try:
            execution = execute_owned_prompt(
                spawn_envelope.prompt,
                root=_atelier_root(),
                tool_name="agent",
                task_text=spawn_envelope.prompt,
                decision=decision,
                host_agent=_detect_agent(),
                session_state=route_state,
                allow_fallback=decision.mode == "auto",
                cache_policy=cache_policy,
                compiled_prompt=compiled_prompt.to_dict(),
                spawn_metadata=spawn_envelope.to_dict(),
            )
        except OwnedExecutionError as exc:
            return {
                "status": "failed",
                "output": "",
                "output_json": {},
                "execution_receipt": exc.receipt.to_dict(),
                "duration_seconds": exc.receipt.duration_seconds,
                "cost_usd": exc.receipt.cost_usd,
                "error": str(exc),
            }
        ledger.record_call(
            operation="owned_execution",
            model=execution.receipt.executed_model,
            input_tokens=execution.receipt.input_tokens,
            output_tokens=execution.receipt.output_tokens,
            cache_read_tokens=execution.receipt.cache_read_input_tokens,
            cache_write_tokens=execution.receipt.cache_write_input_tokens,
            modeled_cache_read_tokens=execution.receipt.modeled_cache_read_input_tokens,
            cost_usd=execution.receipt.cost_usd,
            stable_prefix_hash=execution.receipt.stable_prefix_hash,
            prefix_invalidated_reason=execution.receipt.prefix_invalidated_reason,
            cache_evidence=execution.receipt.cache_evidence,
            phase="workflow",
        )
        return {
            "status": "done",
            "output": execution.output,
            "output_json": _parse_workflow_agent_output(execution.output),
            "execution_receipt": execution.receipt.to_dict(),
            "duration_seconds": execution.receipt.duration_seconds,
            "cost_usd": execution.receipt.cost_usd,
        }
    runner = decision.runner if decision is not None else _workflow_runner_profile()
    model = (
        decision.model
        if decision is not None
        else _workflow_runner_model(
            defaults,
            role_id=str(getattr(step, "role_id", "") or "general"),
            workspace=workspace,
            runner=runner,
        )
    )
    lane_key = ":".join(part for part in (spawn_envelope.spawn_group_id, spawn_envelope.role_id) if part)
    observed_lane = context_state.observed_host_lane(lane_key) if lane_key else {}
    selected_runner = str(observed_lane.get("runner") or runner)
    selected_model = str(observed_lane.get("model") or model or "")
    if lane_key and not observed_lane:
        context_state.record_host_lane(lane_key, {"runner": selected_runner, "model": selected_model})
    command = resolve_swarm_runner_command(
        runner=selected_runner,
        runner_model=selected_model,
        runner_args=(),
        child_command=(),
        prompt_template=spawn_envelope.prompt,
    )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            text=True,
            capture_output=True,
            check=False,
            timeout=48 * 60 * 60,  # 48h hard ceiling so a hung host CLI can't wedge the run forever
        )
    except subprocess.TimeoutExpired:
        duration_seconds = time.perf_counter() - started
        error = f"native workflow spawn ({selected_runner}) timed out after 48h"
        return {
            "status": "failed",
            "output": "",
            "output_json": {},
            "execution_receipt": _native_workflow_execution_receipt(
                defaults=defaults,
                runner=selected_runner,
                model=selected_model,
                role_id=str(getattr(step, "role_id", "") or "general"),
                compiled_prompt=compiled_prompt,
                spawn_envelope=spawn_envelope.to_dict(),
                status="failed",
                duration_seconds=duration_seconds,
                observed_fields=_observed_host_fields(
                    spawn_envelope=spawn_envelope.to_dict(),
                    selected_runner=selected_runner,
                    selected_model=selected_model,
                ),
                unverified_fields=_unverified_host_fields(selected_model=selected_model),
                error=error,
                route_mode=route_mode,
            ),
            "error": error,
        }
    duration_seconds = time.perf_counter() - started
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        error = (completed.stderr or output or f"{runner} exited with {completed.returncode}").strip()
        return {
            "status": "failed",
            "output": output,
            "output_json": {},
            "execution_receipt": _native_workflow_execution_receipt(
                defaults=defaults,
                runner=selected_runner,
                model=selected_model,
                role_id=str(getattr(step, "role_id", "") or "general"),
                compiled_prompt=compiled_prompt,
                spawn_envelope=spawn_envelope.to_dict(),
                status="failed",
                duration_seconds=duration_seconds,
                observed_fields=_observed_host_fields(
                    spawn_envelope=spawn_envelope.to_dict(),
                    selected_runner=selected_runner,
                    selected_model=selected_model,
                ),
                unverified_fields=_unverified_host_fields(selected_model=selected_model),
                error=error,
                route_mode=route_mode,
            ),
            "error": error,
        }
    return {
        "status": "done",
        "output": output,
        "output_json": _parse_workflow_agent_output(output),
        "execution_receipt": _native_workflow_execution_receipt(
            defaults=defaults,
            runner=selected_runner,
            model=selected_model,
            role_id=str(getattr(step, "role_id", "") or "general"),
            compiled_prompt=compiled_prompt,
            spawn_envelope=spawn_envelope.to_dict(),
            status="done",
            duration_seconds=duration_seconds,
            observed_fields=_observed_host_fields(
                spawn_envelope=spawn_envelope.to_dict(),
                selected_runner=selected_runner,
                selected_model=selected_model,
            ),
            unverified_fields=_unverified_host_fields(selected_model=selected_model),
            route_mode=route_mode,
        ),
    }


def _workflow_runner_profile() -> str:
    detected = _detect_agent()
    if detected in {"claude", "codex", "copilot", "opencode"}:
        return detected
    return "claude"


def _workflow_runner_model(
    defaults: DefaultRegistry,
    *,
    role_id: str = "general",
    workspace: Path | None = None,
    runner: str | None = None,
) -> str | None:
    resolved_runner = runner or _workflow_runner_profile()
    configured = str(_get_mcp_model() or os.environ.get("ATELIER_MODEL") or "").strip()
    if configured:
        return normalize_model_for_host(resolved_runner, configured)
    return normalize_model_for_host(
        resolved_runner,
        resolve_host_model(resolved_runner, role_id, workspace_root=workspace, fallback=None),
    )


def _native_workflow_execution_receipt(
    *,
    defaults: DefaultRegistry,
    status: str,
    runner: str | None = None,
    model: str | None = None,
    role_id: str = "",
    compiled_prompt: Any | None = None,
    spawn_envelope: dict[str, Any] | None = None,
    duration_seconds: float = 0.0,
    observed_fields: tuple[str, ...] = (),
    unverified_fields: tuple[str, ...] = (),
    error: str = "",
    route_mode: str = "native",
    attempted_route: bool = False,
) -> dict[str, Any]:
    resolved_runner = runner or _workflow_runner_profile()
    resolved_model = model or _workflow_runner_model(defaults) or ""
    resolved_provider = _provider_for_model(resolved_model) if resolved_model else ""
    expose_selection = attempted_route or route_mode == "native"
    compiled = compiled_prompt if hasattr(compiled_prompt, "stable_prefix_hash") else None
    envelope = dict(spawn_envelope or {})
    requested_fields = tuple(str(field) for field in envelope.get("requested_fields", ()))
    honored_fields = ("prompt",)
    dropped_fields = tuple(field for field in requested_fields if field not in honored_fields)
    return {
        "status": status,
        "mode": route_mode,
        "role_id": role_id,
        "selected_provider": resolved_provider if expose_selection else "",
        "selected_model": resolved_model if expose_selection else "",
        "selected_runner": resolved_runner if expose_selection else "",
        "selected_transport": "host-cli" if expose_selection else "",
        "executed_provider": "",
        "executed_model": "",
        "executed_runner": resolved_runner if status == "done" else "",
        "executed_transport": "host-cli" if status == "done" else "",
        "request_id": "",
        "duration_seconds": duration_seconds,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "modeled_cache_read_input_tokens": 0,
        "stable_prefix_hash": getattr(compiled, "stable_prefix_hash", ""),
        "stable_prefix_tokens": getattr(compiled, "stable_prefix_tokens", 0),
        "dynamic_tokens": getattr(compiled, "dynamic_tokens", 0),
        "prefix_invalidated_reason": "cache_policy_fresh" if str(envelope.get("cache_policy") or "") == "fresh" else "",
        "cache_evidence": "hint_only" if getattr(compiled, "stable_prefix_hash", "") else "none",
        "cache_capability": "hint_only" if getattr(compiled, "stable_prefix_hash", "") else "none",
        "spawn_group_id": str(envelope.get("spawn_group_id") or ""),
        "cache_scope_id": str(envelope.get("cache_scope_id") or ""),
        "cache_policy": str(envelope.get("cache_policy") or "inherit"),
        "eligible_for_reuse": bool(
            getattr(compiled, "stable_prefix_hash", "") and str(envelope.get("cache_policy") or "inherit") != "fresh"
        ),
        "reuse_observed": False,
        "spawn_latency_ms": int(duration_seconds * 1000),
        "requested_fields": list(requested_fields),
        "honored_fields": list(observed_fields or honored_fields),
        "dropped_fields": list(dropped_fields),
        "observed_fields": list(observed_fields),
        "unverified_fields": list(unverified_fields),
        "observation_mode": "runtime-observed",
        "cost_usd": 0.0,
        "rerouted": False,
        "attempts": [],
        "error": error,
    }


def _observed_host_fields(
    *,
    spawn_envelope: dict[str, Any],
    selected_runner: str,
    selected_model: str,
) -> tuple[str, ...]:
    observed = ["prompt", "cache_policy", "spawn_group_id", "cache_scope_id"]
    if str(spawn_envelope.get("role_id") or "").strip():
        observed.append("role_id")
    if selected_runner:
        observed.append("selected_runner")
    if selected_model:
        observed.append("selected_model")
    return tuple(observed)


def _unverified_host_fields(*, selected_model: str) -> tuple[str, ...]:
    fields = ["executed_provider", "executed_transport", "reuse_observed"]
    if selected_model:
        fields.append("executed_model")
    return tuple(fields)


def _parse_workflow_agent_output(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _workflow_spawn_summary(step_results: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "step_count": 0,
        "eligible_for_reuse": 0,
        "reuse_observed": 0,
        "spawn_latency_ms": 0,
        "cache_capability_counts": {},
        "host_dropped_fields": {},
    }
    for step_result in step_results.values():
        receipt = getattr(step_result, "execution_receipt", None)
        if not isinstance(receipt, Mapping):
            continue
        if not any(
            key in receipt
            for key in (
                "cache_capability",
                "spawn_group_id",
                "cache_scope_id",
                "requested_fields",
                "dropped_fields",
            )
        ):
            continue
        summary["step_count"] += 1
        summary["eligible_for_reuse"] += int(bool(receipt.get("eligible_for_reuse", False)))
        summary["reuse_observed"] += int(bool(receipt.get("reuse_observed", False)))
        summary["spawn_latency_ms"] += int(receipt.get("spawn_latency_ms", 0) or 0)
        capability = str(receipt.get("cache_capability") or "").strip()
        if capability:
            counts = cast(dict[str, int], summary["cache_capability_counts"])
            counts[capability] = int(counts.get(capability, 0) or 0) + 1
        dropped = receipt.get("dropped_fields")
        if isinstance(dropped, list | tuple):
            for field in dropped:
                field_name = str(field).strip()
                if not field_name:
                    continue
                drop_counts = cast(dict[str, int], summary["host_dropped_fields"])
                drop_counts[field_name] = int(drop_counts.get(field_name, 0) or 0) + 1
    return summary if summary["step_count"] else {}


def _select_owned_execution_route(
    *,
    tool_name: str,
    task_text: str,
    mode: str,
    provider: str,
    model: str,
    runner: str,
    cache_policy: OwnedCachePolicy = "inherit",
    session_state: Mapping[str, Any] | None = None,
) -> Any:
    return select_owned_route(
        _atelier_root(),
        OwnedRouteRequest(
            tool_name=tool_name,
            task_text=task_text,
            mode="explicit" if mode == "explicit" else "auto",
            provider=provider.strip().lower(),
            model=model.strip(),
            runner=runner.strip().lower(),
            host_agent=_detect_agent(),
            cache_policy="fresh" if cache_policy == "fresh" else "inherit",
            session_state=dict(session_state or {}),
        ),
    )


def _normalize_model_id(model_id: str) -> str:
    return model_id.strip().lower().replace(".", "-")


def _provider_for_model(model_id: str) -> str:
    normalized = _normalize_model_id(model_id)
    if not normalized:
        return ""
    if normalized.startswith("claude"):
        return "anthropic"
    if normalized.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    if normalized.startswith("gemini"):
        return "google"
    return "unknown"


_WORKFLOW_SPAWN_DEPTH_LIMIT = 8
# Per-worker-thread workflow spawn depth. The dispatcher runs a thread pool, so
# tracking depth in os.environ races across parallel workflow steps and can leak
# a stale value into the process env; a threading.local isolates it per thread.
_workflow_spawn_depth: threading.local = threading.local()
# Tools that themselves spawn sub-agents/workflows: invoking them from a
# workflow step opens an unbounded recursive spawn path, so they are blocked.
_WORKFLOW_SPAWNING_TOOLS = frozenset({"workflow"})


def _default_workflow_tool_executor(step: Any, args: dict[str, Any], context_state: Any) -> Any:
    if step.tool in _WORKFLOW_SPAWNING_TOOLS:
        raise ValueError(f"workflow steps cannot invoke spawning tool {step.tool!r} (unbounded recursion)")
    spec = TOOLS.get(step.tool)
    if spec is None:
        raise ValueError(f"unknown workflow tool: {step.tool}")
    depth = getattr(_workflow_spawn_depth, "value", 0)
    if depth >= _WORKFLOW_SPAWN_DEPTH_LIMIT:
        raise ValueError(
            f"workflow spawn depth limit ({_WORKFLOW_SPAWN_DEPTH_LIMIT}) exceeded; aborting recursive tool execution"
        )
    handler = cast(Callable[[dict[str, Any]], Any], spec["handler"])
    _workflow_spawn_depth.value = depth + 1
    try:
        return handler(args)
    finally:
        _workflow_spawn_depth.value = depth


def _default_workflow_shell_executor(step: Any, command: str, forked_context: dict[str, Any]) -> Any:
    spec = TOOLS.get("shell")
    if spec is None:
        raise ValueError("shell tool not registered")
    handler = cast(Callable[[dict[str, Any]], Any], spec["handler"])
    return handler({"command": command})


def _run_owned_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
    resume = bool(arguments.get("resume", False))
    # Hold _STATE_LOCK across the whole read-modify-write: atomic os.replace
    # prevents a torn file but not a lost update when a concurrent handler
    # interleaves its own session_state RMW. _STATE_LOCK is an RLock, so the
    # reentrant helper calls below are safe.
    with _STATE_LOCK:
        session_state = _read_workspace_session_state()
        runtime_state = _workflow_runtime_state(session_state)

        workflow_raw = arguments.get("workflow")
        if resume and not isinstance(workflow_raw, Mapping):
            workflow_raw = runtime_state.get("workflow")
        if not isinstance(workflow_raw, Mapping):
            raise ValueError("workflow run requires workflow mapping")
        route_raw = arguments.get("route")
        if resume and not isinstance(route_raw, Mapping):
            route_raw = runtime_state.get("route")
        route = dict(route_raw) if isinstance(route_raw, Mapping) else {}
        review_raw = arguments.get("plan_review")
        plan_review = dict(review_raw) if isinstance(review_raw, Mapping) else {}
        review_decision = _coerce_workflow_review_decision(plan_review)
        definition = workflow_definition_from_mapping(workflow_raw)
        workflow_state = (
            dict(session_state.get("workflow") or {}) if isinstance(session_state.get("workflow"), dict) else {}
        )
        runner_state = (
            WorkflowContextState.from_mapping(runtime_state.get("runner")) if resume else WorkflowContextState()
        )
        runner = WorkflowRunner(
            agent_executor=lambda step, prompt, context_state: _default_workflow_agent_executor(
                step,
                prompt,
                context_state,
                route=route,
            ),
            tool_executor=_default_workflow_tool_executor,
            shell_executor=_default_workflow_shell_executor,
        )
        ledger = _get_ledger()
        result = runner.run(
            definition,
            context_state=runner_state,
            ledger=ledger,
            plan_review_decision=review_decision,
        )
        spawn_summary = _workflow_spawn_summary(result.step_results)
        created_at = str(runtime_state.get("created_at") or "").strip() if resume else ""
        runtime_state = {
            "run_id": result.run_id,
            "workflow_id": definition.workflow_id,
            "workflow": dict(workflow_raw),
            "route": dict(route),
            "status": result.status,
            "step_order": list(result.step_order),
            "current_step": result.paused_step_id
            or result.failed_step_id
            or (result.step_order[-1] if result.step_order else ""),
            "failed_step_id": result.failed_step_id or "",
            "paused_step_id": result.paused_step_id or "",
            "artifact_ids": [],
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "runner": runner_state.to_dict(),
        }
        if spawn_summary:
            runtime_state["spawn_summary"] = dict(spawn_summary)
        if result.status == "awaiting_review":
            workflow_state["current_step"] = "review"
            workflow_state["session_phase"] = "review"
            runtime_state["plan_review"] = {
                "decision": review_decision or "pending",
                "paused_step_id": result.paused_step_id or "",
                "workflow_id": definition.workflow_id,
            }
            ledger.record_workflow_event(
                "plan_review",
                {
                    "workflow_step": "review",
                    "review_decision": "pending",
                    "workflow_id": definition.workflow_id,
                    "step_id": result.paused_step_id or "",
                },
            )
        elif result.status == "review_rejected":
            workflow_state["current_step"] = "review"
            workflow_state["session_phase"] = "review"
            runtime_state["plan_review"] = {
                "decision": review_decision or "revise",
                "paused_step_id": result.paused_step_id or "",
                "workflow_id": definition.workflow_id,
            }
            ledger.record_workflow_event(
                "plan_review",
                {
                    "workflow_step": "review",
                    "review_decision": review_decision or "revise",
                    "workflow_id": definition.workflow_id,
                    "step_id": result.paused_step_id or "",
                },
            )
        else:
            workflow_state["current_step"] = "execution"
            workflow_state["session_phase"] = "execute"
            if review_decision:
                runtime_state["plan_review"] = {
                    "decision": review_decision,
                    "workflow_id": definition.workflow_id,
                }
            if review_decision:
                ledger.record_workflow_event(
                    "plan_review",
                    {
                        "workflow_step": "review",
                        "review_decision": review_decision,
                        "workflow_id": definition.workflow_id,
                    },
                )
        workflow_state["current_task"] = {
            "workflow_id": definition.workflow_id,
            "run_id": result.run_id,
            "step_id": result.paused_step_id
            or result.failed_step_id
            or (result.step_order[-1] if result.step_order else ""),
        }
        workflow_state["task_outputs"] = {
            step_id: step_result.to_dict() for step_id, step_result in result.step_results.items()
        }
        if spawn_summary:
            workflow_state["spawn_summary"] = dict(spawn_summary)
            ledger.record_workflow_event("spawn_summary", dict(spawn_summary))
        if result.status in {"awaiting_review", "review_rejected"}:
            workflow_state["plan_review"] = {
                "decision": review_decision or "pending",
                "paused_step_id": result.paused_step_id or "",
                "workflow_id": definition.workflow_id,
            }
        elif review_decision:
            workflow_state["plan_review"] = {
                "decision": review_decision,
                "workflow_id": definition.workflow_id,
            }
        else:
            workflow_state.pop("plan_review", None)
        workflow_state["updated_at"] = datetime.now(UTC).isoformat()
        session_state["workflow"] = workflow_state
        _write_workflow_runtime_state(session_state, runtime_state)
        _write_workspace_session_state(session_state)
        ledger.persist()
    receipt = {
        "run_id": result.run_id,
        "status": result.status,
        "step_count": len(result.step_order),
        "artifact_ids": [],
    }
    if spawn_summary:
        receipt["spawn_summary"] = dict(spawn_summary)
    if result.failed_step_id:
        receipt["failed_step_id"] = result.failed_step_id
    if result.paused_step_id:
        receipt["paused_step_id"] = result.paused_step_id
    return receipt


WORKFLOW_TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["run", "status", "inspect", "pause", "resume", "stop"],
        },
        "workflow": {"type": "object"},
        "run_id": {"type": "string"},
        "route": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["native", "auto", "explicit"]},
                "provider": {"type": "string"},
                "model": {"type": "string"},
                "runner": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "plan_review": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["approve", "revise", "rerun"]},
            },
            "additionalProperties": False,
        },
        "pause_reason": {"type": "string"},
        "stop_reason": {"type": "string"},
    },
    "required": ["op"],
    "additionalProperties": False,
}


@mcp_tool(name="agent")
def tool_agent(
    prompt: Annotated[
        str,
        Field(description="Full task/instruction for the spawned Atelier-owned sub-agent."),
    ],
    budget: Annotated[
        str,
        Field(description="Cost/quality tier: 'cheap' | 'balanced' | 'best'. Default 'balanced'."),
    ] = "balanced",
    provider: Annotated[
        str,
        Field(description="Force a provider (e.g. 'anthropic'); empty = auto-select from configured vendors."),
    ] = "",
    model: Annotated[
        str,
        Field(description="Force a model id; empty = auto-pick by budget."),
    ] = "",
    cache_policy: Annotated[
        str,
        Field(
            description="'inherit' shares the prompt-cache scope with prior owned spawns (cheaper); 'fresh' starts a new scope."
        ),
    ] = "inherit",
) -> dict[str, Any]:
    """Spawn an Atelier-owned sub-agent and return its result.

    Runs the task on Atelier's owned-execution runtime: it selects a provider and
    model from the credentials already configured in the environment (a provider
    API key when present, otherwise the installed host CLI), executes the prompt,
    and shares a prompt-cache scope with sibling spawns when
    ``cache_policy='inherit'``. Prefer this over the host ``Agent`` tool when you
    want Atelier to control the sub-agent's model, cost, and cache affinity.
    """
    root = _workspace_root()
    session_state = _read_workspace_session_state()
    norm_cache: OwnedCachePolicy = "fresh" if str(cache_policy).strip().lower() == "fresh" else "inherit"
    use_explicit = bool(provider.strip() and model.strip())
    request = OwnedRouteRequest(
        tool_name="agent",
        task_text=prompt,
        mode="explicit" if use_explicit else "auto",
        budget=cast(Any, str(budget).strip().lower() or "balanced"),
        provider=provider.strip(),
        model=model.strip(),
        host_agent=_detect_agent(),
        cache_policy=norm_cache,
        session_state=session_state,
    )
    try:
        decision = select_owned_route(root, request)
    except (NoFeasibleRouteError, RouteConfigError) as exc:
        return {
            "isError": True,
            "status": "no_route",
            "message": (
                f"No owned-execution route available: {exc}. Configure a route config (route.yaml) "
                "plus a provider API key in the environment or an installed host CLI, and enable "
                "owned routing."
            ),
        }
    try:
        result = execute_owned_prompt(
            prompt,
            root=root,
            tool_name="agent",
            task_text=prompt,
            decision=decision,
            host_agent=_detect_agent(),
            session_state=session_state,
            cache_policy=norm_cache,
        )
    except OwnedExecutionError as exc:
        return {
            "isError": True,
            "status": "failed",
            "message": str(exc),
            "receipt": exc.receipt.to_dict(),
        }
    receipt = result.receipt
    return {
        "status": receipt.status,
        "output": result.output,
        "provider": receipt.executed_provider,
        "model": receipt.executed_model,
        "transport": receipt.executed_transport,
        "cost_usd": receipt.cost_usd,
        "tokens": {
            "input": receipt.input_tokens,
            "output": receipt.output_tokens,
            "cache_read": receipt.cache_read_input_tokens,
            "cache_write": receipt.cache_write_input_tokens,
        },
        "cache": {
            "evidence": receipt.cache_evidence,
            "reuse_observed": receipt.reuse_observed,
            "scope_id": receipt.cache_scope_id,
        },
    }


@mcp_tool(name="workflow", input_schema=WORKFLOW_TOOL_INPUT_SCHEMA)
def tool_workflow(
    op: str,
    workflow: dict[str, Any] | None = None,
    run_id: str | None = None,
    route: dict[str, Any] | None = None,
    plan_review: dict[str, Any] | None = None,
    pause_reason: str | None = None,
    stop_reason: str | None = None,
) -> dict[str, Any]:
    """Run or inspect Atelier's durable workflow runtime.

    Ops:
      run     — execute a workflow synchronously from a fresh runtime state
      status  — inspect the persisted workflow runtime for this workspace
      inspect — inspect spawn/cache receipts for the persisted workflow runtime
      pause   — mark the persisted workflow runtime paused (does not cancel a live synchronous call)
      resume  — continue the persisted workflow runtime using its stored workflow and route
      stop    — mark the persisted workflow runtime stopped (does not cancel a live synchronous call)
    """
    normalized_op = op.strip().lower()
    if normalized_op == "run":
        return _run_owned_workflow({"workflow": workflow or {}, "route": route or {}, "plan_review": plan_review or {}})
    # Hold _STATE_LOCK across the read so the pause/stop read-modify-write below
    # cannot lose a concurrent handler's session_state update. _STATE_LOCK is an
    # RLock; the resume branch reacquires it reentrantly via _run_owned_workflow.
    with _STATE_LOCK:
        session_state = _read_workspace_session_state()
        if normalized_op == "status":
            return _coerce_workflow_runtime_status(session_state)
        if normalized_op == "inspect":
            return _inspect_workflow_runtime(session_state)
        if normalized_op not in {"pause", "resume", "stop"}:
            return {
                "isError": True,
                "status": "unsupported_op",
                "message": f"unsupported workflow op: {op}",
            }
        _require_active_workflow_runtime(session_state, run_id or "")
        if normalized_op == "resume":
            arguments: dict[str, Any] = {"resume": True, "plan_review": plan_review or {}}
            if workflow is not None:
                arguments["workflow"] = workflow
            if route is not None:
                arguments["route"] = route
            return _run_owned_workflow(arguments)
        if normalized_op == "pause":
            _pause_workflow_runtime(
                session_state,
                run_id=run_id or "",
                pause_reason=str(pause_reason or ""),
            )
            _write_workspace_session_state(session_state)
            return _coerce_workflow_runtime_status(session_state)
        if normalized_op == "stop":
            _stop_workflow_runtime(
                session_state,
                run_id=run_id or "",
                stop_reason=str(stop_reason or ""),
            )
            _write_workspace_session_state(session_state)
            return _coerce_workflow_runtime_status(session_state)
    raise AssertionError(f"unreachable workflow op: {op!r}")  # op is guaranteed pause/resume/stop above


def _inspect_workflow_runtime(session_state: dict[str, Any]) -> dict[str, Any]:
    status = _coerce_workflow_runtime_status(session_state)
    runtime_state = _workflow_runtime_state(session_state)
    runner_state = WorkflowContextState.from_mapping(runtime_state.get("runner"))
    step_spawns: list[dict[str, Any]] = []
    for step_id in runner_state.step_order:
        step_result = runner_state.step_results.get(step_id)
        if step_result is None:
            continue
        receipt = step_result.execution_receipt
        if not isinstance(receipt, Mapping):
            continue
        if not any(
            key in receipt
            for key in (
                "cache_capability",
                "spawn_group_id",
                "cache_scope_id",
                "requested_fields",
                "dropped_fields",
            )
        ):
            continue
        step_spawns.append(
            {
                "step_id": step_id,
                "status": step_result.status,
                "mode": str(receipt.get("mode") or ""),
                "role_id": str(receipt.get("role_id") or ""),
                "cache_capability": str(receipt.get("cache_capability") or ""),
                "eligible_for_reuse": bool(receipt.get("eligible_for_reuse", False)),
                "reuse_observed": bool(receipt.get("reuse_observed", False)),
                "spawn_latency_ms": int(receipt.get("spawn_latency_ms", 0) or 0),
                "spawn_group_id": str(receipt.get("spawn_group_id") or ""),
                "cache_scope_id": str(receipt.get("cache_scope_id") or ""),
                "requested_fields": list(receipt.get("requested_fields") or []),
                "honored_fields": list(receipt.get("honored_fields") or []),
                "dropped_fields": list(receipt.get("dropped_fields") or []),
            }
        )
    spawn_summary = runtime_state.get("spawn_summary") if isinstance(runtime_state.get("spawn_summary"), dict) else {}
    return {
        **status,
        "spawn_summary": spawn_summary,
        "step_spawns": step_spawns,
    }


def _grounded_benchmark_mode_enabled() -> bool:
    raw_mode = os.environ.get("ATELIER_BENCH_MODE")
    if raw_mode is None:
        return False
    from atelier.bench.mode import is_off as _bench_is_off

    return not _bench_is_off()


def _workspace_session_id(state: dict[str, Any] | None = None) -> str:
    session_state = state if state is not None else _read_workspace_session_state()
    session_id = str(session_state.get("session_id") or session_state.get("active_session_id") or "").strip()
    return session_id or _get_claude_session_id()


def _record_grounding_evidence_if_available(tool_name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    targets = extract_grounding_targets(
        tool_name,
        args=args,
        result=result,
        workspace_root=os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd(),
    )
    if not targets:
        return
    # Hold _STATE_LOCK across the read-modify-write so a concurrent handler's
    # session_state update is not lost. _STATE_LOCK is an RLock.
    with _STATE_LOCK:
        state = _read_workspace_session_state()
        session_id = _workspace_session_id(state)
        if not session_id:
            return
        updated = record_grounding_evidence(
            state,
            session_id=session_id,
            tool_name=tool_name,
            targets=targets,
            workspace_root=os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd(),
        )
        if updated != state:
            _write_workspace_session_state(updated)


def _benchmark_edit_block_message(args: dict[str, Any]) -> str | None:
    if not _grounded_benchmark_mode_enabled():
        return None
    edits = args.get("edits")
    if not isinstance(edits, list):
        return None
    targets = list(_collect_touched_paths(edits).keys())
    if not targets:
        return None
    state = _read_workspace_session_state()
    session_id = _workspace_session_id(state)
    missing = missing_grounding_targets(
        state,
        session_id=session_id,
        targets=targets,
        workspace_root=os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd(),
    )
    if not missing:
        return None
    target_list = ", ".join(missing[:4])
    return (
        "Benchmark edit gate requires grounding evidence before editing. "
        f"Ground the target with read, grep, search, symbols, node, explore, callers, "
        f"callees, or usages first: {target_list}"
    )


def _register_mcp_session() -> None:
    """Create this MCP process's registration file if it doesn't exist yet."""
    f = _mcp_session_file()
    if f.exists():
        return
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        ws = str(Path(os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()).resolve())
        import hashlib as _hl2

        data = {
            "atelier_mcp_id": _MCP_ID,
            "pid": os.getpid(),
            "workspace": ws,
            "workspace_hash": _hl2.sha256(ws.encode()).hexdigest()[:12],
            "started_at": datetime.utcnow().isoformat(),
            "claude_session_id": "",
            "model": "",
        }
        f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        # Best-effort sidecar registration; a failed write must not break startup.
        _log.debug("MCP session registration write failed", exc_info=True)


def _get_claude_session_id() -> str:
    """Return the Claude Code session UUID.

    Reads workspace session_state.json once (written by SessionStart hook),
    caches the result in _cached_claude_session_id for all subsequent calls.
    Falls back to MCP registration file for backward compatibility.
    Falls back to the product session UUID if not yet populated.
    """
    global _cached_claude_session_id, _cached_mcp_model
    if _cached_claude_session_id:
        return _cached_claude_session_id

    # CLAUDE_CODE_SESSION_ID is set per MCP process by Claude Code, so it is the
    # authoritative session identity even with concurrent sessions in one
    # workspace. Prefer it over the shared workspace bridge.
    env_sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if env_sid:
        _cached_claude_session_id = env_sid
        return env_sid

    sid, model = _read_workspace_session_bridge()
    if sid:
        _cached_claude_session_id = sid
        _cached_mcp_model = model
        return sid

    try:
        f = _mcp_session_file()
        if f.is_file():
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                sid = str(data.get("claude_session_id") or "").strip()
                if sid:
                    _cached_claude_session_id = sid
                    _cached_mcp_model = str(data.get("model") or "").strip()
                    return sid
    except (OSError, json.JSONDecodeError):
        _log.debug("MCP session id read failed", exc_info=True)
    return _get_product_session_id()


def _get_mcp_model() -> str:
    """Return the model string last written by SessionStart, or empty string."""
    global _cached_mcp_model
    if not _cached_claude_session_id:
        # Try to populate both caches via workspace bridge read.
        _get_claude_session_id()

    # Re-read model from workspace bridge on each call — SessionStart may fire
    # again on resume/compact with a different model. Only trust it when the
    # bridge belongs to this session; otherwise a sibling session sharing the
    # workspace could hand us a wrong model. The live transcript model (preferred
    # in _append_savings) covers the common case; this is a pre-first-turn fallback.
    sid, model = _read_workspace_session_bridge()
    if sid and model and sid == _claude_session_id():
        _cached_mcp_model = model
        return _cached_mcp_model

    # Backward-compatible fallback to MCP session file.
    try:
        f = _mcp_session_file()
        if f.is_file():
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _cached_mcp_model = str(data.get("model") or "").strip()
    except (OSError, json.JSONDecodeError):
        _log.debug("MCP model read failed", exc_info=True)
    return _cached_mcp_model


def _get_host_session_sidecar_path() -> Path:
    """Return per-session sidecar path for the current host.

    Priority:
    1. Claude: CLAUDE_CODE_SESSION_ID (set per MCP process by Claude Code), then
       the workspace bridge / MCP session file (written by the SessionStart hook).
    2. All other hosts: native session-ID env var exposed to the MCP process.
    3. Fallback: workspace-scoped file (no per-session isolation).
    """
    # 1. Per-process Claude session id, then the SessionStart-written fallbacks.
    #    The env var is unique per session, so concurrent sessions sharing one
    #    workspace no longer write into each other's sidecar.
    sid = _claude_session_id()
    if not sid:
        try:
            f = _mcp_session_file()
            if f.is_file():
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    sid = str(data.get("claude_session_id") or "").strip()
        except (OSError, json.JSONDecodeError):
            _log.debug("MCP sidecar session id read failed", exc_info=True)
    if sid:
        return _atelier_root() / "sessions" / sid / "savings.jsonl"

    # 2. Other hosts — use their native session ID env var directly.
    _HOST_SESSION_ENVS: list[tuple[str, str]] = [
        ("CODEX_SESSION_ID", "codex"),
        ("OPENCODE_SESSION_ID", "opencode"),
        ("GITHUB_COPILOT_SESSION_ID", "copilot"),
        ("CURSOR_SESSION_ID", "cursor"),
        ("CURSOR_TRACE_ID", "cursor"),
        ("HERMES_SESSION_ID", "hermes"),
        ("ANTIGRAVITY_SESSION_ID", "antigravity"),
        ("AGY_SESSION_ID", "antigravity"),
    ]
    for env_var, _host in _HOST_SESSION_ENVS:
        env_sid = os.environ.get(env_var, "").strip()
        if env_sid:
            return _atelier_root() / "sessions" / env_sid / "savings.jsonl"

    return _workspace_savings_path()


def _current_context_state() -> tuple[int, str]:
    """Measured (context size, model) from the host transcript's last usage entry.

    Context size is input + cache_read + cache_creation tokens of the most
    recent usage entry; model is the one that produced it — the per-turn ground
    truth, unlike the SessionStart bridge which goes stale when the user
    switches models mid-session via /model. Returns (0, "") when no
    transcript/usage is available. Callers must treat 0/"" as "unknown" and
    skip pricing — never synthesize values.

    Cached on the candidate transcripts' (path, mtime_ns, size) signature: this
    runs on every savings-bearing tool call, so we re-tail and JSON-parse the
    64 KB window only when a transcript actually changed.
    """
    try:
        from atelier.core.capabilities.savings_summary import (
            claude_transcript_candidates,
            is_real_model,
        )

        sid = _claude_session_id()
        if not sid:
            return 0, ""

        candidates = list(claude_transcript_candidates(sid))
        sig_parts: list[tuple[str, int, int]] = []
        for cand in candidates:
            try:
                st = os.stat(cand)
            except OSError:
                continue
            sig_parts.append((str(cand), st.st_mtime_ns, st.st_size))
        sig = tuple(sig_parts)

        with _STATE_LOCK:
            cached = _CONTEXT_STATE_CACHE.get(sid)
        if cached is not None and cached[0] == sig:
            return cached[1]

        from atelier.gateway.hosts.context_state import _tail_lines

        result: tuple[int, str] = (0, "")
        for cand in candidates:
            try:
                tail_lines = _tail_lines(cand)
            except OSError:
                continue
            best = 0
            best_model = ""
            for line in tail_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # first line of the tail window may be partial
                msg = entry.get("message") or {}
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not isinstance(usage, dict):
                    continue
                ctx = (
                    int(usage.get("input_tokens", 0) or 0)
                    + int(usage.get("cache_read_input_tokens", 0) or 0)
                    + int(usage.get("cache_creation_input_tokens", 0) or 0)
                )
                if ctx > 0:
                    best = ctx
                    candidate = str(msg.get("model") or "").strip()
                    if is_real_model(candidate):
                        best_model = candidate
            if best > 0:
                result = (best, best_model)
                break

        with _STATE_LOCK:
            _CONTEXT_STATE_CACHE[sid] = (sig, result)
        return result
    except Exception:
        logging.exception("Recovered from broad exception handler")
        _log.debug("context state probe failed", exc_info=True)
    return 0, ""


def _price_avoided_calls_usd(model: str, calls_saved: int, ctx_tokens: int) -> float:
    """Price avoided tool-call round trips at *model*'s CACHE-READ rate.

    Each avoided call is an API round trip that would have re-read the
    current context (``ctx_tokens``, measured from the host transcript) at
    the cache-read rate. Unknown model or unmeasured context → 0.0 (no guess).
    """
    if calls_saved <= 0 or ctx_tokens <= 0 or not model or model == "_default":
        return 0.0
    from atelier.core.capabilities.pricing import get_model_pricing

    pricing = get_model_pricing(model)
    if pricing is None or not pricing.known or pricing.cache_read <= 0:
        return 0.0
    return pricing.tokens_to_usd(int(calls_saved) * int(ctx_tokens), "cache_read")


def _append_savings(tool_name: str, tokens_saved: int, calls_saved: int, rid: str = "") -> None:
    """Append one per-call savings row to ``sessions/<id>/savings.jsonl``.

    This single sidecar is the source of truth read by the live statusline,
    the stop hook, and the session report. Each row carries the raw
    ``tokens``/``calls`` plus the pre-priced ``cost_saved_usd`` /
    ``calls_usd`` so analytics readers need not re-price.
    """
    if tokens_saved <= 0 and calls_saved <= 0:
        return
    _register_mcp_session()
    ts = datetime.utcnow().isoformat()
    # Per-turn model truth from the transcript beats the SessionStart bridge,
    # which goes stale when the user switches models mid-session via /model.
    ctx_tokens, live_model = _current_context_state()
    model = live_model or _get_mcp_model()
    calls_usd = 0.0
    if calls_saved > 0 and ctx_tokens > 0:
        calls_usd = round(_price_avoided_calls_usd(model, calls_saved, ctx_tokens), 6)
    cost_saved = round(_price_tokens_saved_usd(model, tokens_saved), 6)
    try:
        path = _get_host_session_sidecar_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "tool": tool_name,
            # Field names match the in-response `saved: {tokens, calls}` shape.
            # The file lives under sessions/<id>/ so "savings" is implicit
            # from context — no need to suffix the keys.
            "tokens": int(tokens_saved),
            "calls": int(calls_saved),
            "model": model,
            "ts": ts,
        }
        # Pre-priced USD so the session report / analytics need not re-price.
        # Omitted when zero to keep rows lean; readers treat missing as 0.
        if cost_saved > 0:
            entry["cost_saved_usd"] = cost_saved
        if calls_usd > 0:
            entry["calls_usd"] = calls_usd
            entry["ctx_tokens"] = ctx_tokens
        if rid:
            entry["rid"] = rid
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        logging.exception("Recovered from broad exception handler")
        # Best-effort savings sidecar; a failed write must not break the tool call.
        _log.debug("savings sidecar append failed", exc_info=True)


def _append_workspace_savings(tool_name: str, tokens_saved: int, calls_saved: int, rid: str = "") -> None:
    """Backward-compat shim — delegates to _append_savings."""
    _append_savings(tool_name, tokens_saved, calls_saved, rid=rid)


def _mcp_debug_enabled() -> bool:
    if os.environ.get("ATELIER_MCP_DEBUG", "0") not in ("0", "", "false", "no"):
        return True
    # Auto-enable in dev installations (marker written by make dev / scripts/local.sh).
    try:
        return (_atelier_root() / ".dev_mode").exists()
    except Exception:  # noqa: BLE001
        return False


def _mcp_debug_path() -> Path:
    return _atelier_root() / "mcp_debug.jsonl"


_DEBUG_LARGE_KEYS = frozenset({"new_string", "old_string", "content", "prompt", "task", "query"})

# Argument keys whose values carry credentials/PII (DSNs, tokens, passwords).
# These are masked regardless of length before anything is written to the debug
# log or shipped to telemetry — the 300-char large-value threshold misses short
# secrets such as a sql `connection_string` or a bearer token.
_DEBUG_SECRET_KEY_RE = re.compile(
    r"(connection_string|dsn|api[_-]?key|token|secret|password|authorization)",
    re.IGNORECASE,
)


def _scrub_args_for_debug(args: dict[str, Any]) -> dict[str, Any]:
    """Sanitize tool args before they are logged or emitted as telemetry.

    Two transforms, applied in order:
      1. Secret-bearing keys (connection_string/dsn/api_key/token/secret/
         password/authorization, case-insensitive) have their value masked
         regardless of length so short DSNs/tokens never leak verbatim.
      2. Remaining large string values (>300 chars, or known large-value keys)
         are replaced with ``<N chars>`` to keep the debug log small.
    """

    def _scrub_value(key: str | None, value: Any) -> Any:
        if isinstance(key, str) and _DEBUG_SECRET_KEY_RE.search(key):
            return "<redacted>"
        if isinstance(value, dict):
            return {kk: _scrub_value(kk, vv) for kk, vv in value.items()}
        if isinstance(value, list):
            return [_scrub_value(None, item) for item in value]
        if isinstance(value, str) and (key in _DEBUG_LARGE_KEYS or len(value) > 300):
            return f"<{len(value)} chars>"
        return value

    return {k: _scrub_value(k, v) for k, v in args.items()}


def _append_mcp_debug_event(
    *,
    tool: str,
    args: dict[str, Any],
    duration_ms: int,
    response_size: int,
    status: str,
    error: str | None = None,
    session_id: str = "",
) -> None:
    """Write a per-call debug record to ~/.atelier/mcp_debug.jsonl.

    Only active when ATELIER_MCP_DEBUG=1. Fail-open: errors are swallowed
    so the MCP server is never disrupted by the debug log writer.
    """
    if not _mcp_debug_enabled():
        return
    try:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "tool": tool,
            "args": _scrub_args_for_debug(args),
            "duration_ms": duration_ms,
            "response_size_bytes": response_size,
            "status": status,
            "session_id": session_id,
        }
        if error:
            entry["error"] = error
        path = _mcp_debug_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001
        pass  # never disrupt the server


def _smart_state_path() -> Path:
    return _atelier_root() / "smart_state.json"


def _read_smart_state() -> dict[str, Any]:
    path = _smart_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return {}


def _write_smart_state(state: dict[str, Any]) -> None:
    try:
        path = _smart_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: a torn smart_state.json would corrupt cumulative
        # counters, so stage to a temp file and os.replace into place.
        tmp_path: str | None = None
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(state, handle, indent=2)
            tmp_path = handle.name
        Path(tmp_path).replace(path)
    except Exception:
        logging.exception("Recovered from broad exception handler")
        logger.warning("Suppressed exception while writing smart_state", exc_info=True)


def _coerce_saved_tokens(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return int(max(0.0, value))
    if isinstance(value, dict):
        return sum(
            int(max(0.0, float(item_value)))
            for item_value in value.values()
            if isinstance(item_value, (int, float)) and not isinstance(item_value, bool)
        )
    return 0


def _extract_compact_output_tokens_saved(result: dict[str, Any]) -> int:
    return _coerce_saved_tokens(result.get("tokens_saved_vs_naive"))


def _extract_tokens_saved(result: dict[str, Any]) -> int:
    direct = _coerce_saved_tokens(result.get("tokens_saved"))
    if direct > 0:
        return direct
    # Check thread-local written by tool handlers that strip tokens_saved before returning
    tl = getattr(_tool_call_tokens_saved, "value", 0)
    if tl > 0:
        return tl
    return _extract_compact_output_tokens_saved(result)


def _record_smart_state_savings(tokens_saved: int, calls_avoided: int) -> None:
    if tokens_saved <= 0 and calls_avoided <= 0:
        return
    # Serialize the read-modify-write so concurrent tool calls can't lose an
    # update to the cumulative counters. _STATE_LOCK is an RLock.
    with _STATE_LOCK:
        state = _read_smart_state()
        savings = state.get("savings")
        if not isinstance(savings, dict):
            savings = {"calls_avoided": 0, "tokens_saved": 0}
        savings["calls_avoided"] = int(savings.get("calls_avoided", 0) or 0) + max(0, calls_avoided)
        savings["tokens_saved"] = int(savings.get("tokens_saved", 0) or 0) + max(0, tokens_saved)
        state["savings"] = savings
        _write_smart_state(state)


class _NoOpContextBudgetRecorder:
    """No-op recorder for service-backed MCP state."""

    def record(self, **kwargs: Any) -> None:
        pass

    def record_compact_tool_output(self, **kwargs: Any) -> None:
        pass

    def aggregate_run(self, session_id: str) -> Any:
        return {}


def _get_context_budget_recorder() -> Any:
    global _context_budget_recorder
    if _service_backed_state():
        return _NoOpContextBudgetRecorder()
    if _context_budget_recorder is None:
        try:
            from atelier.core.capabilities.telemetry.context_budget import ContextBudgetRecorder
            from atelier.infra.storage.factory import create_store

            store = create_store(_atelier_root())
            store.init()
            _context_budget_recorder = ContextBudgetRecorder(store)
        except Exception:
            logging.exception("Recovered from broad exception handler")
            _context_budget_recorder = _NoOpContextBudgetRecorder()
    return _context_budget_recorder


_REDACTION_PLACEHOLDER_RE = re.compile(r"<redacted[^>]*>")


def _core_runtime() -> Any:
    return _runtime().core_runtime


def _redact_memory_input(text: str, field_name: str) -> str:
    if _REDACTION_PLACEHOLDER_RE.search(text):
        return text
    redacted = redact(text)
    if not text:
        return redacted
    remaining = _REDACTION_PLACEHOLDER_RE.sub("", redacted)
    if len(remaining.strip()) < len(text.strip()) * 0.5:
        raise ValueError(f"{field_name} rejected: likely secret leakage")
    return redacted


def _memory_store() -> Any:
    return make_memory_store(_atelier_root())


def _archival_recall() -> ArchivalRecallCapability:
    return ArchivalRecallCapability(_memory_store(), make_embedder(), redactor=redact)


def _symbol_recall() -> Any:
    from atelier.core.capabilities.archival_recall.symbol_recall import SymbolRecallCapability
    from atelier.core.foundation.store import ContextStore

    workspace_root = _workspace_root()
    trace_store = ContextStore(_atelier_root())
    trace_store.init()
    return SymbolRecallCapability(
        repo_root=workspace_root,
        engine=_code_context_engine(str(workspace_root)),
        memory_store=_memory_store(),
        trace_store=trace_store,
    )


def _workspace_path(file_path: str) -> Path:
    p = Path(file_path)
    if p.is_absolute():
        return p
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    return Path(workspace) / p


# N10 — per-request project isolation. The stdio MCP server normally serves a
# single workspace resolved from env/cwd. A request may instead carry an
# ``Mcp-Project-Path``-style override (via ``params._meta`` or a reserved
# ``project_path`` arg); when present we serve that repo for the duration of the
# request only. The executor runs each request on its own worker thread, so a
# thread-local override is naturally request-scoped and keeps per-repo isolation.
# Absent override -> today's single-workspace behavior is unchanged.
_request_project: threading.local = threading.local()


def _http_project_override_allowed() -> bool:
    """H1 opt-in: whether a wire-supplied project override may be honored at all.

    Default OFF. Resolving an arbitrary host directory from the wire lets a
    caller pivot the server outside its workspace, so acceptance is gated behind
    ``ATELIER_HTTP_ALLOW_PROJECT_OVERRIDE`` AND confined to the workspace root.
    """
    return os.environ.get("ATELIER_HTTP_ALLOW_PROJECT_OVERRIDE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _project_override_root() -> Path:
    """The allowlisted root a wire-supplied project override must stay inside."""
    root = (
        os.environ.get("CLAUDE_WORKSPACE_ROOT")
        or os.environ.get("ATELIER_WORKSPACE_ROOT")
        or os.environ.get("VSCODE_CWD")
        or os.getcwd()
    )
    return Path(root).expanduser().resolve()


def _is_within_root(candidate: Path, root: Path) -> bool:
    """True iff ``candidate`` is ``root`` or nested under it (no parent escape)."""
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _set_request_project(path: str | None) -> str | None:
    """Set the request-scoped project override; return the prior value.

    Only an existing directory is accepted; anything else clears the override so
    a bad header can never silently mis-route to a non-repo path.

    H1 — a wire-supplied path can point ANYWHERE on the host. Acceptance is
    therefore gated behind the explicit ``ATELIER_HTTP_ALLOW_PROJECT_OVERRIDE``
    opt-in AND confined to the workspace root: a candidate outside the root is
    rejected (override cleared) so the default never pivots out of bounds.
    """
    prior = getattr(_request_project, "value", None)
    resolved: str | None = None
    if isinstance(path, str) and path.strip() and _http_project_override_allowed():
        try:
            candidate = Path(path).expanduser().resolve()
            if candidate.is_dir() and _is_within_root(candidate, _project_override_root()):
                resolved = str(candidate)
        except OSError:
            resolved = None
    _request_project.value = resolved
    return prior


def _clear_request_project(prior: str | None) -> None:
    _request_project.value = prior


def _extract_request_project(params: dict[str, Any], args: dict[str, Any]) -> str | None:
    """Pull an ``Mcp-Project-Path``-style override from a tools/call request.

    Checks, in order: ``params._meta`` (the MCP metadata channel) under any of
    the conventional keys, then a reserved ``project_path`` argument. The arg is
    popped so it never reaches the tool handler. Returns ``None`` when absent so
    the default single-workspace path is preserved.
    """
    meta = params.get("_meta")
    if isinstance(meta, dict):
        for key in ("mcp-project-path", "projectPath", "project_path", "projectRoot", "project_root"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value
    if isinstance(args, dict):
        value = args.pop("project_path", None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _workspace_root() -> Path:
    # A request-scoped project override (N10) wins for the lifetime of the
    # request; everything else falls back to the single-workspace resolution.
    override = getattr(_request_project, "value", None)
    if isinstance(override, str) and override:
        return Path(override)
    workspace = (
        os.environ.get("CLAUDE_WORKSPACE_ROOT")
        or os.environ.get("ATELIER_WORKSPACE_ROOT")
        or os.environ.get("VSCODE_CWD")
        or os.getcwd()
    )
    return Path(workspace)


def _claude_additional_dirs(workspace_root: Path) -> list[Path]:
    """Extra directories allowed for edits beyond *workspace_root*.

    Merges two sources in order:
    1. ``ATELIER_ADDITIONAL_DIRS`` — colon-separated env var (highest priority).
    2. ``additionalDirectories`` array in ``~/.claude/settings.json`` and
       ``<workspace>/.claude/settings.json`` (mirrors what Claude Code's
       ``--add-dir`` flag persists).

    Read-only tools (grep/search/read) already accept any absolute path, so
    this only affects write operations (edit, batch-edit).
    """
    dirs: list[Path] = []

    env_raw = os.environ.get("ATELIER_ADDITIONAL_DIRS", "").strip()
    for raw in env_raw.split(":"):
        raw = raw.strip()
        if raw:
            try:
                dirs.append(Path(raw).expanduser().resolve())
            except (OSError, ValueError):
                pass

    for sp in (
        Path.home() / ".claude" / "settings.json",
        workspace_root / ".claude" / "settings.json",
    ):
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            for raw in data.get("additionalDirectories", []):
                if isinstance(raw, str) and raw.strip():
                    try:
                        dirs.append(Path(raw).expanduser().resolve())
                    except (OSError, ValueError):
                        pass
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    return dirs


# Thread-local slot for passing real tokens_saved from tool handlers to the
# budget recorder without polluting the LLM-facing response dict.
_tool_call_tokens_saved: threading.local = threading.local()
_tool_call_rendered_text: threading.local = threading.local()
# Raw structured result of the last tool call, stashed per-call for the in-process
# `atelier tools call ... --json` CLI to recover the full dict. Never serialized
# into the host-facing MCP response, so the host's main model only sees `content`.
_tool_call_raw_result: threading.local = threading.local()


def _bootstrap_context_status(root: Path) -> dict[str, Any]:
    from atelier.core.capabilities.code_context import CodeContextEngine
    from atelier.core.service.bootstrap_context import bootstrap_status, missing_bootstrap_labels
    from atelier.core.service.jobs import JOB_BOOTSTRAP_CONTEXT
    from atelier.infra.storage.factory import create_store

    repo_root = _workspace_root().resolve()
    repo_id = CodeContextEngine(repo_root).repo_id
    memory_store = _memory_store()
    state = bootstrap_status(memory_store, repo_id)
    store = create_store(root)
    store.init()
    jobs = [
        job
        for job in store.list_jobs(job_type=JOB_BOOTSTRAP_CONTEXT, limit=200)
        if isinstance(job.get("payload"), dict) and job["payload"].get("repo_id") == repo_id
    ]
    queued = False
    # Only block re-queueing if there is an already-active (pending or running) job.
    # Failed/dead jobs should not permanently prevent retrying bootstrap.
    active_job = next((job for job in jobs if job["status"] in {"pending", "running"}), None)
    job_id: str | None = None
    if state != "warm" and active_job is None:
        job_id = store.enqueue_job(
            JOB_BOOTSTRAP_CONTEXT,
            {"repo_root": str(repo_root), "repo_id": repo_id},
        )
        queued = True
    status = "warm" if state == "warm" else ("warming" if queued or active_job or job_id else state)
    return {
        "repo_id": repo_id,
        "queued": queued,
        "job_id": job_id,
        "status": status,
        "missing_labels": missing_bootstrap_labels(memory_store, repo_id),
    }


@mcp_tool(name="context")
def tool_get_context(
    task: str,
    domain: str | None = None,
    files: list[str] | None = None,
    keywords: list[str] | None = None,
    excluded_paths: list[str] | None = None,
    tools: list[str] | None = None,
    errors: list[str] | None = None,
    max_blocks: int = 5,
    token_budget: int | None = 2000,
    dedup: bool = True,
    agent_id: str | None = None,
    recall: bool = True,
    mode: Literal["procedures", "symbols", "pull"] = "procedures",
) -> dict[str, Any]:
    """Record task context and retrieve relevant Playbooks for the task.

    Call at task start to seed context with prior procedures, repo bootstrap
    knowledge, and per-agent memory. mode="symbols" returns the most relevant
    code symbols/files from the SCIP index instead; mode="pull" returns scoped
    subtask context (files/keywords/excluded_paths scope it).

    Args: task (required) drives ranking; domain narrows retrieval; files boost
    related blocks; tools/errors rank matching procedure and rescue blocks;
    max_blocks (default 5); token_budget (default 2000, None = unlimited);
    dedup; agent_id loads per-agent memory; recall=False skips memory recall.
    """
    if mode == "symbols":
        engine = _code_context_engine(".")
        return cast(
            dict[str, Any],
            engine.tool_context(
                task=task,
                seed_files=files or [],
                budget_tokens=token_budget or 4000,
                max_symbols=max_blocks,
            ),
        )
    if mode == "pull":
        from atelier.core.capabilities.scoped_context import Subtask

        subtask = Subtask(
            description=task,
            affected_paths=files or [],
            keywords=keywords or [],
            excluded_paths=excluded_paths or [],
            budget_tokens=token_budget or 4000,
        )
        return cast(dict[str, Any], _scoped_context_capability(".").pull(subtask).to_dict())
    if mode != "procedures":
        raise ValueError(f"unknown mode: {mode!r}")
    if errors is None:
        errors = []
    if tools is None:
        tools = []
    if keywords is None:
        keywords = []
    if excluded_paths is None:
        excluded_paths = []
    if files is None:
        files = []
    rt = _runtime()
    led = _get_ledger()
    led.task = task
    if domain:
        led.domain = domain
    _match_mcp_lexical({"task": task})

    led.record_tool_call(
        "get_context",
        {
            "task": task,
            "domain": domain,
            "files": files,
            "keywords": keywords,
            "excluded_paths": excluded_paths,
            "tools": tools,
            "errors": errors,
            "max_blocks": max_blocks,
            "token_budget": token_budget,
            "dedup": dedup,
            "agent_id": agent_id,
            "recall": recall,
        },
    )

    bootstrap = _bootstrap_context_status(_atelier_root())
    # Keep workspace resolution consistent between this MCP adapter and the
    # core runtime path resolver so bootstrap status and injected bootstrap
    # context are derived from the same repository.
    workspace_root = str(_workspace_root().resolve())
    previous_workspace_root = os.environ.get("ATELIER_WORKSPACE_ROOT")
    os.environ["ATELIER_WORKSPACE_ROOT"] = workspace_root

    # Advance trajectory monitors and obtain FSM-derived retrieval hints.
    _monitor_composite, _fsm_skip_etraces = _advance_monitors(_get_product_session_id(), task, led.task or task)

    try:
        payload = rt.get_context(
            task=task,
            domain=domain,
            files=files,
            tools=tools,
            errors=errors,
            max_blocks=max_blocks,
            token_budget=token_budget,
            dedup=dedup,
            agent_id=agent_id,
            recall=recall,
            monitor_composite=_monitor_composite,
            fsm_skip_etraces=_fsm_skip_etraces,
        )
    finally:
        if previous_workspace_root is None:
            os.environ.pop("ATELIER_WORKSPACE_ROOT", None)
        else:
            os.environ["ATELIER_WORKSPACE_ROOT"] = previous_workspace_root
    result: dict[str, Any] = payload if isinstance(payload, dict) else {"context": payload}
    if bootstrap["status"] != "warm":
        _spawn_worker_if_idle(_atelier_root())
    result["bootstrap"] = bootstrap

    # Wire PrefixCachePlanner: compute static/dynamic split for this turn
    try:
        from atelier.core.capabilities.prefix_cache.planner import PrefixCachePlanner
        from atelier.core.capabilities.prompt_compilation.models import (
            BlockKind,
            PromptBlock,
            Stability,
        )

        context_text = result.get("context", "")
        bootstrap_text = (
            result.get("bootstrap", {}).get("context", "") if isinstance(result.get("bootstrap"), dict) else ""
        )
        _recall_count = len(result.get("recalled_passages", []))

        # Build synthetic PromptBlocks from the assembled context pieces
        blocks: list[PromptBlock] = []
        if context_text:
            blocks.append(
                PromptBlock(
                    id="context",
                    kind=BlockKind.PLAYBOOK,
                    stability=Stability.BRANCH,
                    content=context_text,
                )
            )
        if bootstrap_text:
            blocks.append(
                PromptBlock(
                    id="bootstrap",
                    kind=BlockKind.REPO_SUMMARY,
                    stability=Stability.SESSION,
                    content=bootstrap_text,
                )
            )
        if task:
            blocks.append(
                PromptBlock(
                    id="task",
                    kind=BlockKind.USER_TASK,
                    stability=Stability.TURN,
                    content=task,
                )
            )

        if blocks:
            # Compare with prior hash from last llm_call event in ledger
            prior_hash = ""
            call_events = [e for e in led.events if e.payload.get("kind") == "llm_call"]
            if call_events:
                prior_hash = call_events[-1].payload.get("stable_prefix_hash", "")

            planner = PrefixCachePlanner()
            plan = planner.plan_with_history(blocks, prior_hash or None)
            result["prefix_plan"] = plan.to_dict()
    except Exception:
        logging.exception("Recovered from broad exception handler")
        # Best-effort: never break tool_context due to prefix planning errors.
        _log.debug("prefix-cache planning failed", exc_info=True)

    return result


def _prefix_cache_diagnostics_from_ledger(led: Any) -> dict[str, Any]:
    """Extract prefix cache metrics from recorded llm_call events in the ledger."""
    call_events = [e for e in led.events if e.payload.get("kind") == "llm_call"]
    if not call_events:
        return {
            "turn_count": 0,
            "cache_hit_ratio": 0.0,
            "cache_read_tokens_saved": 0,
            "avg_prefix_tokens": 0,
            "avg_dynamic_tokens": 0,
            "current_prefix_hash": "",
            "prefix_invalidated_reason": "",
        }

    cache_read_totals = [int(e.payload.get("cache_read_tokens", 0)) for e in call_events]
    modeled_cache_read_totals = [int(e.payload.get("modeled_cache_read_tokens", 0)) for e in call_events]
    input_totals = [int(e.payload.get("input_tokens", 0)) for e in call_events]
    prefix_hashes = [e.payload.get("stable_prefix_hash", "") for e in call_events]

    # A turn is a cache "hit" when cache_read_tokens > 0
    eligible = call_events[1:]
    hits = sum(1 for e in eligible if int(e.payload.get("cache_read_tokens", 0)) > 0)
    hit_ratio = round(hits / len(eligible), 4) if eligible else 0.0
    cache_read_saved = sum(cache_read_totals)
    avg_input = int(sum(input_totals) / len(input_totals)) if input_totals else 0

    last = call_events[-1]
    return {
        "turn_count": len(call_events),
        "cache_hit_ratio": hit_ratio,
        "cache_read_tokens_saved": cache_read_saved,
        "modeled_cache_read_tokens_saved": sum(modeled_cache_read_totals),
        "avg_prefix_tokens": avg_input,
        "avg_dynamic_tokens": 0,
        "current_prefix_hash": prefix_hashes[-1] if prefix_hashes else "",
        "prefix_invalidated_reason": last.payload.get("prefix_invalidated_reason", ""),
    }


@mcp_tool(name="rescue")
def tool_rescue_failure(
    task: str,
    error: str,
    domain: str | None = None,
    files: list[str] | None = None,
    recent_actions: list[str] | None = None,
) -> dict[str, Any]:
    """Suggest a rescue procedure for a repeated failure (call after the same approach fails twice).

    Returns: {cluster_id, domain, rescue_type, procedure: [{step, rationale}], rationale, analysis?}.
    """
    if recent_actions is None:
        recent_actions = []
    if files is None:
        files = []
    rt = _runtime()
    led = _get_ledger()
    _match_mcp_lexical({"task": task, "error": error})
    led.record_tool_call(
        "rescue_failure",
        {
            "task": task,
            "error": error,
            "domain": domain,
            "files": files,
            "recent_actions": recent_actions,
        },
    )

    result = rt.rescue_failure(
        task=task,
        error=error,
        files=files,
        domain=domain,
        recent_actions=recent_actions,
    )
    payload = to_jsonable(result)
    with contextlib.suppress(Exception):
        from atelier.core.service.telemetry import emit_product
        from atelier.core.service.telemetry.schema import hash_identifier

        matched = list(payload.get("matched_blocks", []) or []) if isinstance(payload, dict) else []
        emit_product(
            "rescue_offered",
            cluster_id_hash=hash_identifier(str(matched[0] if matched else "unmatched_rescue")),
            rescue_type="playbook" if matched else "summary",
            session_id=_get_product_session_id(),
        )

    # Failure incident analysis from prior failed traces.
    with contextlib.suppress(Exception):
        analysis = rt.core_runtime.analyze_failure_for_error(
            task=task,
            error=error,
            domain=domain,
            lookback=200,
        )
        payload["analysis"] = analysis
        incident = analysis.get("incident") if isinstance(analysis, dict) else None
        if isinstance(incident, dict):
            root_cause = incident.get("root_cause_hypothesis", "")
            if isinstance(root_cause, str) and root_cause:
                led.record(
                    "note",
                    "failure_analysis",
                    {
                        "root_cause": root_cause,
                        "fingerprint": incident.get("fingerprint"),
                        "count": incident.get("count"),
                    },
                )

    return payload


_MAX_TRACE_FILES = int(os.environ.get("ATELIER_TRACE_MAX_FILES", "50"))
_MAX_TRACE_FILE_BYTES = int(os.environ.get("ATELIER_TRACE_MAX_FILE_BYTES", str(1024 * 1024)))


@mcp_tool(name="trace")
def tool_record_trace(
    agent: str,
    domain: str,
    task: str,
    status: Literal["success", "failed", "partial"],
    errors_seen: list[str] | None = None,
    diff_summary: str = "",
    output_summary: str = "",
    tools_called: list[Any] | None = None,
    validation_results: list[Any] | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    host: str | None = None,
    trace_confidence: str | None = None,
    capture_sources: list[str] | None = None,
    missing_surfaces: list[str] | None = None,
    event_type: str | None = None,
    event_payload: dict[str, Any] | None = None,
    capture_files: list[str] | None = None,
    learnings: list[Any] | None = None,
) -> dict[str, Any]:
    """Record an observable trace of an agent run (status, diffs, tools, validations, learnings) to the run ledger.

    Call once when a task is done so outcomes and lessons persist for later recall.

    Returns: {trace_id, event_recorded}.
    """
    from atelier.core.foundation.redaction import redact, redact_list

    if tools_called is None:
        tools_called = []
    if validation_results is None:
        validation_results = []
    if errors_seen is None:
        errors_seen = []
    if capture_sources is None:
        capture_sources = []
    if missing_surfaces is None:
        missing_surfaces = []
    if event_payload is None:
        event_payload = {}
    if capture_files is None:
        capture_files = []
    if learnings is None:
        learnings = []
    rt = _runtime()
    led = _get_ledger()
    rtc = _get_realtime_context()

    def _redact_json_strings(value: Any) -> Any:
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, list):
            return [_redact_json_strings(item) for item in value]
        if isinstance(value, dict):
            return {str(key): _redact_json_strings(item) for key, item in value.items()}
        return value

    def _coerce_validation_passed(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"pass", "passed", "success", "successful", "ok", "true"}:
                return True
            if lowered in {"fail", "failed", "failure", "error", "errored", "false"}:
                return False
        return False

    def _normalize_validation_results(items: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                name = item.get("name") or item.get("check") or "validation"
                detail = item.get("detail") or item.get("output") or ""
                passed = item.get("passed")
                if passed is None:
                    passed = item.get("status")
                normalized.append(
                    {
                        "name": redact(str(name)),
                        "passed": _coerce_validation_passed(passed),
                        "detail": redact(str(detail)),
                    }
                )
                continue
            text = redact(str(item))
            lowered = text.lower()
            passed = not any(token in lowered for token in ("fail", "error", "not run"))
            normalized.append({"name": text, "passed": passed, "detail": ""})
        return normalized

    def _normalize_tool_calls(items: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, str):
                normalized.append({"name": redact(item), "args_hash": "", "count": 1})
                continue
            if isinstance(item, dict):
                raw_count = item.get("count") or 1
                with contextlib.suppress(TypeError, ValueError):
                    raw_count = int(raw_count)
                if not isinstance(raw_count, int):
                    raw_count = 1
                tool_call: dict[str, Any] = {
                    "name": redact(str(item.get("name") or item.get("tool") or "unknown")),
                    "args_hash": redact(str(item.get("args_hash") or "")),
                    "count": raw_count,
                }
                if "args" in item:
                    tool_call["args"] = _redact_json_strings(item["args"])
                if isinstance(item.get("result_summary"), str):
                    tool_call["result_summary"] = redact(item["result_summary"])
                normalized.append(tool_call)
                continue
            normalized.append({"name": redact(str(item)), "args_hash": "", "count": 1})
        return normalized

    def _normalize_learnings(items: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, str):
                text = redact(item.strip())
                if text:
                    normalized.append({"kind": "note", "text": text})
                continue
            if not isinstance(item, dict):
                continue
            raw_text = (
                item.get("text")
                or item.get("learning")
                or item.get("lesson")
                or item.get("body")
                or item.get("summary")
                or ""
            )
            text = redact(str(raw_text).strip())
            if not text:
                continue
            entry: dict[str, Any] = {"text": text}
            if item.get("kind") is not None:
                entry["kind"] = redact(str(item["kind"]))
            if item.get("evidence") is not None:
                entry["evidence"] = redact(str(item["evidence"]))
            promote_to = item.get("promote_to")
            if promote_to is None:
                promote_to = item.get("target") or item.get("promotion_target")
            if promote_to is not None:
                entry["promote_to"] = redact(str(promote_to))
            normalized.append(entry)
        return normalized

    def _normalize_trace_confidence(value: Any) -> str | None:
        if value is None:
            return None
        normalized = redact(str(value)).strip().lower()
        if not normalized or normalized in {"none", "null", "unknown"}:
            return None
        if normalized in {"full_live", "mcp_live", "wrapper_live", "imported", "manual"}:
            return normalized
        if normalized in {"high", "medium", "low"}:
            # Legacy callers treated this field like a confidence strength rather
            # than a capture provenance. Preserve the trace conservatively.
            return "manual"
        return "manual"

    def _normalize_workflow_trace_payload(raw_event_type: str, raw_payload: dict[str, Any]) -> dict[str, Any] | None:
        normalized_type = redact(raw_event_type).strip().lower()
        payload = _redact_json_strings(raw_payload)
        if not isinstance(payload, dict):
            return None
        if normalized_type == "workflow_state":
            workflow_step = str(payload.get("workflow_step") or payload.get("current_step") or "").strip()
            session_phase = str(payload.get("session_phase") or "").strip()
            result: dict[str, Any] = {}
            if workflow_step:
                result["workflow_step"] = workflow_step
            if session_phase:
                result["session_phase"] = session_phase
            return result or None
        if normalized_type == "plan_review":
            review_decision = str(payload.get("review_decision") or payload.get("decision") or "").strip()
            plan_id = str(payload.get("plan_id") or "").strip()
            workflow_step = str(payload.get("workflow_step") or "").strip()
            result = {}
            if review_decision:
                result["review_decision"] = review_decision
            if plan_id:
                result["plan_id"] = plan_id
            if workflow_step:
                result["workflow_step"] = workflow_step
            return result or None
        if normalized_type == "task_progress":
            task_id = str(payload.get("task_id") or "").strip()
            workflow_step = str(payload.get("workflow_step") or "").strip()
            result = {}
            if task_id:
                result["task_id"] = task_id
            if workflow_step:
                result["workflow_step"] = workflow_step
            for key in ("completed_tasks", "remaining_tasks"):
                value = payload.get(key)
                if isinstance(value, bool):
                    continue
                try:
                    result[key] = max(0, int(value or 0))
                except (TypeError, ValueError):
                    continue
            return result or None
        return None

    # Derive host label from agent string and environment
    def _derive_host(a: str) -> str:
        al = a.lower()
        if "antigravity" in al or "agy" in al or os.environ.get("ANTIGRAVITY_CLI") or os.environ.get("AGY_CLI"):
            return "antigravity"
        if "cursor" in al or os.environ.get("CURSOR_SESSION_ID") or os.environ.get("CURSOR_TRACE_ID"):
            return "cursor"
        if (
            "hermes" in al
            or os.environ.get("HERMES_HOME")
            or os.environ.get("HERMES_SESSION_ID")
            or os.environ.get("HERMES_CLI")
        ):
            return "hermes"
        if "copilot" in al or os.environ.get("COPILOT_CLI"):
            return "copilot"
        if "codex" in al or os.environ.get("CODEX_CLI"):
            return "codex"
        if (
            "opencode" in al
            or os.environ.get("OPENCODE_CLI")
            or os.environ.get("OPENCODE_SESSION_ID")
            or os.environ.get("ATELIER_AGENT", "") == "opencode"
        ):
            return "opencode"
        if "claude" in al or os.environ.get("CLAUDE_CODE"):
            return "claude"

        # Default to the agent name if no known host environment is detected
        return "atelier" if al.startswith("atelier:") else al

    normalized_capture_sources = [redact(str(source)) for source in capture_sources]
    normalized_trace_confidence = _normalize_trace_confidence(trace_confidence)
    normalized_missing_surfaces = redact_list([str(value) for value in missing_surfaces])
    if normalized_trace_confidence == "full_live" and not any(
        source in {"hooks", "live_hooks", "plugin_hooks"} for source in normalized_capture_sources
    ):
        normalized_trace_confidence = "mcp_live"
        if "hooks" not in normalized_missing_surfaces:
            normalized_missing_surfaces.append("hooks")

    payload: dict[str, Any] = {
        "agent": agent,
        "domain": domain,
        "task": redact(task),
        "status": status,
        "errors_seen": redact_list([str(v) for v in errors_seen]),
        "diff_summary": redact(diff_summary),
        "output_summary": redact(output_summary),
        "session_id": session_id or run_id or led.session_id,
        "host": redact(host) if host else _derive_host(agent),
        "trace_confidence": normalized_trace_confidence,
        "capture_sources": normalized_capture_sources,
        "missing_surfaces": normalized_missing_surfaces,
    }
    payload["tools_called"] = _normalize_tool_calls(tools_called)
    payload["validation_results"] = _normalize_validation_results(validation_results)
    payload["learnings"] = _normalize_learnings(learnings)

    raw_artifacts: list[str] = []
    if capture_files:
        source_session_id = (
            _get_product_session_id()
            or os.environ.get("CODEX_SESSION_ID")
            or os.environ.get("OPENCODE_SESSION_ID")
            or "unknown"
        )
        for fpath in capture_files[:_MAX_TRACE_FILES]:
            try:
                p = Path(fpath)
                if not p.is_file():
                    continue
                if p.stat().st_size > _MAX_TRACE_FILE_BYTES:
                    logging.info(
                        "trace capture: skipping %s (%d bytes > cap %d; raise ATELIER_TRACE_MAX_FILE_BYTES)",
                        fpath,
                        p.stat().st_size,
                        _MAX_TRACE_FILE_BYTES,
                    )
                    continue
                content = p.read_text(encoding="utf-8", errors="replace")
                # We redact secrets from files before capture for safety
                redacted_content = redact(content)
                digest = sha256(redacted_content.encode("utf-8", errors="replace")).hexdigest()

                # Use a stable but unique ID for the file artifact
                artifact_id = f"file-{sha256(fpath.encode()).hexdigest()[:12]}-{digest[:12]}"

                artifact = RawArtifact(
                    id=artifact_id,
                    source="mcp",
                    source_session_id=source_session_id,
                    kind="source.code",
                    relative_path=f"{artifact_id}.txt",
                    content_path=f"raw/mcp/{source_session_id}/{artifact_id}.txt",
                    sha256_original=sha256(content.encode()).hexdigest(),
                    sha256_redacted=digest,
                    byte_count_original=len(content.encode("utf-8")),
                    byte_count_redacted=len(redacted_content.encode("utf-8")),
                    redacted=True,
                    source_path=str(p.absolute()),
                    source_file_mtime=datetime.fromtimestamp(p.stat().st_mtime, tz=UTC),
                )
                rt.store.record_raw_artifact(artifact, redacted_content)
                raw_artifacts.append(artifact_id)
            except Exception as e:
                logging.exception("Recovered from broad exception handler")
                logger.warning("Failed to capture context file %s: %s", fpath, e)

    if raw_artifacts:
        payload["raw_artifact_ids"] = raw_artifacts

    if event_type:
        normalized_event_payload = _normalize_workflow_trace_payload(event_type, event_payload)
        if normalized_event_payload is not None:
            led.record_workflow_event(event_type, normalized_event_payload)
        else:
            led.record("note", f"event:{redact(event_type)}", _redact_json_strings(event_payload))

    if "id" not in payload:
        payload["id"] = Trace.make_id(task, agent)

    trace = Trace.model_validate(payload)
    rt.store.record_trace(trace)
    from atelier.core.capabilities.lesson_promotion import ingest_failed_trace

    ingest_failed_trace(rt.store, trace)

    # Write learnings to archival memory (not Playbooks - those are curated).
    # Each learning is a short sentence the agent synthesises; stored deduped so
    # repeated identical insights across sessions don't accumulate noise.
    if trace.learnings:
        mem = _memory_store()
        for learning in trace.learnings:
            text = redact(learning.text.strip())
            if not text:
                continue
            dedup_hash = sha256(f"{agent}:{text}".encode()).hexdigest()[:32]
            passage = ArchivalPassage(
                agent_id=agent,
                text=text,
                source="trace",
                source_ref=trace.id,
                tags=["learning", domain, learning.kind],
                dedup_hash=dedup_hash,
            )
            with contextlib.suppress(Exception):
                mem.insert_passage(passage)

    led.close(status=status)
    led.persist()

    rtc.persist()

    # Emit to Langfuse if configured (fail-open)
    from atelier.gateway.integrations.langfuse import emit_trace as _lf_emit

    _lf_emit(payload)

    # Kick off a background consolidation tick so knowledge blocks are extracted
    # from this trace without waiting for the daemon's next cycle. Throttled
    # (>=30s) so a burst of trace calls can't spawn a thread storm.
    _spawn_worker_if_idle(_atelier_root())

    # Stable compact receipt.
    return {
        "trace_id": trace.id,
        "event_recorded": bool(event_type),
    }


@mcp_tool(name="verify")
def tool_run_rubric_gate(rubric_id: str, checks: dict[str, Any]) -> Any:
    """Evaluate agent results against a domain rubric. Returns pass|warn|fail with per-check detail."""
    rt = _runtime()
    led = _get_ledger()
    led.record_tool_call("run_rubric_gate", {"rubric_id": rubric_id, "checks": checks})

    rubric = rt.store.get_rubric(rubric_id)
    if rubric is None:
        raise ValueError(f"rubric not found: {rubric_id}")

    if rubric_id not in led.active_rubrics:
        led.active_rubrics.append(rubric_id)

    result = run_rubric(rubric, checks)
    led.record("rubric_run", f"Rubric {rubric_id} status: {result.status}", to_jsonable(result))
    return to_jsonable(result)


def _compress_context(session_id: str | None = None) -> Any:
    """Compress the current ledger state into a compact prompt block for context continuation.

    Call when context is heavy; the block preserves decisions and state while dropping stale history.

    Returns: {prompt_block, tokens_before, tokens_after_estimate, tokens_freed, cost_saved_usd}.
    """
    from atelier.infra.runtime.context_compressor import ContextCompressor

    led = _get_ledger()
    if session_id:
        led.session_id = session_id
    state = ContextCompressor().compress(led, preserve_last_n_turns=10, workspace_root=_workspace_root())
    compaction_savings = _session_compaction_savings_payload(
        led,
        state,
        tokens_before=int(led.token_count or 0),
        trigger="compact_session",
        reason="session compaction executed",
    )
    if int(compaction_savings["tokens_saved"]) > 0:
        _append_live_savings_event(compaction_savings)

    with contextlib.suppress(Exception):
        from atelier.infra.runtime import outcome_capture

        outcome_capture.schedule_compact(
            session_id=led.session_id,
            trigger="compact_session",
            tokens_before=int(compaction_savings["tokens_before"]),
            tokens_after=int(compaction_savings["tokens_after_estimate"]),
            must_keep_keywords=list(led.active_playbooks),
            errors_before=len(led.errors_seen) + len(led.repeated_failures),
            writer=_make_outcome_writer(led),
        )

    return {
        "prompt_block": state.to_prompt_block(),
        "tokens_before": int(compaction_savings["tokens_before"]),
        "tokens_after_estimate": int(compaction_savings["tokens_after_estimate"]),
        "tokens_freed": int(compaction_savings["tokens_freed"]),
        "cost_saved_usd": float(compaction_savings["cost_saved_usd"]),
    }


def _memory_upsert_block(
    agent_id: str,
    label: str,
    value: str,
    limit_chars: int = 8000,
    description: str = "",
    read_only: bool = False,
    pinned: bool = False,
    metadata: dict[str, Any] | None = None,
    expected_version: int | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    """Create or update an editable memory block."""
    clean_value = _redact_memory_input(value, "value")
    clean_description = _redact_memory_input(description, "description")
    store = _memory_store()
    existing = store.get_block(agent_id, label)
    version = expected_version if expected_version is not None else (existing.version if existing else 1)
    seed = existing or MemoryBlock(agent_id=agent_id, label=label, value=clean_value)
    block = MemoryBlock(
        id=seed.id,
        agent_id=agent_id,
        label=label,
        value=clean_value,
        limit_chars=limit_chars,
        description=clean_description,
        read_only=read_only,
        metadata=metadata or {},
        pinned=pinned,
        version=version,
        current_history_id=existing.current_history_id if existing else None,
        created_at=seed.created_at,
    )
    from atelier.core.capabilities.memory_arbitration import arbitrate

    decision = arbitrate(block, store, make_embedder())
    target = None
    if decision.target_block_id:
        for item in store.list_blocks(agent_id, include_tombstoned=True, limit=500):
            if item.id == decision.target_block_id:
                target = item
                break

    if decision.op == "NOOP" and target is not None:
        stored = target
    elif decision.op == "UPDATE" and target is not None:
        stored = store.upsert_block(
            target.model_copy(update={"value": decision.merged_value or clean_value}),
            actor=actor or f"agent:{agent_id}",
            reason=decision.reason,
        )
    elif decision.op == "DELETE" and target is not None:
        store.tombstone_block(target.id, deprecated_by_block_id=block.id, reason=decision.reason)
        stored = store.upsert_block(block, actor=actor or f"agent:{agent_id}", reason=decision.reason)
    else:
        stored = store.upsert_block(block, actor=actor or f"agent:{agent_id}")
    return {
        "id": stored.id,
        "version": stored.version,
        "arbitration": {"op": decision.op, "reason": decision.reason},
    }


def _memory_get_block(agent_id: str | None, label: str) -> dict[str, Any] | None:
    """Retrieve a MemoryBlock by label."""
    block = _memory_store().get_block(agent_id, label)
    return block.model_dump(mode="json") if block is not None else None


def _memory_archive(
    agent_id: str | None,
    text: str,
    source: str,
    source_ref: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Archive long-term memory text for later recall."""
    passage = _archival_recall().archive(
        agent_id=agent_id,
        text=text,
        source=source,  # type: ignore[arg-type]
        source_ref=source_ref,
        tags=tags or [],
    )
    return {"id": passage.id, "dedup_hit": passage.dedup_hit}


def _memory_recall(
    agent_id: str | None,
    query: str,
    top_k: int = 5,
    tags: list[str] | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Recall relevant archival memory passages.

    The recall surface spans two stores: durable memory (``memory.db`` via
    ``MemoryService``) and past-session transcripts (``recall.db``, populated by
    the SessionStart indexer in ``session_recall``). They are separate SQLite
    files with independently scaled scores, so memory passages are listed first,
    then past-session hits are appended.
    """
    result = (
        _memory_service()
        .recall(
            agent_id=agent_id,
            query=query,
            top_k=top_k,
            tags=tags or None,
            since=since,
        )
        .model_dump(mode="json")
    )
    mem_passages = result.get("passages")
    if not isinstance(mem_passages, list):
        mem_passages = []
    session = _session_recall_passages(query, top_k)
    if session:
        # Honor the top_k contract (the field promises "max results") while keeping
        # past-session recall visible: reserve up to a third of the budget for
        # session hits and fill the rest from durable memory.
        reserve = min(len(session), max(1, top_k // 3))
        passages = mem_passages[: max(0, top_k - reserve)] + session[:reserve]
    else:
        passages = mem_passages[:top_k]
    result["passages"] = passages
    if not passages:
        # Helpful state hint instead of a bare empty result, so the model knows
        # memory is working and how to seed it.
        result["hint"] = (
            "No matching memories yet — memory accrues as you work. Store durable facts with "
            "memory(op=store_fact); past-session recall improves as sessions are indexed."
        )
    return result


def _session_recall_passages(query: str, top_k: int) -> list[dict[str, Any]]:
    """Past-session recall hits from ``recall.db``, shaped like
    ``MemoryRecallPassage`` so ``memory(op=recall)`` renders them next to
    ``memory.db`` passages. Best-effort: ``session_recall.recall`` returns ``[]``
    when the index is missing or the embedder is unavailable."""
    from atelier.core.capabilities import session_recall

    return [
        {
            "id": str(hit.get("session") or ""),
            "text": str(hit.get("text") or ""),
            "source_ref": str(hit.get("session") or ""),
            "tags": list(hit.get("tags") or []),
        }
        for hit in session_recall.recall(_atelier_root(), query, top_k=top_k)
    ]


def _memory_service() -> MemoryService:
    return MemoryService(store=_memory_store(), embedder=make_embedder(), redactor=redact)


def _memory_store_fact(
    *,
    agent_id: str | None,
    subject: str,
    fact: str,
    citations: str,
    reason: str,
    scope: str,
) -> dict[str, Any]:
    """Store a durable fact with Copilot-memory-like fields in Atelier memory."""
    return (
        _memory_service()
        .store_fact(
            agent_id=agent_id,
            subject=_redact_memory_input(subject, "subject"),
            fact=_redact_memory_input(fact, "fact"),
            citations=_redact_memory_input(citations, "citations"),
            reason=_redact_memory_input(reason, "reason"),
            scope=scope,
        )
        .model_dump(mode="json")
    )


def _memory_vote_fact(
    *,
    agent_id: str | None,
    fact: str,
    direction: str,
    reason: str,
    scope: str | None,
) -> dict[str, Any]:
    """Vote on an existing stored fact by exact fact text."""
    return (
        _memory_service()
        .vote_fact(
            agent_id=agent_id,
            fact=_redact_memory_input(fact, "fact"),
            direction=direction,
            reason=_redact_memory_input(reason, "reason"),
            scope=scope,
        )
        .model_dump(mode="json")
    )


@mcp_tool(
    name="memory",
    description=("Memory op-dispatch for fact storage/voting and recall."),
)
def tool_memory(
    op: Annotated[
        Literal[
            "recall",
            "recall_symbol",
            "store_fact",
            "vote_fact",
        ],
        Field(
            description=(
                "Operation to execute. recall requires query; "
                "recall_symbol requires query (returns a symbol-linked recall bundle); "
                "store_fact requires subject+fact+citations+reason+scope; "
                "vote_fact requires fact+direction+reason."
            )
        ),
    ],
    agent_id: Annotated[
        str | None,
        Field(
            description="Memory namespace for scoped blocks and archival passages. Defaults to shared namespace when not specified."
        ),
    ] = None,
    query: Annotated[str | None, Field(description="Search query used by recall.")] = None,
    top_k: Annotated[int, Field(description="Max results to return for recall.")] = 5,
    subject: Annotated[
        str | None,
        Field(description="Fact subject for store_fact (for example: testing, workflow preference)."),
    ] = None,
    fact: Annotated[
        str | None,
        Field(description="Exact fact text for store_fact and vote_fact."),
    ] = None,
    citations: Annotated[
        str | None,
        Field(description="Source citations for store_fact."),
    ] = None,
    reason: Annotated[
        str | None,
        Field(description="Detailed rationale for store_fact and vote_fact."),
    ] = None,
    scope: Annotated[
        Literal["repository", "user"] | None,
        Field(description="Fact scope for store_fact/vote_fact."),
    ] = None,
    direction: Annotated[
        Literal["upvote", "downvote"] | None,
        Field(description="Vote direction for vote_fact."),
    ] = None,
) -> dict[str, Any] | None:
    """Memory op-dispatch: recall, recall_symbol, store_fact, or vote_fact."""

    def require(name: str, current: str | None) -> str:
        if not current:
            raise ValueError(f"{name} is required for memory op={op}")
        return current

    if op == "recall":
        return _memory_recall(
            agent_id=agent_id,
            query=require("query", query),
            top_k=top_k,
        )
    if op == "store_fact":
        return _memory_store_fact(
            agent_id=agent_id,
            subject=require("subject", subject),
            fact=require("fact", fact),
            citations=citations or "",
            reason=reason or "",
            scope=require("scope", scope),
        )
    if op == "vote_fact":
        return _memory_vote_fact(
            agent_id=agent_id,
            fact=require("fact", fact),
            direction=require("direction", direction),
            reason=require("reason", reason),
            scope=scope,
        )
    if op == "recall_symbol":
        return cast(
            dict[str, Any],
            _symbol_recall().recall_symbol(
                query=require("query", query),
                agent_id=agent_id,
                top_k=top_k,
            ),
        )
    raise ValueError(f"unsupported memory op: {op}")


def _render_read_md(result: dict[str, Any]) -> str | None:
    mode = str(result.get("mode") or "")
    projection = result.get("projection")
    notice = ""
    if isinstance(projection, dict):
        raw_notice = str(projection.get("notice") or "").strip()
        if raw_notice:
            notice = raw_notice
    if mode == "directory":
        entries = result.get("entries")
        if isinstance(entries, list):
            return "\n".join(entries)
        return None
    if mode == "summary":
        summary = str(result.get("summary") or "").strip()
        if not summary:
            return None
        return f"{notice}\n\n{summary}" if notice else summary
    if mode in {"range", "full"}:
        content = str(result.get("content") or "")
        if not content:
            return None
        return f"{notice}\n\n{content}" if notice else content
    if mode == "outline":
        path = str(result.get("path") or "?")
        language = str(result.get("language") or "")
        outline = result.get("outline")
        if isinstance(outline, dict):
            rendered = _render_read_outline_md(path, outline, language)
            return f"{notice}\n\n{rendered}" if notice else rendered
        return None
    return None


def _render_read_outline_md(path: str, outline: dict[str, Any], language: str) -> str:
    # Treesitter/generic: has pre-formatted `text` field
    text = str(outline.get("text") or "").strip()
    if text:
        return text
    # AST outline: has `symbols`, `imports`, `hint` fields
    lines: list[str] = []
    hint = str(outline.get("hint") or "").strip()
    if hint:
        lines.append(f"hint: {hint}")
    imports_list = outline.get("imports")
    if isinstance(imports_list, list) and imports_list:
        # Collapse to distinct top-level roots instead of one line per import.
        # On import-heavy files the full list is dozens of lines the model
        # rarely needs; the root set conveys the dependency surface far cheaper.
        roots = sorted({str(imp).split()[0].split(".")[0] for imp in imports_list if str(imp).strip()})
        lines.append(f"imports ({len(imports_list)}): {', '.join(roots)}")
    symbols_list = outline.get("symbols")
    if isinstance(symbols_list, list) and symbols_list:
        lines.append("symbols:")
        for sym in symbols_list:
            if not isinstance(sym, dict):
                continue
            name = str(sym.get("name") or "?")
            kind = str(sym.get("kind") or "?")
            start = int(sym.get("start_line") or 0)
            end = int(sym.get("end_line") or 0)
            loc = f"{start}-{end}" if end > start else str(start)
            lines.append(f"- {loc}: {name} [{kind}]")
    return "\n".join(lines) if lines else "(no outline)"


def _render_grep_md(result: dict[str, Any]) -> str | None:
    mode = str(result.get("mode") or result.get("output_mode") or "")
    if mode == "ranked_file_map":
        matches = result.get("matches")
        if not isinstance(matches, list) or not matches:
            return "no matches"
        lines: list[str] = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            file_path = str(match.get("file") or "?")
            lines.append(file_path)
            ranges = match.get("ranges")
            if isinstance(ranges, list):
                for r in ranges:
                    lines.append(f"- lines {r}")
        return "\n".join(lines) if lines else "no matches"
    # Non-ranked modes: content is pre-formatted text blocks
    content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    return None


def _render_search_md(result: dict[str, Any]) -> str | None:
    mode = str(result.get("mode") or "chunks")
    if mode == "map":
        outline = str(result.get("outline") or "").strip()
        ranked_raw = result.get("ranked_files")
        ranked = ranked_raw if isinstance(ranked_raw, list) else []
        if not outline and not ranked:
            return None
        # The repo-map `outline` is already plain text; emitting it directly
        # (instead of json.dumps of the whole payload) drops the JSON wrapper and
        # the \n-escaping of every outline line.
        map_lines = ["### repo_map"]
        if outline:
            map_lines.append(outline)
        if ranked:
            map_lines.append("files:")
            for entry in ranked:
                if isinstance(entry, dict):
                    map_lines.append(f"- {entry.get('path') or entry.get('file') or '?'}")
                else:
                    map_lines.append(f"- {entry}")
        return "\n".join(map_lines)
    matches = result.get("matches")
    if not isinstance(matches, list) or not matches:
        return "### search\n- no matches"
    lines: list[str] = ["### search"]
    for match in matches:
        if not isinstance(match, dict):
            continue
        path = str(match.get("path") or "?")
        lines.append(path)
        content = str(match.get("content") or "").strip()
        if content:
            lines.append(content)
        else:
            snippets = match.get("snippets")
            if isinstance(snippets, list):
                for snip in snippets[:3]:
                    if isinstance(snip, dict):
                        snip_content = str(snip.get("content") or "").strip()
                        if snip_content:
                            lines.append(snip_content)
    return "\n".join(lines)


def _render_memory_md(result: dict[str, Any]) -> str | None:
    """Compact recall rendering: one header line per passage (source/tags) plus
    its text body, instead of a JSON list that repeats the field keys on every
    entry and escapes every newline in the passage text. Only recall (which has
    a ``passages`` list) is rendered; store_fact/vote_fact fall back to JSON.
    """
    passages = result.get("passages")
    if not isinstance(passages, list):
        return None
    hint = str(result.get("hint") or "").strip()
    if not passages:
        return "### memory\n- no passages" + (f"\n{hint}" if hint else "")
    lines = [f"### memory ({len(passages)} passage(s))"]
    for passage in passages:
        if not isinstance(passage, dict):
            continue
        ref = (str(passage.get("source_ref") or passage.get("id") or "?").strip()) or "?"
        tags = passage.get("tags")
        tag_str = f" [{', '.join(str(tag) for tag in tags)}]" if isinstance(tags, list) and tags else ""
        lines.append(f"- {ref}{tag_str}")
        text = str(passage.get("text") or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _render_verify_md(result: dict[str, Any]) -> str | None:
    """Compact rubric-gate rendering: one line per check instead of a list of dicts
    that repeats name/status/detail keys (detail is empty on every passing check).
    """
    outcomes = result.get("outcomes")
    if not isinstance(outcomes, list):
        return None
    lines = [f"### verify rubric={result.get('rubric_id') or '?'} status={result.get('status') or '?'}"]
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        status = str(outcome.get("status") or "?")
        check_name = str(outcome.get("name") or "?")
        detail = str(outcome.get("detail") or "").strip()
        lines.append(f"- {status} {check_name}" + (f": {detail}" if detail else ""))
    escalations = result.get("escalations")
    if isinstance(escalations, list):
        for escalation in escalations:
            lines.append(f"- escalation: {escalation}")
    return "\n".join(lines)


def _render_sql_md(result: dict[str, Any]) -> str | None:
    """Compact rendering for sql introspection (schema/table/search/relationships/lint).

    Collapses per-column dicts ({cid,name,type,notnull,pk}) -- which repeat their keys
    on every column -- into one line per column. The `query` action is already columnar
    (positional rows + a single header), so it is left as JSON (returns None).
    """

    def _cols(columns: Any) -> list[str]:
        out: list[str] = []
        if isinstance(columns, list):
            for col in columns:
                if not isinstance(col, dict):
                    continue
                parts = [str(col.get("name") or "?"), str(col.get("type") or "")]
                if col.get("pk"):
                    parts.append("pk")
                if col.get("notnull"):
                    parts.append("notnull")
                out.append("  - " + " ".join(p for p in parts if p))
        return out

    def _fks(fks: Any) -> list[str]:
        out: list[str] = []
        if isinstance(fks, list):
            for fk in fks:
                if isinstance(fk, dict):
                    out.append(
                        f"  fk: {fk.get('from_column', '?')} -> {fk.get('table', '?')}.{fk.get('to_column', '?')}"
                    )
        return out

    if "results" in result:  # query: already columnar, leave as JSON
        return None
    if isinstance(result.get("schema"), dict):
        schema = result["schema"]
        lines = [f"### sql schema ({result.get('table_count', len(schema))} tables)"]
        for table, info in schema.items():
            lines.append(f"- {table}")
            if isinstance(info, dict):
                lines.extend(_cols(info.get("columns")))
                lines.extend(_fks(info.get("foreign_keys")))
        return "\n".join(lines)
    if isinstance(result.get("matches"), list):
        lines = ["### sql search"]
        for match in result["matches"]:
            if not isinstance(match, dict):
                continue
            lines.append(f"- {match.get('table', '?')}")
            lines.extend(_cols(match.get("columns")))
            lines.extend(_fks(match.get("foreign_keys")))
        return "\n".join(lines)
    if isinstance(result.get("relationships"), list):
        lines = ["### sql relationships"]
        for rel in result["relationships"]:
            if isinstance(rel, dict):
                lines.append(f"- {rel.get('from', '?')} -> {rel.get('to', '?')}")
        return "\n".join(lines)
    if isinstance(result.get("columns"), list) and "table" in result:
        lines = [f"### sql table {result.get('table', '?')}"]
        lines.extend(_cols(result.get("columns")))
        lines.extend(_fks(result.get("foreign_keys")))
        return "\n".join(lines)
    if "ok" in result:  # lint
        return f"### sql lint: {'ok' if result.get('ok') else (result.get('message') or 'invalid')}"
    if isinstance(result.get("tables"), list):
        tables = result["tables"]
        return "\n".join([f"### sql tables ({result.get('table_count', len(tables))})", *(f"- {t}" for t in tables)])
    return None


def render_tool_result_text(name: str, result: Any) -> str | None:
    """Best-effort compact text rendering of a tool result for model context.

    Shared by the MCP dispatch path and the in-process CLI runtime so both
    hosts send the model identical, minimal text instead of raw dict dumps.
    Returns ``None`` when no renderer applies or it produced nothing — callers
    fall back to the raw string / compact JSON form.
    """
    if name in {"symbols"} | _CODE_INTEL_TOOLS:
        return getattr(_tool_call_rendered_text, "value", None) or None
    if not isinstance(result, dict):
        return None
    payload = result
    text: str | None = None
    if name == "read":
        with contextlib.suppress(Exception):
            files = payload.get("files")
            if isinstance(files, list):
                parts: list[str] = []
                cwd = str(Path.cwd())
                for entry in files:
                    if not isinstance(entry, dict):
                        continue
                    entry_path = str(entry.get("path") or "?")
                    if entry_path.startswith(cwd + os.sep):
                        entry_path = entry_path[len(cwd) + 1 :]
                    entry_text = _render_read_md(entry)
                    if entry_text is None:
                        entry_text = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
                    parts.append(f"## {entry_path}\n{entry_text}")
                text = "\n\n".join(parts) if parts else None
            else:
                text = _render_read_md(payload)
    elif name == "grep":
        with contextlib.suppress(Exception):
            text = _render_grep_md(payload)
    elif name == "search":
        with contextlib.suppress(Exception):
            text = _render_search_md(payload)
    elif name == "shell":
        with contextlib.suppress(Exception):
            text = _render_shell_text(payload)
    elif name == "web_fetch":
        with contextlib.suppress(Exception):
            text = str(payload.get("content") or "")
    elif name == "verify":
        with contextlib.suppress(Exception):
            text = _render_verify_md(payload)
    elif name == "sql":
        with contextlib.suppress(Exception):
            text = _render_sql_md(payload)
    elif name == "memory":
        with contextlib.suppress(Exception):
            text = _render_memory_md(payload)
    return text or None


def _read_dedup_resource(args: dict[str, Any]) -> str:
    """Stable resource key for delta re-reads: single-path reads only.

    Batch reads (``files=[...]``) render multiple bodies into one text and are
    not delta-tracked. The range/expand projection is part of the key so
    different views of the same file never cross-diff.
    """
    path = str(args.get("path") or "")
    if not path or args.get("files") is not None:
        return ""
    range_spec = str(args.get("range") or "")
    max_lines = args.get("max_lines")
    max_lines_spec = "" if max_lines is None else str(max_lines)
    projection_spec = str(args.get("projection_kind") or "")
    return f"read:{path}:{range_spec}:{max_lines_spec}:{projection_spec}:{int(bool(args.get('expand')))}"


_READ_SUGGEST_PRUNE_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".next",
        "target",
    }
)


def _suggest_paths_for_missing(workspace_root: Path, missing: str, *, limit: int = 3) -> list[str]:
    """Workspace-relative paths whose basename matches the missing file's."""
    name = Path(missing).name
    if not name:
        return []
    lowered = name.lower()
    hits: list[str] = []
    scanned = 0
    try:
        for dirpath, dirnames, filenames in os.walk(workspace_root):
            dirnames[:] = [d for d in dirnames if d not in _READ_SUGGEST_PRUNE_DIRS]
            scanned += len(filenames)
            for fname in filenames:
                if fname.lower() == lowered:
                    with contextlib.suppress(ValueError):
                        hits.append(str((Path(dirpath) / fname).relative_to(workspace_root)))
                    if len(hits) >= limit:
                        return hits
            if scanned > 50_000:
                break
    except OSError:
        return hits
    return hits


# A trailing "#start-end" / "#line" suffix on a read path is parsed as a line
# range (parity with the edit tool's `file_path#start-end` form and with the
# range specs models naturally emit, e.g. "store.py#60-100"). Optional "L"
# prefixes mirror the read tool's own range syntax. A non-numeric "#..." tail is
# left intact so genuine '#' filenames still resolve.
_READ_RANGE_SUFFIX = re.compile(r"#(L?\d+(?:[-,:]L?\d+)?)$", re.IGNORECASE)


def _split_read_range_suffix(raw_path: str) -> tuple[str, str | None]:
    """Split a trailing line-range suffix off a read path.

    Returns (path, range_spec) where range_spec is in the read tool's range
    syntax (e.g. "60-100"), or (raw_path, None) when there is no numeric suffix.
    """
    match = _READ_RANGE_SUFFIX.search(raw_path)
    if match is None:
        return raw_path, None
    return raw_path[: match.start()], match.group(1)


def _smart_read_single(
    path: str,
    range: str | None = None,
    expand: bool = False,
    max_lines: int | None = None,
    include_meta: bool = False,
    projection_kind: str | None = None,
) -> dict[str, Any]:
    """Execute a single-file smart-read.  Called by both the decorated tool and the batch loop."""
    target_path = path
    if not target_path:
        raise ValueError("provide path")
    # Support a trailing "#start-end" / "#line" line-range suffix on the path
    # itself (e.g. "store.py#60-100"); an explicit range= argument wins.
    target_path, suffix_range = _split_read_range_suffix(target_path)
    if range is None and suffix_range is not None:
        range = suffix_range
    # Reads may target any path the host process can access — a coding agent
    # legitimately reads configs / sibling repos outside the project, and the
    # host's own permission layer gates the tool call. Writes/edits, by contrast,
    # are confined to the workspace (see tool_smart_edit). Relative paths still
    # resolve against the workspace root.
    resolved = _workspace_path(target_path)
    if max_lines is not None and range is None and not expand:
        payload = cast(dict[str, Any], _core_runtime().smart_read(str(resolved), max_lines=max_lines))
        payload.setdefault("mode", "summary")
        payload["projection"] = SourceProjection.summary().to_dict()
        if include_meta:
            return payload
        payload.pop("cache_hit", None)
        payload.pop("tokens_saved", None)
        return payload

    target = resolved

    # Detect directory input early — return a helpful listing instead of a cryptic error.
    if target.is_dir():
        try:
            entries = sorted(
                os.listdir(target),
                key=lambda x: (not (target / x).is_dir(), x.lower()),
            )
        except OSError:
            entries = []
        return {
            "mode": "directory",
            "path": str(target),
            "entries": [(e + "/" if (target / e).is_dir() else e) for e in entries],
            "message": (
                "This is a directory, not a file. "
                "Use `symbols` to find indexed code by name, "
                "or `grep` with `file_glob_patterns` to list/search files."
            ),
        }

    # Source-side guard: an exact full read (expand) of a very large file would
    # load the whole file into memory and serialize into one oversized JSON-RPC
    # frame, which disconnects the host. Read only a bounded prefix from disk so
    # gigabytes are never materialized. Range reads are inherently bounded, and
    # non-expand reads of code files become cheap outlines, so neither is touched.
    if expand and range is None:
        disconnect_cap = _max_result_bytes()
        inline_budget = _read_inline_budget_bytes()
        try:
            total_bytes = target.stat().st_size
        except OSError:
            total_bytes = 0
        # Tier 1: enormous file — never materialize it (a multi-MB JSON-RPC frame
        # disconnects the host). Read a bounded byte prefix straight from disk.
        if total_bytes > disconnect_cap:
            notice = (
                f"\n\n[atelier: result truncated — file is {total_bytes} bytes; read the "
                f"first {disconnect_cap} bytes only to keep the MCP connection alive. "
                'Re-request a narrower slice, e.g. read with range="L1-L400".]'
            )
            prefix_bytes = max(0, disconnect_cap - len(notice.encode("utf-8")) - 1024)
            with open(target, "rb") as fh:
                head = fh.read(prefix_bytes)
            return {
                "mode": "full",
                "content": head.decode("utf-8", "ignore") + notice,
                "path": str(target),
                "projection": SourceProjection.exact().to_dict(),
                "truncated": True,
                "bytes_total": total_bytes,
            }
        # Tier 2: moderately large — fits in memory but exceeds the host's
        # MCP-output limit, which would persist the result to a temp file and
        # force blind range re-reads. Pre-empt that with a line-aligned prefix
        # plus the EXACT continuation range, so a whole-file read costs at most a
        # couple of clean calls and the bytes are never dumped.
        if inline_budget and total_bytes > inline_budget:
            text = target.read_text(encoding="utf-8", errors="ignore")
            lines = text.splitlines(keepends=True)
            kept: list[str] = []
            used = 0
            for line in lines:
                line_bytes = len(line.encode("utf-8"))
                if kept and used + line_bytes > inline_budget:
                    break
                kept.append(line)
                used += line_bytes
            shown = len(kept)
            total_lines = len(lines)
            if shown < total_lines:
                notice = (
                    f"\n\n[atelier: showing lines 1-{shown} of {total_lines}. The full file "
                    f"({total_bytes} bytes) exceeds the single-response budget and would be "
                    f'truncated by the host. Continue with range="L{shown + 1}-", or request a '
                    "specific slice. To refactor a big file, read it in these labeled chunks.]"
                )
                return {
                    "mode": "full",
                    "content": "".join(kept) + notice,
                    "path": str(target),
                    "projection": SourceProjection.exact().to_dict(),
                    "truncated": True,
                    "bytes_total": total_bytes,
                    "lines_total": total_lines,
                    "lines_shown": shown,
                }

    cap = SemanticFileMemoryCapability(_atelier_root())
    try:
        payload = cap.smart_read(target, range_spec=range, expand=expand)
    except FileNotFoundError as exc:
        # Append nearest basename matches (or an authoritative "no such file
        # anywhere") so the model corrects the path instead of retrying it.
        workspace_root = Path(os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd()))
        suggestions = _suggest_paths_for_missing(workspace_root, target_path)
        if suggestions:
            raise FileNotFoundError(f"{exc}. Did you mean: {', '.join(suggestions)}") from exc
        raise FileNotFoundError(
            f"{exc}. No file named {Path(target_path).name!r} found under {workspace_root} — do not retry this path."
        ) from exc
    mode = payload["mode"]
    content = payload.get("content")
    # Whitespace-minify file bodies before they enter the agent's context
    # (token optimization that works under any host/orchestrator). Only the
    # conservative transform is applied (strip trailing whitespace + collapse
    # 3+ blank-line runs), which the fuzzy edit matcher tolerates. Outline mode
    # carries no body, so it is left untouched.
    projection = SourceProjection.outline() if mode == "outline" else SourceProjection.exact()
    projection_saved = 0
    projection_delta: dict[str, Any] | None = None
    projection_result: CompactProjectionResult | MinifiedProjectionResult | None = None
    exact_read = expand or range is not None
    if isinstance(content, str) and content and mode in ("full", "range") and not exact_read:
        from atelier.core.capabilities.source_projection import (
            ProjectionDelta,
            build_compact_projection,
            build_minified_projection,
            language_for_minify,
        )

        language = str(payload.get("language") or "")
        # Prefer the tree-sitter minified view (comments and blank lines
        # dropped, then re-parsed); fall back to the conservative compact
        # whitespace transform when minification does not apply. Callers can
        # pin the conservative compact view via projection_kind="compact".
        force_compact = projection_kind == "compact"
        minify_lang = language_for_minify(str(target))
        if minify_lang is not None and not force_compact:
            minified = build_minified_projection(content, minify_lang, include_mapping=True, path=str(target))
            if minified.applied:
                projection_result = minified
                projection = SourceProjection.minified()
        if projection_result is None:
            compact = build_compact_projection(content, language, include_mapping=True, path=str(target))
            if compact.applied:
                projection_result = compact
                projection = SourceProjection.compact()
        if projection_result is not None:
            content = projection_result.content
            projection_saved = projection_result.saved_tokens
            projection_delta = ProjectionDelta(
                path=str(payload.get("path", str(target))),
                lang=language,
                original_tokens=projection_result.original_tokens,
                projected_tokens=projection_result.projected_tokens,
            ).to_dict()
    elif mode == "range":
        projection = SourceProjection.range()
    response: dict[str, Any] = {
        "mode": mode,
        "outline": payload.get("outline"),
        "content": content,
        "path": payload.get("path", str(target)),
        "range": payload.get("range"),
        "language": payload.get("language"),
        "projection": projection.to_dict(),
    }
    ts = int(payload.get("tokens_saved", 0) or 0) + projection_saved
    # Always carry the projection mapping when a projection replaced the body, so
    # downstream edits can map projected coordinates back to source even without
    # include_meta (the top-level mode still reads "full"; the mapping is the
    # authoritative signal that the body is transformed).
    if projection_result is not None and projection_result.mapping is not None:
        response["projection_mapping"] = projection_result.mapping.to_dict()
    if include_meta:
        response["cache_hit"] = bool(payload.get("cache_hit", False))
        response["tokens_saved"] = ts
        if projection_delta is not None:
            response["projection_delta"] = projection_delta
    # Always save real savings via thread-local for the budget recorder
    if ts > 0:
        _tool_call_tokens_saved.value = ts
    return response


@mcp_tool(
    name="read",
    hidden_params=("projection_kind",),
    description=(
        "Read a file (or batch) with automatic source projection. Modes: outline "
        "(structure only; default for files >200 LOC), range (range='L42-L118' or "
        "open-ended 'L42-'), full (small files or expand=true), and compact. Re-read "
        "with expand=true or a range before editing against an outline/compact view. "
        "Batch 2+ files via files=[{path, range?}, ...] in one call."
    ),
)
def tool_smart_read(
    path: Annotated[
        str,
        Field(
            description=(
                "Workspace-relative file path to read. May carry a '#start-end' / '#line' "
                "line-range suffix, e.g. 'store.py#60-100'. "
                "For multiple independent files use `files` instead — one round trip for N reads."
            ),
        ),
    ] = "",
    range: str | None = None,
    expand: bool = False,
    max_lines: int | None = None,
    include_meta: Annotated[
        bool,
        Field(description="Include tool metadata fields (cache and token counters)."),
    ] = False,
    files: Annotated[
        list[dict[str, Any] | str] | None,
        Field(
            description=(
                "Batch read: ['path', ...] or [{path, range?, expand?, max_lines?}, ...] "
                "(plain strings and dict specs may be mixed). "
                "A plain string may carry a '#start-end' / '#line' suffix, e.g. "
                "'store.py#60-100', read as that line range. "
                "Returns {files: [{path, ...single-read result...}, ...]}. "
                "Use this whenever reading 2+ independent files — it costs one round trip "
                "vs one per file, cutting cached-context re-read tax by (N-1) turns."
            )
        ),
    ] = None,
    projection_kind: str | None = None,
    format: Annotated[Literal["auto", "compact", "json"], _FORMAT_FIELD] = "auto",
) -> dict[str, Any]:
    """Read a file (or batch of files) with automatic source projection.

    Modes: outline (structure only — default for files >200 LOC), range
    (range="42-118", "L42-L118", or open-ended "L42-" for an exact line slice),
    full (small files, or any file with expand=true), and compact (safe
    whitespace-only transformation of full reads — not byte-identical source).

    Prefer over native `Read`/`cat` unless the file is known to be small;
    outline mode typically saves 50-90% of tokens on large files. Re-read with
    expand=true (or a range) before editing against an outline/compact view.

    BATCH: when reading 2+ independent files, use files=[{path, range?}, ...]
    in a single call rather than separate calls — each extra turn re-reads the
    entire conversation history at ~$0.49/turn on large context windows.

    Cross-tool: after editing a file via `edit`, don't re-read it — the edit
    response already confirms the change. When you don't yet know which file
    holds something, use `grep` with output_mode="file_paths_with_content" to
    discover and read in one step instead of grep-then-read.
    """
    # Batch mode: process each file spec and return aggregated results.
    if files is not None:
        results = []
        batch_saved = 0
        for spec in files:
            if isinstance(spec, str):
                spec = {"path": spec}
            spec_path = str(spec.get("path") or "")
            if not spec_path:
                results.append({"error": "path is required in each files entry"})
                continue
            # _smart_read_single writes each file's saving to the thread-local
            # (last write wins). Capture it per file, stamp it on the entry so
            # per-entry baseline de-dup can zero an already-credited file, and
            # accumulate the batch total instead of letting the last file clobber
            # the rest. Reset between iterations so a stale value can't bleed in.
            _tool_call_tokens_saved.value = 0
            try:
                single = _smart_read_single(
                    path=spec_path,
                    range=spec.get("range"),
                    expand=bool(spec.get("expand", False)),
                    max_lines=spec.get("max_lines"),
                    include_meta=include_meta,
                    projection_kind=spec.get("projection_kind", projection_kind),
                )
                entry_saved = int(getattr(_tool_call_tokens_saved, "value", 0) or 0)
                if entry_saved > 0:
                    single["tokens_saved"] = entry_saved
                    batch_saved += entry_saved
                results.append(single)
            except Exception as exc:  # noqa: BLE001
                results.append({"path": spec_path, "error": str(exc)})
        _tool_call_tokens_saved.value = batch_saved
        return {"files": results}

    return _smart_read_single(
        path=path,
        range=range,
        expand=expand,
        max_lines=max_lines,
        include_meta=include_meta,
        projection_kind=projection_kind,
    )


def _snapshot_path(raw_path: str) -> str:
    if "#cell=" in raw_path:
        return raw_path.split("#cell=", 1)[0]
    match = re.search(r"#\d+(?:-\d+)?$", raw_path)
    return raw_path[: match.start()] if match else raw_path


def _resolve_snapshot_path(raw_path: str, repo_root: Path) -> tuple[str, Path]:
    """Return a ledger display path and workspace-resolved file path for snapshots."""
    clean = _snapshot_path(raw_path)
    candidate = Path(clean)
    resolved = candidate if candidate.is_absolute() else repo_root / candidate
    resolved = resolved.resolve()
    root = repo_root.resolve()
    try:
        display = str(resolved.relative_to(root))
    except ValueError:
        display = str(resolved)
    return display, resolved


def _collect_touched_paths(edits: list[dict[str, Any]], *, repo_root: str | Path | None = None) -> dict[str, Path]:
    """Extract workspace-resolved file paths referenced in edit descriptors."""
    root = Path(repo_root or Path.cwd()).resolve()
    paths: dict[str, Path] = {}
    for edit in edits:
        raw = str(edit.get("file_path") or edit.get("path") or "")
        if not raw and str(edit.get("kind") or "") == "symbol":
            from atelier.core.capabilities.tool_supervision.symbol_edit import (
                preview_symbol_edit_path,
            )

            with contextlib.suppress(Exception):
                raw = preview_symbol_edit_path(edit, repo_root=root)
        if raw:
            display, resolved = _resolve_snapshot_path(raw, root)
            paths[display] = resolved
    return dict(sorted(paths.items()))


def _snapshot_paths(paths: dict[str, Path]) -> dict[str, tuple[Path, bool, str | None]]:
    """Snapshot each file's pre-edit state for rollback.

    Returns ``(fp, existed, content)``. ``existed`` distinguishes a file that
    was genuinely absent pre-edit (rollback should delete it) from one that
    existed but could not be read (rollback must NOT delete it -- that would be
    silent data loss). ``existed=True`` with ``content is None`` means the file
    was unreadable: rollback skips it rather than deleting or truncating.
    """
    snap: dict[str, tuple[Path, bool, str | None]] = {}
    for display, fp in paths.items():
        existed = fp.exists()
        content: str | None = None
        if existed:
            try:
                content = fp.read_text(encoding="utf-8")
            except Exception:
                logging.exception("Recovered from broad exception handler")
                content = None
        snap[display] = (fp, existed, content)
    return snap


def _looks_like_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    parts = normalized.split("/")
    name = parts[-1]
    return (
        any(part in {"test", "tests", "spec", "specs", "__tests__"} for part in parts[:-1])
        or name.startswith("test_")
        or "_test." in name
        or ".test." in name
        or ".spec." in name
    )


# Files created by this process's edit tool. Tests the agent authored in this
# session are its own work in progress, not a pre-existing contract to protect.
_SESSION_CREATED_FILES: set[str] = set()


def _existing_test_contract_paths(
    snapshots: dict[str, tuple[Path, bool, str | None]],
) -> list[str]:
    return sorted(
        path
        for path, (fp, _existed, old_content) in snapshots.items()
        if old_content is not None and _looks_like_test_path(path) and str(fp.resolve()) not in _SESSION_CREATED_FILES
    )


def _compute_and_record_diffs(
    snapshots: dict[str, tuple[Path, bool, str | None]],
) -> dict[str, str]:
    """Compute unified diffs from *snapshots* vs current file content.

    Records each diff in the ledger and returns {display_path: diff_text} for
    callers that want to surface the diff inline (eliminating a read-after-edit turn).
    Only the first 30 lines of each diff are included in the return value to
    keep response size bounded.
    """
    import difflib

    led = _get_ledger()
    out: dict[str, str] = {}
    for path, (fp, existed, old_content) in snapshots.items():
        try:
            new_content = fp.read_text(encoding="utf-8") if fp.exists() else None
        except Exception:
            logging.exception("Recovered from broad exception handler")
            new_content = None
        if not existed and new_content is not None:
            _SESSION_CREATED_FILES.add(str(fp.resolve()))
        if old_content == new_content:
            continue
        old_lines = (old_content or "").splitlines(keepends=True)
        new_lines = (new_content or "").splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        diff_text = "".join(diff_lines) if diff_lines else ""
        if diff_text:
            led.record_file_event(path=path, event="edit", diff=diff_text)
            # Truncate for inline response: keep first 30 diff lines
            truncated_lines = diff_lines[:30]
            truncated = "".join(truncated_lines)
            if len(diff_lines) > 30:
                truncated += f"... ({len(diff_lines) - 30} more lines)\n"
            out[path] = truncated
        else:
            led.record_file_event(path=path, event="edit")
    return out


def _edit_descriptor_family(edit: dict[str, Any]) -> str:
    is_legacy = "op" in edit and "file_path" not in edit and "cell_action" not in edit
    return "legacy" if is_legacy else "rich"


def _validate_edit_descriptor_families(edits: list[dict[str, Any]]) -> str:
    if not edits:
        raise ValueError("edits must include at least one descriptor")
    families = {_edit_descriptor_family(edit) for edit in edits}
    if len(families) > 1:
        raise ValueError("cannot mix legacy op/path descriptors with rich edit descriptors in one call")
    return families.pop()


def _edit_verify_enabled(verify_flag: bool) -> bool:
    """Whether the WS1 executing edit gate should run for this call."""
    if verify_flag:
        return True
    val = os.environ.get("ATELIER_EDIT_VERIFY", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _restore_snapshots(
    snapshots: dict[str, tuple[Path, bool, str | None]],
    applied_content: dict[str, str | None] | None = None,
) -> list[str]:
    """Restore files to their pre-edit content (used when the verify gate fails).

    Must run under this call's per-path edit locks. When *applied_content* is
    given (this call's post-apply content per display path), a path is restored
    ONLY if its current on-disk content still equals what this call wrote;
    otherwise a concurrent edit committed in the window after this call released
    its lock, so we skip the restore to avoid clobbering that committed write
    (lost update). Returns the display paths skipped due to such a conflict.
    """
    conflicts: list[str] = []
    for display, (fp, existed, old_content) in snapshots.items():
        try:
            if applied_content is not None and display in applied_content:
                current = fp.read_text(encoding="utf-8") if fp.exists() else None
                if current != applied_content[display]:
                    # A concurrent edit moved this file on after we applied; the
                    # pre-edit content is stale, so restoring it would lose that
                    # update. Leave the concurrent write in place.
                    conflicts.append(display)
                    continue
            if not existed:
                if fp.exists():
                    fp.unlink()
            elif old_content is None:
                # Existed pre-edit but was unreadable at snapshot time: we have
                # no content to restore, so leave the file as-is rather than
                # deleting or truncating it (data-loss safe).
                conflicts.append(display)
                continue
            else:
                fp.write_text(old_content, encoding="utf-8")
        except Exception:
            logging.exception("Recovered from broad exception handler")
    return conflicts


def _apply_edit_verify_gate(
    result: dict[str, Any],
    *,
    touched: list[Path],
    snapshots: dict[str, tuple[Path, bool, str | None]],
    applied_content: dict[str, str | None] | None = None,
    checks: list[str] | None,
    rollback: bool,
    timeout_ms: int,
    repo_root: Path,
) -> None:
    """Run the executing parse + mypy/pytest gate; attach counterexamples and roll back on failure.

    Fully fail-open: a gate crash never blocks a legitimate edit.
    """
    try:
        from atelier.core.capabilities.verification.edit_gate import run_edit_gate

        checks_seq = tuple(checks) if checks else ("typecheck", "tests")
        counterexamples = run_edit_gate(
            touched,
            repo_root=repo_root,
            checks=checks_seq,
            timeout_s=max(1.0, timeout_ms / 1000),
        )
        errors = [c for c in counterexamples if c.severity == "error"]
        if not errors:
            result["verify"] = {"passed": True, "checks": list(checks_seq)}
            return
        result["verify"] = {"passed": False, "checks": list(checks_seq)}
        result["counterexamples"] = [c.to_dict() for c in errors]
        if rollback:
            # The gate runs outside the per-file edit locks (so verify can't
            # serialize concurrent edits); re-acquire them just for the rollback
            # restore-write so it can't race a concurrent edit to the same file.
            with contextlib.ExitStack() as _rb_locks:
                for _lock in _edit_path_locks(touched):
                    _rb_locks.enter_context(_lock)
                conflicts = _restore_snapshots(snapshots, applied_content)
            if conflicts:
                result["rollback_conflicts"] = conflicts
            result["rolled_back"] = True
            result["applied"] = []
            result["writes"] = 0
            result["verify"]["rolled_back"] = True
    except Exception:
        logging.exception("Recovered from broad exception handler")
        result["verify"] = {"passed": None, "error": "verify gate failed open"}


EDIT_TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "minItems": 1,
            "items": {
                "anyOf": [
                    {
                        "title": "File edit",
                        "type": "object",
                        "required": ["file_path", "new_string"],
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path, optionally suffixed with #line, #start-end, or #cell=N.",
                            },
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                            "overwrite": {"type": "boolean"},
                        },
                    },
                    {
                        "title": "Notebook cell edit",
                        "type": "object",
                        "required": ["file_path", "cell_action"],
                        "properties": {
                            "file_path": {"type": "string"},
                            "cell_action": {
                                "enum": [
                                    "insert_after",
                                    "insert_before",
                                    "delete",
                                    "move_after",
                                    "move_before",
                                ]
                            },
                            "cell_type": {"enum": ["code", "markdown"]},
                            "cell_move_target": {"type": "integer"},
                            "new_string": {"type": "string"},
                        },
                    },
                    {
                        "title": "Symbol edit",
                        "type": "object",
                        "required": ["kind"],
                        "properties": {
                            "kind": {"const": "symbol"},
                            "qualified_name": {"type": "string"},
                            "name": {"type": "string"},
                            "file_path": {"type": "string"},
                            "mode": {"enum": ["replace", "prepend", "append"]},
                            "new_body": {"type": "string"},
                            "preserve_signature": {"type": "boolean"},
                        },
                    },
                    {
                        "title": "Projection edit",
                        "type": "object",
                        "required": ["kind", "file_path", "projection_mapping"],
                        "properties": {
                            "kind": {"const": "projection"},
                            "file_path": {"type": "string"},
                            "projection_mapping": {
                                "type": "object",
                                "description": "Mapping returned by a compact read with include_meta=true.",
                            },
                            "projected_start": {"type": "integer"},
                            "projected_end": {"type": "integer"},
                            "new_string": {"type": "string"},
                            "projected_ranges": {
                                "type": "array",
                                "description": "Multiple non-overlapping exact spans from the same mapping; each item replaces one span.",
                                "items": {
                                    "type": "object",
                                    "required": ["projected_start", "projected_end", "new_string"],
                                    "properties": {
                                        "projected_start": {"type": "integer"},
                                        "projected_end": {"type": "integer"},
                                        "new_string": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                ]
            },
        },
        "atomic": {
            "type": "boolean",
            "default": True,
            "description": "Roll back all edits if any one fails.",
        },
        "post_edit_hooks": {
            "type": "boolean",
            "default": True,
            "description": "Run formatter/linter on touched files; error/warning diagnostics appear in the result.",
        },
        "post_edit_timeout_ms": {
            "type": "integer",
            "default": 30000,
            "minimum": 0,
            "description": "Maximum total timeout for post-edit hooks in milliseconds.",
        },
        "allow_test_contract_change": {
            "type": "boolean",
            "default": False,
            "description": "Allow edits to existing test files.",
        },
        "contract_change_evidence": {
            "type": "string",
            "description": "Required with allow_test_contract_change=true: cite the user request or source of truth requiring the contract change.",
        },
        "verify": {
            "type": "boolean",
            "default": False,
            "description": (
                "Run an executing correctness gate after the edit: a tree-sitter parse check "
                "(TS/JS/Rust/Go), scoped mypy over touched Python source, and pytest over touched "
                "test files. On an error-severity failure the edit is rolled back (see verify_rollback). "
                "Fail-open. Also enabled globally via ATELIER_EDIT_VERIFY=1."
            ),
        },
        "verify_checks": {
            "type": "array",
            "items": {"type": "string", "enum": ["typecheck", "tests", "lint"]},
            "description": "Which executing checks the verify gate runs (default: typecheck + tests). The parse gate always runs when verify is enabled.",
        },
        "verify_rollback": {
            "type": "boolean",
            "default": True,
            "description": "When the verify gate finds an error-severity counterexample, restore all touched files to their pre-edit state.",
        },
        "verify_timeout_ms": {
            "type": "integer",
            "default": 60000,
            "minimum": 0,
            "description": "Maximum per-subprocess timeout for the verify gate's mypy/pytest runs.",
        },
    },
    "required": ["edits"],
    "additionalProperties": False,
}


def _applied_entry_path(entry: str | dict[str, Any]) -> str | None:
    """Extract the file path from a raw applied entry, tolerating both shapes.

    Entries can be dicts (``{"path": ...}`` / ``{"file": ...}`` / ``{"file_path": ...}``,
    as emitted by ``apply_rich_edits`` and ``apply_batch_edit``) or already-compacted
    strings of the form ``"path:line,start-end"`` (as emitted by
    ``_compact_applied_entries``). A ``#10-20`` line suffix on the path is stripped so
    line-scoped edits to the same file collapse onto one path. Returns ``None`` when no
    path can be recovered.
    """
    if isinstance(entry, str):
        # Compacted form "path:spans" or plain "path"; spans only ever follow the
        # final ":" and contain digits/commas/hyphens, so split on the last ":".
        raw = entry.rsplit(":", 1)[0] if ":" in entry else entry
        raw = raw.strip()
    elif isinstance(entry, dict):
        candidate = entry.get("path") or entry.get("file") or entry.get("file_path")
        raw = str(candidate).strip() if candidate is not None else ""
    else:
        return None
    if not raw:
        return None
    # Drop a "#10-20" / "#cell=..." line/cell scope suffix so same-file scopes merge.
    return raw.split("#", 1)[0] or raw


def _distinct_edited_files(entries: list[Any]) -> int:
    """Count distinct files across applied entries.

    Built-in MultiEdit already batches multiple same-file hunks into one call, so
    Atelier's only honest advantage over a competent baseline is cross-file batching.
    Entries whose path cannot be recovered are counted as their own file so a
    legitimate cross-file edit is never under-credited.
    """
    distinct: set[str] = set()
    unparsed = 0
    for entry in entries:
        path = _applied_entry_path(entry)
        if path is None:
            unparsed += 1
        else:
            distinct.add(path)
    return len(distinct) + unparsed


def _compact_applied_entries(entries: list[dict[str, Any]]) -> list[str | dict[str, Any]]:
    """Group ordinary edit hunks by path while retaining special edit metadata."""
    grouped: dict[str, list[str]] = {}
    special: list[dict[str, Any]] = []
    for entry in entries:
        if set(entry) - {"path", "hunks"}:
            special.append(entry)
            continue
        path = str(entry.get("path", ""))
        spans = grouped.setdefault(path, [])
        for hunk in entry.get("hunks") or []:
            start = hunk.get("line_start")
            end = hunk.get("line_end")
            if isinstance(start, int) and isinstance(end, int):
                spans.append(str(start) if start == end else f"{start}-{end}")
    compact = [f"{path}:{','.join(spans)}" if spans else path for path, spans in grouped.items()]
    return [*compact, *special]


@mcp_tool(
    name="edit",
    input_schema=EDIT_TOOL_INPUT_SCHEMA,
    description=(
        "Apply many mechanical edits across files in one deterministic call. Each edit is "
        "one descriptor and all must share a family. Families (exact shapes in inputSchema): "
        "file replace {file_path, old_string, new_string}; create {file_path, new_string, "
        "overwrite:true}; line-scoped via file_path='foo.py#10-20'; notebook cell; symbol "
        "{kind:'symbol', qualified_name|name, mode, new_body}; projection {kind:'projection', "
        "...}. Maximise work per call: put every change in `edits`. Returns "
        "{applied:[...]}; failures stay structured."
    ),
)
def tool_smart_edit(
    edits: list[dict[str, Any]],
    atomic: bool = True,
    post_edit_hooks: bool = True,
    post_edit_timeout_ms: int = 30_000,
    allow_test_contract_change: bool = False,
    contract_change_evidence: str | None = None,
    verify: bool = False,
    verify_checks: list[str] | None = None,
    verify_rollback: bool = True,
    verify_timeout_ms: int = 60_000,
) -> dict[str, Any]:
    """Apply many mechanical edits across files in one deterministic call.

    Choose the right descriptor family for each edit (all must be the same family):

    Rich (preferred) — ``file_path`` required:
      - Replace text:    {file_path, old_string, new_string}
      - Create/overwrite:{file_path, new_string, overwrite: true}
      - Line-scoped:     {file_path: "foo.py#10-20", old_string, new_string}
      - Notebook cell:   {file_path, cell_action: insert_after|delete|..., new_string}
      - Symbol:          {kind: "symbol", qualified_name|name, mode, new_body}
      - Projection:      {kind: "projection", file_path, projection_mapping, projected_start+projected_end+new_string or projected_ranges}

    Legacy — ``path`` + ``op`` required:
      - replace:       {path, op: "replace", old_string, new_string, fuzzy?}
      - insert_after:  {path, op: "insert_after", anchor, new_string}
      - replace_range: {path, op: "replace_range", line_start, line_end, new_string}

    Maximise work per call: ``edits`` is the batching surface — fill it with every
    change in one call (ten edits to one file, or one edit each to ten files). One
    call with N edit objects beats N calls in both latency and cost. Prefer several
    small edits over one huge ``new_string``, and identify all target files up-front
    from your initial read. After editing, don't re-read the file — the response
    below already confirms the change.

    Returns ordinary successful hunks as {applied: ["path:line,start-end", ...]};
    failures and edits carrying special metadata remain structured.
    """
    # Resolve the edit root the same way reads do (honors CLAUDE/ATELIER
    # workspace env + per-request project override) so write-confinement below
    # matches the active workspace.
    repo_root = _workspace_root()
    family = _validate_edit_descriptor_families(edits)

    paths = _collect_touched_paths(edits, repo_root=repo_root)
    # Confine writes to the workspace root plus any additional directories from
    # Claude Code's additionalDirectories setting or ATELIER_ADDITIONAL_DIRS env.
    # Read tools accept any absolute path; writes need explicit opt-in.
    _extra_roots = _claude_additional_dirs(repo_root)
    _allowed_edit_roots = [repo_root, *_extra_roots]

    _escaped_edit_paths = [
        str(_p) for _p in paths.values() if not any(_p == _r or _p.is_relative_to(_r) for _r in _allowed_edit_roots)
    ]
    if _escaped_edit_paths:
        return {
            "applied": [],
            "failed": [
                {
                    "paths": _escaped_edit_paths,
                    "error": (
                        "edit path escapes the workspace root; add the directory via "
                        "additionalDirectories in ~/.claude/settings.json or "
                        "ATELIER_ADDITIONAL_DIRS env to allow edits there"
                    ),
                }
            ],
            "rolled_back": True,
            "writes": 0,
        }
    # Serialize the snapshot/apply/write critical section per touched file so two
    # concurrent edit calls cannot read-modify-write the same file and lose one
    # update. Locks are ordered by path (inside _edit_path_locks) to avoid
    # deadlock and release on every return below via the ExitStack.
    # This call's post-apply content per display path, captured under the edit
    # lock. The verify gate (which runs after the lock releases) uses it to skip
    # restoring any file a concurrent edit moved on, avoiding a lost update.
    applied_content: dict[str, str | None] = {}
    with contextlib.ExitStack() as _edit_locks:
        for _lock in _edit_path_locks(list(paths.values())):
            _edit_locks.enter_context(_lock)
        snapshots = _snapshot_paths(paths)
        contract_paths = _existing_test_contract_paths(snapshots)
        evidence = (contract_change_evidence or "").strip()
        if contract_paths and (not allow_test_contract_change or len(evidence) < 20):
            return {
                "applied": [],
                "failed": [
                    {
                        "paths": contract_paths,
                        "error": (
                            "Existing test contract edit requires explicit review before writing. Reconsider the "
                            "production change first. If the contract truly must change, retry with "
                            "allow_test_contract_change=true and contract_change_evidence citing the user request or "
                            "repository source of truth."
                        ),
                    }
                ],
                "rolled_back": True,
                "writes": 0,
                "contract_review": {"required": True, "paths": contract_paths},
            }

        if family == "rich":
            from atelier.core.capabilities.tool_supervision.rich_edit import apply_rich_edits

            result = apply_rich_edits(edits, atomic=atomic, repo_root=repo_root, allowed_roots=_extra_roots)
        else:
            from atelier.core.capabilities.tool_supervision.batch_edit import apply_batch_edit

            result = apply_batch_edit(edits, atomic=atomic, repo_root=repo_root, allowed_roots=_extra_roots)

        if not result.get("failed") and not result.get("rolled_back"):
            if post_edit_hooks:
                from atelier.core.capabilities.tool_supervision.post_edit_hooks import (
                    HookConfig,
                    run_post_edit_hooks,
                )

                try:
                    hook_result = run_post_edit_hooks(
                        [str(p) for p in paths.values()],
                        repo_root=repo_root,
                        config=HookConfig(total_timeout_s=post_edit_timeout_ms / 1000),
                    )
                    result["diagnostics"] = [
                        {
                            "file": d.file,
                            "line": d.line,
                            "col": d.col,
                            "severity": d.severity,
                            "message": d.message,
                            "code": d.code,
                            "source": d.source,
                        }
                        for d in hook_result.diagnostics
                    ]
                    result["hooks"] = {
                        "ran": hook_result.steps_ran,
                        "skipped": hook_result.steps_skipped,
                        "failed_steps": hook_result.steps_failed,
                        "total_ms": hook_result.total_ms,
                    }
                except Exception as hook_exc:
                    logging.exception("Recovered from broad exception handler")
                    result["hooks"] = {"error": str(hook_exc)}
            # WS1 edit-loop correctness gate: optional executing parse + scoped
            # mypy/pytest verification with rollback. Opt-in via the `verify` arg or
            # the ATELIER_EDIT_VERIFY env var; fully fail-open.
            # Diffs are always recorded to the ledger (audit/undo), computed
            # inside the lock so a concurrent edit can't race the post-apply
            # read. They are surfaced inline ONLY when an edit landed via a
            # non-exact match (normalized/placeholder/fuzzy): there the applied
            # text may diverge from what the caller asked for, so the diff is
            # the sole signal of that divergence and earns its tokens by saving
            # a verifying re-read. For exact matches the caller already knows
            # old->new and the `applied` line ranges, so an inline diff is pure
            # redundancy.
            diffs = _compute_and_record_diffs(snapshots)
            for _disp, _fp in paths.items():
                try:
                    applied_content[_disp] = _fp.read_text(encoding="utf-8") if _fp.exists() else None
                except Exception:
                    logging.exception("Recovered from broad exception handler")
                    applied_content[_disp] = None
            _applied = result.get("applied") or []
            if diffs and any(
                isinstance(e, dict) and e.get("match_mode") in ("normalized", "placeholder", "fuzzy")
                for e in _applied
            ):
                result["diff"] = diffs
            # match_mode is only informative when it is not the default exact match.
            for entry in _applied:
                if isinstance(entry, dict) and entry.get("match_mode") == "exact":
                    entry.pop("match_mode", None)
            if contract_paths:
                result["contract_review"] = {
                    "required": True,
                    "paths": contract_paths,
                    "evidence": evidence,
                }

    # WS1 edit-loop correctness gate: optional executing parse + scoped mypy/pytest
    # verification with rollback. Run OUTSIDE the per-file edit locks (released at
    # the end of the with-block above) so a slow verify (up to verify_timeout_ms)
    # can't serialize concurrent edits to the same file; the gate re-acquires the
    # locks only for its rollback restore-write. Opt-in via `verify` or
    # ATELIER_EDIT_VERIFY; fully fail-open.
    if not result.get("failed") and not result.get("rolled_back") and _edit_verify_enabled(verify):
        _apply_edit_verify_gate(
            result,
            touched=list(paths.values()),
            snapshots=snapshots,
            applied_content=applied_content,
            checks=verify_checks,
            rollback=verify_rollback,
            timeout_ms=verify_timeout_ms,
            repo_root=repo_root,
        )
        if result.get("rolled_back"):
            # Files were restored to pre-edit state; the inline diff no longer applies.
            result.pop("diff", None)

    # Include diagnostics inline: this IS the lint-after-edit turn.
    # Filter to errors/warnings only — informational notes add noise.
    if "diagnostics" in result:
        result["diagnostics"] = [d for d in result["diagnostics"] if d.get("severity") in ("error", "warning")]
        if not result["diagnostics"]:
            result.pop("diagnostics")
    # Strip verbose hooks metadata — callers don't need step details.
    result.pop("hooks", None)

    # Honest cross-file batching credit: Claude Code's built-in MultiEdit already
    # batches multiple hunks within a single file into one call, so collapsing
    # same-file hunks is no saving vs a competent baseline. Atelier's genuine
    # advantage is only batching edits across *distinct files*, so credit
    # (distinct files - 1) calls. The dispatcher reads this and writes it into the
    # response's content[].saved.calls field.
    applied_entries = result.get("applied") or []
    distinct_files = _distinct_edited_files(applied_entries)
    if distinct_files > 1:
        result.setdefault("calls_saved", distinct_files - 1)
    if applied_entries and not result.get("failed") and not result.get("rolled_back"):
        result["applied"] = _compact_applied_entries(applied_entries)
    return result


SQL_TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "connect",
                "tables",
                "schema",
                "table",
                "relationships",
                "search",
                "lint",
                "query",
            ],
            "description": (
                "connect: discover DB. tables: list tables. schema: all columns + FKs. table/search: one table "
                "or keyword match (needs name). relationships: FK graph. lint: validate SQL (needs sql). "
                "query: execute (needs sql or queries[])."
            ),
        },
        "name": {
            "type": "string",
            "description": "Target table for action=table, or keyword for action=search.",
        },
        "sql": {
            "type": "string",
            "description": "SQL string for action=lint or action=query.",
        },
        "queries": {
            "type": "array",
            "description": "Batch for action=query: [{name, sql}, ...]. Prefer over repeated calls.",
            "items": {
                "type": "object",
                "required": ["sql"],
                "properties": {
                    "name": {"type": "string"},
                    "sql": {"type": "string"},
                },
            },
        },
        "connection_string": {
            "type": "string",
            "description": "DSN (sqlite:///path, postgresql://...). Auto-discovered from DATABASE_URL/.env if omitted.",
        },
        "max_rows": {"type": "integer", "default": 500},
        "allow_writes": {
            "type": "boolean",
            "default": False,
            "description": "Permit INSERT/UPDATE/DELETE/DDL on action=query/lint. Off by default; reads always allowed.",
        },
        "auto_limit": {
            "type": "boolean",
            "default": True,
            "description": "Append LIMIT max_rows when missing.",
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}


@mcp_tool(name="sql", input_schema=SQL_TOOL_INPUT_SCHEMA)
def tool_sql(
    action: str,
    name: str | list[str] | None = None,
    sql: str | None = None,
    queries: list[dict[str, str]] | None = None,
    connection_string: str | None = None,
    max_rows: int = 500,
    timeout_ms: int = 30_000,
    auto_limit: bool = True,
    allow_writes: bool = False,
) -> dict[str, Any]:
    """SQL op-dispatch for connect, lint, and bounded query batching.

    Actions:
      connect       — discover database and show schema overview
      tables        — list table names (+ count)
      schema        — columns + foreign keys per table
      table         — one table's columns + foreign keys (needs name)
      relationships — foreign-key graph as {from: "t.col", to: "rt.col"}
      search        — keyword over table/column names -> matching tables with columns + FKs (needs name)
      lint          — validate SQL syntax without executing (needs sql)
      query         — execute SQL (needs sql or queries[{name,sql},...])

    Connection is auto-discovered from DATABASE_URL env or .env file.
    Pass connection_string explicitly to override. Live introspection/queries run on SQLite;
    other dialects report a driver-required note.

    Returns: introspection actions return {tables|table_count|schema|columns|foreign_keys|relationships|matches};
    lint -> {ok, message}; query -> {results: [{name, columns, rows, row_count, truncated}], took_ms}.
    """
    from atelier.core.capabilities.tool_supervision.sql_tool import sql_tool

    if action not in {
        "connect",
        "tables",
        "schema",
        "table",
        "relationships",
        "search",
        "lint",
        "query",
    }:
        return {
            "isError": True,
            "message": "unsupported action: use connect, tables, schema, table, relationships, search, lint, or query",
        }
    if action == "query" and not sql and not queries:
        return {"isError": True, "message": "action='query' requires sql or queries parameter"}

    result = sql_tool(
        action=action,
        name=name,
        sql=sql,
        queries=queries,
        connection_string=connection_string,
        max_rows=max_rows,
        timeout_ms=timeout_ms,
        auto_limit=auto_limit,
        allow_writes=allow_writes,
        repo_root=os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd()),
    )
    # Batched queries collapse N would-be individual sql calls into 1.
    if isinstance(result, dict) and isinstance(queries, list) and len(queries) > 1:
        result.setdefault("calls_saved", len(queries) - 1)
    return result


_TASK_BOUNDARY_SUCCESS_RE = re.compile(
    r"\b(done|complete|completed|success|successful|passed|tests?\s+pass(?:ed)?|validated|verified|committed|lgtm)\b",
    re.IGNORECASE,
)
_TASK_BOUNDARY_FAILURE_RE = re.compile(
    r"\b(fail(?:ed|ure)?|error|exception|traceback|blocked|todo|not\s+done|not\s+complete)\b",
    re.IGNORECASE,
)


def _ledger_turn_count(led: RunLedger) -> int:
    turn_events = [
        event
        for event in led.events
        if event.kind in {"agent_message", "reasoning", "test_result", "command_result", "tool_result"}
    ]
    if turn_events:
        return len(turn_events)
    return len(led.events)


def _event_text(event: Any) -> str:
    summary = str(getattr(event, "summary", ""))
    payload = getattr(event, "payload", {})
    return f"{summary}\n{json.dumps(payload, ensure_ascii=False, default=str)}"


def _task_boundary_detected(led: RunLedger) -> bool:
    """Return true only when recent ledger events show a clean stopping point."""
    for event in led.events[-3:]:
        text = _event_text(event)
        if _TASK_BOUNDARY_SUCCESS_RE.search(text) and not _TASK_BOUNDARY_FAILURE_RE.search(text):
            if event.kind == "test_result":
                return bool(event.payload.get("passed"))
            if event.kind == "command_result":
                return bool(event.payload.get("ok"))
            return True
    return False


def _context_lifecycle_decision(led: RunLedger) -> dict[str, Any]:
    tokens_used = led.token_count + max(0, len(led.events) * 10)
    utilisation_pct = round(100.0 * tokens_used / CONTEXT_WINDOW_TOKENS, 1)
    turn_count = _ledger_turn_count(led)
    boundary = _task_boundary_detected(led)
    should_handover = utilisation_pct >= HANDOVER_THRESHOLD
    # Bypass the min-turns gate when utilisation is already very high - a small
    # number of dense turns (huge tool outputs, large file reads) can fill the
    # window just as fast as many small ones.
    turns_gate_passed = turn_count > AUTO_COMPACT_MIN_TURNS or utilisation_pct >= AUTO_COMPACT_HIGH_UTIL_OVERRIDE
    should_auto_compact = (
        not should_handover and utilisation_pct >= AUTO_COMPACT_THRESHOLD and turns_gate_passed and boundary
    )
    should_advise = utilisation_pct >= COMPACT_ADVISORY_THRESHOLD

    if should_handover:
        reason = "context utilization reached handover threshold"
    elif should_auto_compact:
        reason = "context utilization reached auto-compact threshold at a task boundary"
    elif utilisation_pct >= AUTO_COMPACT_THRESHOLD and not turns_gate_passed:
        reason = f"auto-compact gated: fewer than {AUTO_COMPACT_MIN_TURNS} turns and below {AUTO_COMPACT_HIGH_UTIL_OVERRIDE}% override"
    elif utilisation_pct >= AUTO_COMPACT_THRESHOLD and not boundary:
        reason = "auto-compact waiting for a clean task boundary"
    elif should_advise:
        reason = "advisory threshold reached; no automatic action"
    else:
        reason = "below advisory threshold"

    return {
        "tokens_used": tokens_used,
        "context_window": CONTEXT_WINDOW_TOKENS,
        "utilisation_pct": utilisation_pct,
        "turn_count": turn_count,
        "task_boundary_detected": boundary,
        "should_advise": should_advise,
        "should_auto_compact": should_auto_compact,
        "should_compact": should_auto_compact,
        "should_handover": should_handover,
        "reason": reason,
        "thresholds": {
            "advisory_pct": COMPACT_ADVISORY_THRESHOLD,
            "auto_compact_pct": AUTO_COMPACT_THRESHOLD,
            "handover_pct": HANDOVER_THRESHOLD,
            "auto_compact_min_turns": AUTO_COMPACT_MIN_TURNS,
        },
    }


def _write_handover_packet(led: RunLedger, state: Any) -> Path:
    from atelier.infra.runtime.context_compressor import HandoverPacket

    root = _atelier_root()
    run_dir = session_run_dir(root, led.session_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    handover_path = run_dir / "HANDOVER.md"
    packet = HandoverPacket.from_ledger(led, state, workspace_root=_workspace_root())
    handover_path.write_text(packet.to_markdown(), encoding="utf-8")
    return handover_path


_COMPACT_ADVISE_CACHE: dict[str, tuple[int, Any]] = {}
_MAX_COMPACT_ADVISE_CACHE = 64


def _compact_advise(session_id: str | None = None) -> dict[str, Any]:
    """Advise when to compact and what context to preserve.

    Returns a manifest with:
    - should_advise: bool (true if utilisation >= 60%)
    - should_compact: bool (true if utilisation >= 80%, after min-turn and boundary gates)
    - should_handover: bool (true if utilisation >= 95%)
    """
    try:
        from atelier.infra.runtime.context_compressor import ContextCompressor

        led = _get_ledger()
        if session_id:
            led.session_id = session_id

        lifecycle = _context_lifecycle_decision(led)
        utilisation_pct = float(lifecycle["utilisation_pct"])
        should_compact = bool(lifecycle["should_compact"])
        should_handover = bool(lifecycle["should_handover"])
        # Memoize the full-ledger compression by (session, event count): this
        # advisory entrypoint may be polled repeatedly without the ledger
        # changing, and compress() walks every event each call. compress() is
        # pure (reads events, returns a fresh CompactState), so reuse is safe.
        _ca_key = led.session_id or ""
        _ca_cached = _COMPACT_ADVISE_CACHE.get(_ca_key)
        if _ca_cached is not None and _ca_cached[0] == len(led.events):
            state = _ca_cached[1]
        else:
            state = ContextCompressor().compress(led, preserve_last_n_turns=10, workspace_root=_workspace_root())
            _COMPACT_ADVISE_CACHE[_ca_key] = (len(led.events), state)
            if len(_COMPACT_ADVISE_CACHE) > _MAX_COMPACT_ADVISE_CACHE:
                # Bound the cache: a marathon process seeing many session ids must
                # not leak compressed states. Evict oldest (skip current).
                for _stale in list(_COMPACT_ADVISE_CACHE)[
                    : len(_COMPACT_ADVISE_CACHE) - _MAX_COMPACT_ADVISE_CACHE
                ]:
                    if _stale != _ca_key:
                        _COMPACT_ADVISE_CACHE.pop(_stale, None)
        compaction_savings = _session_compaction_savings_payload(
            led,
            state,
            tokens_before=int(lifecycle["tokens_used"]),
            trigger="compact_advise",
            reason=str(lifecycle["reason"]),
            utilisation_pct=utilisation_pct,
        )

        # Collect preserve_playbooks: top active Playbooks from ledger
        preserve_playbooks = list(set(led.active_playbooks))[:3]

        # Collect pin_memory: pinned MemoryBlocks for this run's agent
        pin_memory: list[str] = []
        try:
            store = _memory_store()
            agent_id = led.agent or "claude"
            pinned = store.list_pinned_blocks(agent_id=agent_id)
            pin_memory = [b.id for b in pinned][:5]
        except Exception:
            logging.exception("Recovered from broad exception handler")
            logger.warning(
                "Suppressed exception in _compact_advise fetching pinned memory",
                exc_info=True,
            )

        # Collect open_files: last 5 files touched
        open_files = led.files_touched[-5:] if led.files_touched else []
        handover_file: str | None = None
        if should_handover:
            handover_file = str(_write_handover_packet(led, state))

        # Build suggested prompt
        if should_handover:
            suggested_prompt = (
                f"Session is at {utilisation_pct}% context utilisation. Read {handover_file} and continue "
                "from a fresh agent context using the host-native agent/subagent mechanism."
            )
        else:
            suggested_prompt = (
                f"Compact this conversation. Context utilisation: {utilisation_pct}%. "
                f"Please preserve these Playbooks: {', '.join(preserve_playbooks) or '(none yet)'}. "
                f"Recently edited files: {', '.join(open_files) or '(none)'}. "
                "Preserve the last 10 raw turns, active errors, and current CLAUDE.md hash."
            )

        # Persist manifest to disk
        try:
            root = _atelier_root()
            run_dir = session_run_dir(root, led.session_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = run_dir / "compact_manifest.json"
            manifest = {
                "created_at": datetime.now(UTC).isoformat(),
                "session_id": led.session_id,
                "should_compact": should_compact,
                "should_advise": bool(lifecycle["should_advise"]),
                "should_auto_compact": bool(lifecycle["should_auto_compact"]),
                "should_handover": should_handover,
                "utilisation_pct": utilisation_pct,
                "turn_count": int(lifecycle["turn_count"]),
                "task_boundary_detected": bool(lifecycle["task_boundary_detected"]),
                "reason": str(lifecycle["reason"]),
                "thresholds": lifecycle["thresholds"],
                "preserve_playbooks": preserve_playbooks,
                "pin_memory": pin_memory,
                "open_files": open_files,
                "recent_turns": state.recent_turns,
                "claude_md_hash": state.claude_md_hash,
                "active_errors": state.error_fingerprints,
                "handover_file": handover_file,
                "suggested_prompt": suggested_prompt,
            }
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            logging.exception("Recovered from broad exception handler")
            logger.warning(
                "Suppressed exception in _compact_advise persisting manifest",
                exc_info=True,
            )

        if should_compact and int(compaction_savings["tokens_saved"]) > 0:
            _append_live_savings_event(compaction_savings)

        return {
            "should_compact": should_compact,
            "should_advise": bool(lifecycle["should_advise"]),
            "should_auto_compact": bool(lifecycle["should_auto_compact"]),
            "should_handover": should_handover,
            "utilisation_pct": utilisation_pct,
            "turn_count": int(lifecycle["turn_count"]),
            "task_boundary_detected": bool(lifecycle["task_boundary_detected"]),
            "reason": str(lifecycle["reason"]),
            "thresholds": lifecycle["thresholds"],
            "preserve_playbooks": preserve_playbooks,
            "pin_memory": pin_memory,
            "open_files": open_files,
            "recent_turns": state.recent_turns,
            "claude_md_hash": state.claude_md_hash,
            "active_errors": state.error_fingerprints,
            "handover_file": handover_file,
            "suggested_prompt": suggested_prompt,
            "tokens_before": int(compaction_savings["tokens_before"]),
            "tokens_after_estimate": int(compaction_savings["tokens_after_estimate"]),
            "tokens_freed": int(compaction_savings["tokens_freed"]),
            "cost_saved_usd": float(compaction_savings["cost_saved_usd"]),
        }
    except Exception:
        logging.exception("Recovered from broad exception handler")
        # Fail-open: return conservative defaults
        return {
            "should_compact": False,
            "should_advise": False,
            "should_auto_compact": False,
            "should_handover": False,
            "utilisation_pct": 0.0,
            "turn_count": 0,
            "task_boundary_detected": False,
            "reason": "Unable to compute compaction advice; proceed conservatively.",
            "thresholds": {
                "advisory_pct": COMPACT_ADVISORY_THRESHOLD,
                "auto_compact_pct": AUTO_COMPACT_THRESHOLD,
                "handover_pct": HANDOVER_THRESHOLD,
                "auto_compact_min_turns": AUTO_COMPACT_MIN_TURNS,
            },
            "preserve_playbooks": [],
            "pin_memory": [],
            "open_files": [],
            "recent_turns": [],
            "claude_md_hash": None,
            "active_errors": [],
            "handover_file": None,
            "suggested_prompt": "Unable to compute compaction advice; proceed with default compaction.",
        }


def _memory_summary(session_id: str) -> dict[str, Any]:
    """Run the sleeptime summarizer for a given run and return a summary.

    Input:
        session_id: The run identifier to summarize.

    Output:
        tokens_pre, tokens_post, summary_md, evicted_event_ids, strategy
    """
    try:
        from atelier.core.capabilities.context_compression.capability import (
            ContextCompressionCapability,
        )

        led = _get_ledger()
        if session_id:
            led.session_id = session_id

        cap = ContextCompressionCapability()
        result = cap.compress_with_sleeptime(led)

        summary_lines = [f"## Sleeptime Summary - run `{led.session_id}`", ""]
        summary_lines.append(f"- Tokens before: {result.chars_before // 4}")
        summary_lines.append(f"- Tokens after:  {result.chars_after // 4}")
        summary_lines.append(f"- Reduction:     {result.reduction_pct}%")
        if result.dropped:
            summary_lines.append("")
            summary_lines.append("### Evicted events")
            for d in result.dropped[:10]:
                summary_lines.append(f"- [{d.kind}] {d.summary[:100]}")

        return {
            "tokens_pre": result.chars_before // 4,
            "tokens_post": result.chars_after // 4,
            "summary_md": "\n".join(summary_lines),
            "evicted_event_ids": [d.kind for d in result.dropped],
            "strategy": "tfidf",
        }
    except Exception as exc:
        logging.exception("Recovered from broad exception handler")
        return {"error": str(exc)}


# Thread-local used to pass the active engine into _maybe_attach_code_rendered
# for cold-start bootstrap-note injection without touching every return branch.
_code_engine_for_current_call: threading.local = threading.local()

# Process-level engine cache keyed by resolved repo path.
# Reusing the same engine across tool calls avoids re-opening the SQLite DB
# and restarting autosync threads on every invocation — critical for both
# MCP server performance (persistent process) and benchmark correctness.
_code_engine_cache: dict[str, Any] = {}
_code_engine_cache_lock: threading.Lock = threading.Lock()
_scoped_context_cache: dict[str, Any] = {}
_scoped_context_cache_lock: threading.Lock = threading.Lock()


def _code_context_engine(repo_root: str = ".") -> Any:
    from atelier.core.capabilities.code_context import CodeContextEngine

    workspace = str(_workspace_root())
    root = Path(repo_root)
    resolved = (root if root.is_absolute() else Path(workspace) / root).resolve()
    cache_key = str(resolved)
    engine = _code_engine_cache.get(cache_key)
    if engine is None:
        with _code_engine_cache_lock:
            engine = _code_engine_cache.get(cache_key)  # re-check under lock
            if engine is None:
                engine = CodeContextEngine(resolved, nonblocking_reads=True)
                _code_engine_cache[cache_key] = engine
    return engine


def _scoped_context_capability(repo_root: str = ".") -> Any:
    from atelier.core.capabilities.scoped_context import ScopedContextCapability

    workspace = str(_workspace_root())
    root = Path(repo_root)
    resolved = (root if root.is_absolute() else Path(workspace) / root).resolve()
    cache_key = str(resolved)
    capability = _scoped_context_cache.get(cache_key)
    if capability is None:
        with _scoped_context_cache_lock:
            capability = _scoped_context_cache.get(cache_key)
            if capability is None:
                capability = ScopedContextCapability(_code_context_engine(str(resolved)))
                _scoped_context_cache[cache_key] = capability
    return capability


def _workspace_code_router(repo_root: str = ".") -> Any:
    from atelier.core.capabilities.code_context.workspace_router import WorkspaceCodeRouter

    workspace = str(_workspace_root())
    root = Path(repo_root)
    resolved = root if root.is_absolute() else Path(workspace) / root
    return WorkspaceCodeRouter(
        repo_root=resolved,
        engine_factory=lambda target_root: _code_context_engine(str(target_root)),
    )


# Fields that are purely internal Atelier bookkeeping — never useful to an LLM.
# Keep: repo_name (multi-repo).
_CODE_OP_TOP_STRIP: frozenset[str] = frozenset(
    {
        "symbol_id",
        "cache_hit",
        "rendered_format",
        "repo_id",
        "total_tokens",
        "tokens_saved",
        "provenance",
        "provenance_breakdown",
        "mode",
        "view",
        "has_more_context",
        "suggested_next",
        "explanation",
        "text_search",
    }
)

# Fields to strip from nested item dicts (search results, callers/related lists, etc.).
# Keep: origin (external/internal scope), repo_name (multi-repo workspace).
_CODE_OP_ITEM_STRIP: frozenset[str] = frozenset(
    {
        "symbol_id",
        "start_byte",
        "end_byte",
        "content_hash",
        "repo_id",
        "score",
        "provenance",
    }
)

# Extra top-level keys to drop per-op (in addition to _CODE_OP_TOP_STRIP).
_CODE_OP_EXTRA_STRIP: dict[str, frozenset[str]] = {
    # edges contain only SCIP hash IDs — no names or paths; `related` has the useful data
    "callers": frozenset({"edges"}),
    "callees": frozenset({"edges"}),
    # symbol op: byte offsets and hashes are useless to LLMs
    "symbol": frozenset({"start_byte", "end_byte", "content_hash", "score"}),
    # search: `snippet` at top level is just the mode string ("none"/"head"/"full"), not actual code
    "search": frozenset({"snippet"}),
    # context: `symbols` duplicates entry_points with heavy metadata; telemetry/import_neighbors are internal
    "context": frozenset({"telemetry", "import_neighbors", "symbols"}),
    # status: db_path exposes internal filesystem paths
    "status": frozenset({"db_path"}),
}

# List-valued fields whose items should be stripped of internal keys.
_CODE_OP_ITEM_LIST_FIELDS: tuple[str, ...] = (
    "items",
    "related",
    "related_symbols",
    "entry_points",
    "references",
    "symbols",
)


def _strip_code_item(item: dict[str, Any]) -> dict[str, Any]:
    """Strip internal bookkeeping from a single result item."""
    cleaned = {k: v for k, v in item.items() if k not in _CODE_OP_ITEM_STRIP}
    if cleaned.get("origin") == "internal":
        del cleaned["origin"]
    if cleaned.get("qualified_name") and cleaned["qualified_name"] == (
        cleaned.get("name") or cleaned.get("symbol_name")
    ):
        del cleaned["qualified_name"]
    cleaned.pop("role", None)
    return cleaned


def _strip_code_op_response(op: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Remove internal/telemetry fields that waste LLM context."""
    drop = _CODE_OP_TOP_STRIP | _CODE_OP_EXTRA_STRIP.get(op, frozenset())
    result: dict[str, Any] = {k: v for k, v in payload.items() if k not in drop}

    # Save real tokens_saved via thread-local so _record_context_budget_for_tool
    # can read it without polluting the LLM-facing response.
    ts = int(payload.get("tokens_saved", 0) or 0)
    if ts > 0:
        _tool_call_tokens_saved.value = ts

    # Strip internal keys from the target object
    if isinstance(result.get("target"), dict):
        result["target"] = _strip_code_item(result["target"])

    # Strip internal keys from list fields (or dicts of lists, e.g. references grouped by file)
    for field in _CODE_OP_ITEM_LIST_FIELDS:
        value = result.get(field)
        if isinstance(value, list):
            result[field] = [_strip_code_item(item) if isinstance(item, dict) else item for item in value]
        elif isinstance(value, dict):
            result[field] = {
                key: (
                    [_strip_code_item(item) if isinstance(item, dict) else item for item in group]
                    if isinstance(group, list)
                    else group
                )
                for key, group in value.items()
            }

    return result


def _maybe_attach_code_rendered(op: str, payload: dict[str, Any], *, render_compact: bool) -> dict[str, Any]:
    # Render first so the markdown uses all original fields (e.g. repo_id for cache_status heading).
    from atelier.core.capabilities.code_context.renderer import render_code_payload

    rendered = render_code_payload(op, payload)

    # Store in thread-local so _handle can use MD text as the MCP response body.
    _tool_call_rendered_text.value = rendered

    # Strip internal fields after rendering — LLMs get clean JSON without duplicating
    # internal bookkeeping that only Atelier needs.
    result = _strip_code_op_response(op, payload)

    if render_compact and rendered:
        result["rendered"] = rendered

    # Inject cold-start bootstrap note so the LLM knows results may be incomplete.
    if op not in {"index", "status", "cache_status"}:
        engine = getattr(_code_engine_for_current_call, "value", None)
        if engine is not None and not Path(engine.db_path).exists():
            result["bootstrap_note"] = (
                "Repository not yet indexed — results may be incomplete. "
                "Run `atelier code index` (or `atelier project init`) to bootstrap the index."
            )

    return result


def _code_search_target_item(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": item.get("kind"),
        "name": item.get("name") or item.get("symbol_name"),
        "qualified_name": item.get("qualified_name"),
        "path": item.get("path") or item.get("file_path"),
        "repo_name": item.get("repo_name"),
        "origin": item.get("origin"),
        "line": item.get("line") or item.get("start_line"),
        "end_line": item.get("end_line"),
        "signature": item.get("signature"),
        "snippet": item.get("snippet"),
        "deleted_at": item.get("deleted_at"),
        "deleted_at_sha": item.get("deleted_at_sha"),
        "rename_target": item.get("rename_target"),
        "rename_note": item.get("rename_note"),
    }
    return {key: value for key, value in result.items() if value is not None}


def _code_search_target_view(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items")
    if isinstance(items, list):
        payload["items"] = [_code_search_target_item(item) if isinstance(item, dict) else item for item in items]
    return payload


def _flatten_code_references(references: Any) -> list[dict[str, Any]]:
    if isinstance(references, list):
        return [dict(item) for item in references if isinstance(item, dict)]
    if isinstance(references, dict):
        flattened: list[dict[str, Any]] = []
        for values in references.values():
            if isinstance(values, list):
                flattened.extend(dict(item) for item in values if isinstance(item, dict))
        return flattened
    return []


def _code_search_graph_view(
    engine: Any,
    *,
    query: str,
    search_payload: dict[str, Any],
    view: Literal["graph", "explain"],
    limit: int,
    depth: int,
    budget_tokens: int,
) -> dict[str, Any]:
    items = search_payload.get("items")
    primary = next((item for item in items if isinstance(item, dict)), None) if isinstance(items, list) else None
    if primary is None:
        return {
            "target": None,
            "related": {"imports": [], "usages": [], "callers": [], "callees": []},
        }

    target = _code_search_target_item(primary)
    symbol_args = {
        "query": query,
        "symbol_id": primary.get("symbol_id") or primary.get("id"),
        "qualified_name": primary.get("qualified_name"),
        "symbol_name": primary.get("symbol_name") or primary.get("name"),
        "file_path": primary.get("file_path") or primary.get("path"),
    }
    relation_budget = max(300, budget_tokens // 3)
    usages = engine.tool_usages(
        query=symbol_args["query"],
        symbol_id=symbol_args["symbol_id"],
        qualified_name=symbol_args["qualified_name"],
        symbol_name=symbol_args["symbol_name"],
        file_path=symbol_args["file_path"],
        group_by="none",
        snippet_lines=0,
        limit=limit,
        budget_tokens=relation_budget,
        auto_index=False,
    )
    callers = engine.tool_callers(
        query=symbol_args["query"],
        symbol_id=symbol_args["symbol_id"],
        qualified_name=symbol_args["qualified_name"],
        symbol_name=symbol_args["symbol_name"],
        file_path=symbol_args["file_path"],
        depth=depth,
        limit=limit,
        budget_tokens=relation_budget,
        auto_index=False,
    )
    callees = engine.tool_callees(
        query=symbol_args["query"],
        symbol_id=symbol_args["symbol_id"],
        qualified_name=symbol_args["qualified_name"],
        symbol_name=symbol_args["symbol_name"],
        file_path=symbol_args["file_path"],
        depth=depth,
        limit=limit,
        budget_tokens=relation_budget,
        auto_index=False,
    )
    refs = _flatten_code_references(usages.get("references"))
    imports = [ref for ref in refs if "import" in str(ref.get("edge_kind") or "")]
    usage_refs = [ref for ref in refs if ref not in imports]
    payload: dict[str, Any] = {
        "target": target,
        "related": {
            "imports": imports,
            "usages": usage_refs,
            "callers": callers.get("related", []),
            "callees": callees.get("related", []),
        },
    }
    if view == "explain":
        payload["items"] = [
            _code_search_target_item(item) if isinstance(item, dict) else item
            for item in cast(list[Any], search_payload.get("items", []))
        ]
    return payload


# The published schema is intentionally slimmer than the handler signature: the
# handler still accepts intent/scope/since/touched_by/provenance and view=graph|explain
# (exercised by tests, the CLI, and power callers), but those axes duplicate the
# dedicated callers/callees/explore/usages/grep/blame tools, so they are not
# surfaced to LLM clients where they would cost schema tokens on every request.
SYMBOLS_TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {
            "type": "string",
            "description": "Identifier ('MyClass', 'module.Class.method') or natural-language description.",
        },
        "mode": {
            "type": "string",
            "enum": ["auto", "lexical", "semantic", "hybrid"],
            "default": "auto",
            "description": "Match strategy: lexical | semantic | hybrid; 'auto' chooses per query.",
        },
        "view": {
            "type": "string",
            "enum": ["target", "context"],
            "default": "target",
            "description": "'target': matching symbols only; 'context': a budgeted symbol+source context pack.",
        },
        "kind": {"type": "string", "description": "Filter: 'function', 'method', 'class', ..."},
        "language": {"type": "string"},
        "limit": {"type": "integer", "default": 20},
        "snippet": {"type": "string", "enum": ["none", "head", "full"], "default": "none"},
        "snippet_lines": {"type": "integer", "default": 8},
        "file_glob": {"type": "string", "description": "e.g. 'src/api/**/*.py'"},
        "repo_root": {"type": "string"},
        "scope": {
            "type": "string",
            "enum": ["repo", "external", "deleted"],
            "default": "repo",
            "description": "'external': dependencies; 'deleted': git graveyard.",
        },
        "since": {"type": "string", "description": "ISO date or relative ('7d')."},
        "format": _FORMAT_SCHEMA_PROPERTY,
    },
}


@mcp_tool(name="symbols", input_schema=SYMBOLS_TOOL_INPUT_SCHEMA)
def tool_symbols(
    query: str | None = None,
    mode: Literal["auto", "lexical", "semantic", "hybrid"] = "auto",
    intent: Literal["auto", "symbol", "text", "semantic"] = "auto",
    view: Literal["target", "graph", "context", "explain"] = "target",
    kind: str | None = None,
    language: str | None = None,
    snippet: Literal["none", "head", "full"] = "none",
    snippet_lines: int = 8,
    file_glob: str | None = None,
    scope: Literal["repo", "external", "deleted"] = "repo",
    since: str | None = None,
    touched_by: str | None = None,
    provenance: str | None = None,
    seed_files: list[str] | None = None,
    max_symbols: int = 4,
    depth: int = 1,
    limit: int = 20,
    budget_tokens: int = 4000,
    repo: str | None = None,
    repo_root: str | None = None,
    render_compact: bool = False,
    format: Annotated[str, _FORMAT_FIELD] = "auto",
) -> dict[str, Any]:
    """Search the SCIP code index for symbols by name or description.

    Prefer over `grep` for symbol lookup — results are exact (not textual), indexed, and token-budgeted.
    Use `grep` for regex on arbitrary text. Use `search` for ranked file/snippet retrieval.

    The `view` parameter controls response shape: `target` locates primary
    definitions/files, `graph` returns relationships for the best target,
    `context` returns a broader context pack, and `explain` combines targets
    with graph evidence.

    For call-graph, reference, and structural work use the dedicated tools:
    `node` (read a definition), `callers` / `callees` (call graph), `usages`
    (all references), `codemod` (AST search/rewrite), `explore` (grouped context).
    """
    return _op_search(
        query=query,
        mode=mode,
        intent=intent,
        view=view,
        kind=kind,
        language=language,
        snippet=snippet,
        snippet_lines=snippet_lines,
        file_glob=file_glob,
        scope=scope,
        since=since,
        touched_by=touched_by,
        provenance=provenance,
        seed_files=seed_files,
        max_symbols=max_symbols,
        depth=depth,
        limit=limit,
        budget_tokens=budget_tokens,
        repo=repo,
        repo_root=repo_root,
        render_compact=render_compact,
    )


# Result keys that represent batched discoveries — each item would have
# required its own naive grep/read in a side-by-side baseline.
_CODE_BATCH_KEYS: tuple[str, ...] = (
    "matches",
    "callers",
    "callees",
    "usages",
    "related",
    "edges",
    "references",
    "results",
    "items",
    "files",
    "symbols",
    "routes",
)


def _finish_code_result(result: dict[str, Any]) -> dict[str, Any]:
    # Infer calls_saved for batched ops: each list-of-items result represents
    # N findings that would have cost N naive calls (grep + read + scan).
    if isinstance(result, dict) and "calls_saved" not in result:
        for key in _CODE_BATCH_KEYS:
            items = result.get(key)
            if isinstance(items, list) and len(items) > 1:
                result["calls_saved"] = len(items) - 1
                break
    engine = getattr(_code_engine_for_current_call, "value", None)
    if engine is not None and isinstance(result, dict) and "index_status" not in result:
        try:
            if not engine.index_ready():
                result["index_status"] = "warming"
                result.setdefault(
                    "hint",
                    "code index is still building in the background; retry shortly for complete results",
                )
        except Exception:
            logging.exception("Recovered from broad exception handler")
    return result


def _code_engine_at(repo_root: str | None) -> Any:
    engine = _code_context_engine(repo_root or ".")
    _code_engine_for_current_call.value = engine
    return engine


_GRAPH_KINDS: frozenset[str] = frozenset(
    {
        "blast_radius",
        "dead_code",
        "cycles",
        "coupling",
        "centrality",
        # WS10 code health & history (G15/G16/N17): additive, read-only, fail-open.
        "design_gaps",
        "verify_design",
        "pr_risk",
        "commit_provenance",
        "index_docs",
        "recall_docs",
        # WS11 (G17): module-boundary / god-module topology discovery.
        "topology",
    }
)


def _synthesize_edges_for_paths(paths: list[str]) -> list[dict[str, Any]]:
    """Run the bounded N2/N3 edge synthesizer over *paths*; clearly-labelled output.

    Returns a flat list of heuristic edge dicts (provenance="heuristic"). Never
    touches the static call graph -- this is a separate, opt-in addendum.
    """
    from atelier.core.capabilities.code_context.edge_synthesis import synthesize_edges
    from atelier.infra.code_intel.languages import language_for_path

    out: list[dict[str, Any]] = []
    for raw in paths:
        candidate = Path(raw)
        if not candidate.is_file():
            continue
        lang = language_for_path(candidate)
        language = lang.name if lang is not None else ""
        source = candidate.read_text(encoding="utf-8", errors="replace")
        for edge in synthesize_edges(source, language=language):
            out.append({"file": str(candidate), **edge.to_dict()})
    return out


def _op_graph(
    *,
    kind: str = "blast_radius",
    path: str | None = None,
    paths: list[str] | None = None,
    limit: int = 50,
    synthesize: bool = False,
    query: str | None = None,
    enable: bool | None = None,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    """Agent-facing graph analytics (G3/G6) dispatched by ``kind``.

    * ``blast_radius`` (default) -- reverse-dependency closure + affected tests +
      risk tier for ``path`` (file-level; uses the existing change_impact).
    * ``dead_code`` / ``cycles`` / ``coupling`` -- repo-wide file-graph analytics
      over the semantic file index. Pass ``paths`` to fold those files into the
      index first; otherwise analyses whatever the index already holds.
    * ``centrality`` -- symbol-level call-graph centrality from the SCIP engine.
      Pass ``synthesize=true`` with ``paths`` to additionally return
      heuristic (route/event) edges as a SEPARATE ``synthesized_edges`` list
      (N2/N3); they are never merged into the static call graph.
    """
    if kind not in _GRAPH_KINDS:
        raise ValueError(f"unknown graph kind: {kind!r}; expected one of {sorted(_GRAPH_KINDS)}")

    # WS10 code health & history kinds (G15/G16/N17). Each is additive, read-only
    # analytics that fails open inside its own module; dispatched before the
    # file-graph kinds because they have distinct argument shapes.
    if kind in {"design_gaps", "verify_design", "pr_risk", "commit_provenance", "index_docs", "recall_docs"}:
        return _op_graph_code_health(
            kind=kind, path=path, paths=paths, limit=limit, query=query, enable=enable, repo_root=repo_root
        )

    if kind == "centrality":
        engine = _code_engine_at(repo_root)
        result = cast(dict[str, Any], engine.call_graph_centrality(limit=limit))
        result["kind"] = "centrality"
        if synthesize and paths:
            result["synthesized_edges"] = _synthesize_edges_for_paths(paths)
        return _finish_code_result(result)

    cap = SemanticFileMemoryCapability(_atelier_root())
    if paths:
        for raw in paths:
            candidate = Path(raw)
            if candidate.is_file():
                cap.summarize_file(candidate)
    analytics = cap.graph_analytics()
    if kind == "blast_radius":
        if not path:
            raise ValueError("path is required for kind='blast_radius'")
        result = analytics.blast_radius(str(Path(path)))
    elif kind == "dead_code":
        result = analytics.dead_code(limit=limit)
    elif kind == "cycles":
        result = analytics.cycles(limit=limit)
    elif kind == "topology":
        result = analytics.topology(limit=limit)
    else:  # coupling
        result = analytics.coupling(limit=limit)
    result["kind"] = kind
    _ = render_compact  # file-graph analytics render as JSON; no markdown view
    return result


def _op_graph_code_health(
    *,
    kind: str,
    path: str | None,
    paths: list[str] | None,
    limit: int,
    query: str | None,
    enable: bool | None,
    repo_root: str | None,
) -> dict[str, Any]:
    """Dispatch the WS10 code health & history graph kinds (G15/G16/N17).

    Each delegated function is independently fail-open; this seam only resolves
    the repo/atelier roots and routes by ``kind``.
    """
    from atelier.core.capabilities.code_health import (
        commit_provenance,
        design_gaps,
        index_design_docs,
        pr_risk,
        recall_design_docs,
        verify_design,
    )

    workspace = _workspace_root()
    repo = (Path(repo_root) if repo_root else workspace).resolve()
    atelier_root = _atelier_root()

    if kind == "design_gaps":
        return design_gaps(repo_root=repo, atelier_root=atelier_root, paths=paths)
    if kind == "verify_design":
        return verify_design(repo_root=repo, atelier_root=atelier_root, paths=paths)
    if kind == "pr_risk":
        targets = paths or ([path] if path else [])
        if not targets:
            raise ValueError("pr_risk requires 'paths' (or 'path') -- the changed files")
        return pr_risk(repo_root=repo, atelier_root=atelier_root, paths=targets)
    if kind == "commit_provenance":
        return commit_provenance(repo_root=repo, path=path, limit=limit)
    if kind == "index_docs":
        return index_design_docs(repo_root=repo, atelier_root=atelier_root, paths=paths, enable=enable)
    # recall_docs
    if not query:
        raise ValueError("recall_docs requires 'query'")
    return recall_design_docs(atelier_root=atelier_root, query=query, limit=limit)


def _op_callers(
    *,
    query: str | None = None,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    kind: str | None = None,
    language: str | None = None,
    depth: int = 1,
    limit: int = 20,
    snapshot: bool = False,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    if not any([query, symbol_id, qualified_name, symbol_name]):
        raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code callers")
    engine = _code_engine_at(repo_root)
    payload = cast(
        dict[str, Any],
        engine.tool_callers(
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=path,
            kind=kind,
            language=language,
            depth=depth,
            limit=limit,
            snapshot=snapshot,
            budget_tokens=budget_tokens,
        ),
    )
    return _finish_code_result(_maybe_attach_code_rendered("callers", payload, render_compact=render_compact))


def _op_callees(
    *,
    query: str | None = None,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    kind: str | None = None,
    language: str | None = None,
    depth: int = 1,
    limit: int = 20,
    snapshot: bool = False,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    if not any([query, symbol_id, qualified_name, symbol_name]):
        raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code callees")
    engine = _code_engine_at(repo_root)
    payload = cast(
        dict[str, Any],
        engine.tool_callees(
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=path,
            kind=kind,
            language=language,
            depth=depth,
            limit=limit,
            snapshot=snapshot,
            budget_tokens=budget_tokens,
        ),
    )
    return _finish_code_result(_maybe_attach_code_rendered("callees", payload, render_compact=render_compact))


def _op_usages(
    *,
    query: str | None = None,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    kind: str | None = None,
    language: str | None = None,
    file_glob: str | None = None,
    group_by: str = "file",
    snippet_lines: int = 8,
    limit: int = 20,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    if not any([query, symbol_id, qualified_name, symbol_name]):
        raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code usages")
    engine = _code_engine_at(repo_root)
    payload = cast(
        dict[str, Any],
        engine.tool_usages(
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=path,
            kind=kind,
            language=language,
            file_glob=file_glob,
            group_by=group_by,
            snippet_lines=3 if snippet_lines == 8 else snippet_lines,
            limit=limit,
            budget_tokens=budget_tokens,
        ),
    )
    return _finish_code_result(_maybe_attach_code_rendered("usages", payload, render_compact=render_compact))


def _op_explore(
    *,
    query: str | None = None,
    seed_files: list[str] | None = None,
    max_files: int = 8,
    max_symbols: int = 4,
    include_source: bool = True,
    include_relationships: bool = True,
    line_numbers: bool = True,
    depth: int = 1,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    if not query:
        raise ValueError("query is required for code explore")
    engine = _code_engine_at(repo_root)
    payload = cast(
        dict[str, Any],
        engine.tool_explore(
            query=query,
            seed_files=seed_files,
            max_files=max_files,
            max_symbols=max_symbols,
            include_source=include_source,
            include_relationships=include_relationships,
            line_numbers=line_numbers,
            depth=depth,
            budget_tokens=budget_tokens,
        ),
    )
    return _finish_code_result(_maybe_attach_code_rendered("explore", payload, render_compact=render_compact))


def _op_pattern(
    *,
    pattern: str | None = None,
    rewrite: str | None = None,
    language: str | None = None,
    file_glob: str | None = None,
    dry_run: bool = True,
    limit: int = 20,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    if not pattern:
        raise ValueError("pattern is required for code pattern")
    engine = _code_engine_at(repo_root)
    payload = cast(
        dict[str, Any],
        engine.tool_pattern(
            pattern=pattern,
            rewrite=rewrite,
            language=language,
            file_glob=file_glob,
            dry_run=dry_run,
            limit=limit,
            budget_tokens=budget_tokens,
        ),
    )
    return _finish_code_result(_maybe_attach_code_rendered("pattern", payload, render_compact=render_compact))


def _op_search(
    *,
    query: str | None = None,
    mode: str = "auto",
    intent: str = "auto",
    view: Literal["target", "graph", "context", "explain"] = "target",
    kind: str | None = None,
    language: str | None = None,
    snippet: str = "none",
    snippet_lines: int = 8,
    file_glob: str | None = None,
    scope: str = "repo",
    since: str | None = None,
    touched_by: str | None = None,
    provenance: str | None = None,
    seed_files: list[str] | None = None,
    max_symbols: int = 4,
    depth: int = 1,
    limit: int = 20,
    budget_tokens: int = 4000,
    repo: str | None = None,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    if not query:
        raise ValueError("query is required for code search")
    engine_root = repo_root or "."
    workspace_router = _workspace_code_router(engine_root)
    if repo is not None and not workspace_router.is_configured:
        raise ValueError("repo filter requires .atelier/workspace.toml")
    engine = _code_context_engine(engine_root)
    _code_engine_for_current_call.value = engine
    if workspace_router.is_configured and view in {"graph", "explain", "context"}:
        # The workspace-routed search path only produces a target-shaped payload;
        # graph/explain/context are not routed. Reject explicitly so callers get a
        # clear error instead of a silently-wrong (unrouted, repo-ignoring) result.
        raise ValueError(
            f"view={view!r} is not supported when a workspace is configured (.atelier/workspace.toml); "
            "use view='target' for routed search"
        )
    if view == "context":
        context_payload = engine.tool_context(
            task=query,
            seed_files=seed_files,
            budget_tokens=budget_tokens,
            max_symbols=max_symbols,
        )
        return _finish_code_result(
            _maybe_attach_code_rendered("context", cast(dict[str, Any], context_payload), render_compact=render_compact)
        )
    search_kwargs: dict[str, Any] = {
        "limit": limit,
        "mode": mode,
        "kind": kind,
        "language": language,
        "snippet": snippet,
        "snippet_lines": snippet_lines,
        "file_glob": file_glob,
        "scope": scope,
        "budget_tokens": budget_tokens,
    }
    if scope != "deleted":
        search_kwargs["intent"] = intent
        search_kwargs["seed_files"] = seed_files
    if since is not None:
        search_kwargs["since"] = since
    if touched_by is not None:
        search_kwargs["touched_by"] = touched_by
    if provenance is not None:
        search_kwargs["provenance_filter"] = provenance
    if workspace_router.is_configured:
        routed_payload = cast(
            dict[str, Any],
            workspace_router.route("search", repo=repo, query=query, **search_kwargs),
        )
        routed_payload = _code_search_target_view(routed_payload)
        return _finish_code_result(_maybe_attach_code_rendered("search", routed_payload, render_compact=render_compact))
    search_payload = cast(dict[str, Any], engine.tool_search(query, **search_kwargs))
    if view == "target":
        search_payload = _code_search_target_view(search_payload)
    elif view in {"graph", "explain"}:
        search_payload = _code_search_graph_view(
            engine,
            query=query,
            search_payload=search_payload,
            view=view,
            limit=limit,
            depth=depth,
            budget_tokens=budget_tokens,
        )
    return _finish_code_result(_maybe_attach_code_rendered("search", search_payload, render_compact=render_compact))


def _op_index(
    *,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    force: bool = False,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    engine = _code_engine_at(repo_root)
    payload = cast(
        dict[str, Any],
        engine.tool_index(
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            force=force,
            budget_tokens=budget_tokens,
        ),
    )
    return _finish_code_result(_maybe_attach_code_rendered("index", payload, render_compact=render_compact))


def _op_blame(
    *,
    query: str | None = None,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    include_churn: bool = True,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    if not (query or symbol_id or qualified_name or symbol_name):
        raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code blame")
    engine = _code_engine_at(repo_root)
    payload = cast(
        dict[str, Any],
        engine.tool_blame(
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=path,
            include_churn=include_churn,
            budget_tokens=budget_tokens,
        ),
    )
    return _finish_code_result(_maybe_attach_code_rendered("blame", payload, render_compact=render_compact))


def _op_node(
    *,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    line: int | None = None,
    budget_tokens: int = 4000,
    repo: str | None = None,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    engine_root = repo_root or "."
    workspace_router = _workspace_code_router(engine_root)
    if repo is not None and not workspace_router.is_configured:
        raise ValueError("repo filter requires .atelier/workspace.toml")
    engine = _code_context_engine(engine_root)
    _code_engine_for_current_call.value = engine
    if workspace_router.is_configured:
        payload = cast(
            dict[str, Any],
            workspace_router.route(
                "symbol",
                repo=repo,
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                symbol_name=symbol_name,
                file_path=path,
                line=line,
                budget_tokens=budget_tokens,
            ),
        )
    else:
        payload = cast(
            dict[str, Any],
            engine.tool_symbol(
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                symbol_name=symbol_name,
                file_path=path,
                line=line,
                budget_tokens=budget_tokens,
            ),
        )
    return _finish_code_result(_maybe_attach_code_rendered("symbol", payload, render_compact=render_compact))


def _op_rename(
    *,
    new_name: str | None = None,
    query: str | None = None,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    rename_backend: str = "auto",
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    if not new_name:
        raise ValueError("new_name is required for code rename")
    if not any([query, symbol_id, qualified_name, symbol_name]):
        raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code rename")
    engine = _code_engine_at(repo_root)
    from atelier.core.capabilities.tool_supervision.rename_symbol import build_rename_edits

    # Single root: the engine resolves/indexes against _workspace_root() (NOT cwd), so edits must be
    # built and applied under the SAME root — otherwise a cross-repo rename hits
    # the wrong working tree.
    root = Path(engine.repo_root)
    edits = build_rename_edits(
        engine,
        symbol_id=symbol_id,
        qualified_name=qualified_name,
        symbol_name=symbol_name or query,
        file_path=path,
        new_name=new_name,
        repo_root=root,
        backend=rename_backend,
    )
    if not edits:
        raise ValueError(f"no occurrences renamed: symbol not found or no references for new_name {new_name!r}")
    truncated = bool(getattr(edits, "truncated", False))
    total_references = int(getattr(edits, "total_references", 0))
    # A truncated edit set covers only the first _RENAME_USAGE_LIMIT (500) sites,
    # so applying it would rewrite some references and leave the rest dangling --
    # silent symbol corruption. Refuse rather than apply a partial rename.
    if truncated:
        return _finish_code_result(
            _maybe_attach_code_rendered(
                "rename",
                {
                    "op": "rename",
                    "new_name": new_name,
                    "backend": rename_backend,
                    "failed": [
                        {
                            "error": (
                                f"rename aborted: symbol has {total_references} references, exceeding the "
                                "500-site cap. The naive backend would rewrite only the first 500 and leave the "
                                "rest dangling, corrupting the symbol. Use a semantic backend (rope/ts-morph) or "
                                "reduce scope."
                            ),
                        }
                    ],
                    "truncated": True,
                    "total_references": total_references,
                },
                render_compact=render_compact,
            )
        )
    from atelier.core.capabilities.tool_supervision.rich_edit import apply_rich_edits

    touched = _collect_touched_paths(edits, repo_root=root)
    snaps = _snapshot_paths(touched)
    result = apply_rich_edits(edits, atomic=True, repo_root=root)
    if not result.get("failed") and not result.get("rolled_back"):
        _compute_and_record_diffs(snaps)
    result["op"] = "rename"
    result["new_name"] = new_name
    result["backend"] = rename_backend
    result["truncated"] = truncated
    result["total_references"] = total_references
    return _finish_code_result(_maybe_attach_code_rendered("rename", result, render_compact=render_compact))


def _op_cache_status(
    *,
    cache_tool: str | None = None,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    engine = _code_engine_at(repo_root)
    if cache_tool is None:
        payload = cast(dict[str, Any], engine.tool_cache_status(budget_tokens=budget_tokens))
    else:
        payload = cast(
            dict[str, Any],
            engine.tool_cache_status(cache_tool=cache_tool, budget_tokens=budget_tokens),
        )
    return _finish_code_result(_maybe_attach_code_rendered("cache_status", payload, render_compact=render_compact))


def _op_cache_invalidate(
    *,
    cache_tool: str | None = None,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    engine = _code_engine_at(repo_root)
    if cache_tool is None:
        payload = cast(dict[str, Any], engine.tool_cache_invalidate(budget_tokens=budget_tokens))
    else:
        payload = cast(
            dict[str, Any],
            engine.tool_cache_invalidate(cache_tool=cache_tool, budget_tokens=budget_tokens),
        )
    return _finish_code_result(_maybe_attach_code_rendered("cache_invalidate", payload, render_compact=render_compact))


# ------------------------------------------------------------------ #
# Dedicated code-intel tools — each calls its `_op_*` engine wrapper  #
# directly (no multiplexer). Published tools carry focused schemas;   #
# repo/admin ops (index, blame, rename, cache_status, cache_invalidate)    #
# are registered hidden via HIDDEN_LLM_TOOLS so tests and power use reach   #
# them by name.                                                            #
# ------------------------------------------------------------------ #

# Code-intel tool names whose pre-rendered text (set during the _op_* call) is
# surfaced verbatim by render_tool_result_text. Includes the hidden repo/admin
# ops so `_call("index"/...)` returns rendered text for tests/power use.
_CODE_INTEL_TOOLS: frozenset[str] = frozenset(
    {
        "node",
        "callers",
        "callees",
        "explore",
        "usages",
        "codemod",
        "index",
        "blame",
        "rename",
        "cache_status",
        "cache_invalidate",
    }
)


def _parse_symbol(symbol: str) -> dict[str, Any]:
    """Route a symbol string to the correct engine kwarg based on form."""
    if symbol.startswith("scip-"):
        return {"symbol_id": symbol}
    if "." in symbol:
        return {"qualified_name": symbol}
    return {"symbol_name": symbol}


@mcp_tool(name="node")
def tool_node(
    symbol: str | None = None,
    path: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    """Get the full source definition of a symbol (function, class, method, variable).

    Prefer over `read` — returns just the symbol, not the whole file.
    Returns: signature, docstring, body, file location, and a stable symbol_id for follow-up calls.

    Pass symbol as unqualified name ('run_command'), qualified path ('module.Class.method'),
    or SCIP id (from a prior search/callers result). Or use path+line for positional lookup —
    the line may be passed separately or as a "path#line" suffix (e.g. "store.py#100").
    """
    if path is not None:
        path, suffix_range = _split_read_range_suffix(path)
        if suffix_range is not None and line is None:
            match = re.match(r"L?(\d+)", suffix_range)
            if match is not None:
                line = int(match.group(1))
    target = _parse_symbol(symbol) if symbol else {}
    return _op_node(**target, path=path, line=line)


@mcp_tool(name="callers")
def tool_callers(
    symbol: str,
    depth: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Find all callers of a function — inbound call graph edges (who calls this?).

    Prefer over grep when tracing where a function is invoked from.
    Returns caller names, file paths, and line numbers grouped by file.
    depth=1: direct callers; depth=2: transitive callers.
    """
    return _op_callers(**_parse_symbol(symbol), depth=depth, limit=limit)


@mcp_tool(name="callees")
def tool_callees(
    symbol: str,
    depth: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Find all functions called by a symbol — outbound call graph edges (what does this call?).

    Use before editing to understand a function's dependencies.
    Returns callee names, file paths, and call sites grouped by file.
    depth=1: direct callees; depth=2: transitive callees.
    """
    return _op_callees(**_parse_symbol(symbol), depth=depth, limit=limit)


@mcp_tool(name="explore")
def tool_explore(
    query: str,
    seed_files: list[str] | None = None,
    max_files: int = 8,
) -> dict[str, Any]:
    """One-call grouped source + call-graph context for a concept or query.

    Replaces chaining code search → node → callers/callees for multi-file understanding.
    Returns: symbol definitions, source, and caller/callee summaries in one call.
    Use seed_files to bias search toward specific files.
    """
    return _op_explore(query=query, seed_files=seed_files, max_files=max_files)


@mcp_tool(name="usages")
def tool_usages(
    symbol: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Find all references/usages of a symbol across the codebase.

    Prefer over `grep` for "where is this used" — results are SCIP-indexed and
    exact (not textual), so renames, shadowed names, and comments don't create
    false hits. Use `callers` instead when you only want call sites of a function.
    Pass an unqualified name ('run_command'), qualified path ('module.Class.method'),
    or a SCIP id from a prior result.
    Returns: references grouped by file with line numbers and matched snippets.
    """
    return _op_usages(**_parse_symbol(symbol), limit=limit)


@mcp_tool(name="graph")
def tool_graph(
    kind: str = "blast_radius",
    path: str | None = None,
    paths: list[str] | None = None,
    limit: int = 50,
    synthesize: bool = False,
    query: str | None = None,
    enable: bool | None = None,
) -> dict[str, Any]:
    """Repo graph analytics + code health & history: blast radius, dead code, cycles,
    coupling, centrality, doc/code drift, PR risk, commit provenance, design-doc recall.

    kind:
      - blast_radius (default): reverse-dependency closure + affected tests + risk tier for `path`.
      - dead_code: indexed files with no inbound importers (likely removable), ranked by complexity.
      - cycles: import dependency cycles (strongly-connected components, size >= 2).
      - coupling: per-file afferent/efferent coupling + Martin's instability metric.
      - centrality: most important symbols by call-graph centrality (degree + eigenvector).
      - design_gaps (G15): doc-referenced symbols absent from the index (stale/aspirational refs).
      - verify_design (G15): doc-referenced symbols whose signature drifted from the index.
      - pr_risk (G16): fuse blast-radius + complexity + churn + test-gap into a 0..1 risk score
        and tier for the changed `paths` (or `path`).
      - commit_provenance (G16): heuristic bugfix/refactor/feature/perf/rename/revert/docs/test
        classification of commits touching `path` (or the repo), with tagged confidence.
      - index_docs (N17): opt-in heading-tree indexing of Markdown design docs into a SEPARATE
        retrieval store (pass `enable=true`, or set ATELIER_DOC_INDEXING=1; off by default).
      - recall_docs (N17): recall design-doc chunks for `query` from the separate doc store.
    Pass `paths` to fold specific files into the index first (dead_code/cycles/coupling/pr_risk);
    for design_gaps/verify_design/index_docs `paths` selects the docs/dirs to scan.
    `synthesize=true` (with `paths`, kind=centrality) also returns heuristic route/event
    edges as a SEPARATE `synthesized_edges` list (never merged into the static call graph).
    """
    return _op_graph(
        kind=kind,
        path=path,
        paths=paths,
        limit=limit,
        synthesize=synthesize,
        query=query,
        enable=enable,
    )


@mcp_tool(name="codemod")
def tool_pattern(
    pattern: str,
    language: str | None = None,
    file_glob: str | None = None,
    rewrite: str | None = None,
    limit: int = 20,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Structural code search and safe rewrite (codemod) by AST shape, via ast-grep.

    Use over `grep` when matching code *shape*, not text: it is formatting-
    independent and never matches inside strings or comments. Metavariables:
    `$X` binds one node, `$$$` binds a list -- e.g. `isinstance($X, $Y)`,
    `$X == None`, `requests.get($URL)`.

    Pass `rewrite` to transform every match (the codemod); captured metavariables
    are reusable in the replacement, e.g. pattern `$X == None`, rewrite `$X is None`.
    `dry_run=True` (default) returns a unified-diff preview and writes nothing;
    `dry_run=False` applies the rewrite across all matched files. Scope with
    `language` (e.g. 'python') and `file_glob`.
    Returns: matches (snippet, file_path, line); with `rewrite`, a diff and `files_changed`.
    """
    return _op_pattern(
        pattern=pattern,
        rewrite=rewrite,
        language=language,
        file_glob=file_glob,
        dry_run=dry_run,
        limit=limit,
    )


# Repo/admin code-intel ops — registered hidden (see HIDDEN_LLM_TOOLS). Not
# surfaced to agents; reachable by name for tests, the CLI, and power use. Each
# delegates straight to its _op_* engine wrapper.
@mcp_tool(name="index")
def tool_index(
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    force: bool = False,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    """Build or refresh the SCIP code index for the repo (internal/admin)."""
    return _op_index(
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        force=force,
        budget_tokens=budget_tokens,
        repo_root=repo_root,
        render_compact=render_compact,
    )


@mcp_tool(name="blame")
def tool_blame(
    query: str | None = None,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    include_churn: bool = True,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    """Git blame / churn summary for a symbol or file (internal/admin)."""
    return _op_blame(
        query=query,
        symbol_id=symbol_id,
        qualified_name=qualified_name,
        symbol_name=symbol_name,
        path=path,
        include_churn=include_churn,
        budget_tokens=budget_tokens,
        repo_root=repo_root,
        render_compact=render_compact,
    )


@mcp_tool(name="rename")
def tool_rename(
    new_name: str | None = None,
    query: str | None = None,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    rename_backend: str = "auto",
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    """Rename a symbol across the repo via SCIP/ast-grep edits (internal/admin)."""
    return _op_rename(
        new_name=new_name,
        query=query,
        symbol_id=symbol_id,
        qualified_name=qualified_name,
        symbol_name=symbol_name,
        path=path,
        rename_backend=rename_backend,
        budget_tokens=budget_tokens,
        repo_root=repo_root,
        render_compact=render_compact,
    )


@mcp_tool(name="cache_status")
def tool_cache_status(
    cache_tool: str | None = None,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    """Report code-intel cache hit/miss counters (internal/admin)."""
    return _op_cache_status(
        cache_tool=cache_tool,
        budget_tokens=budget_tokens,
        repo_root=repo_root,
        render_compact=render_compact,
    )


@mcp_tool(name="cache_invalidate")
def tool_cache_invalidate(
    cache_tool: str | None = None,
    budget_tokens: int = 4000,
    repo_root: str | None = None,
    render_compact: bool = False,
) -> dict[str, Any]:
    """Invalidate code-intel caches (internal/admin)."""
    return _op_cache_invalidate(
        cache_tool=cache_tool,
        budget_tokens=budget_tokens,
        repo_root=repo_root,
        render_compact=render_compact,
    )


@mcp_tool(name="scan")
def tool_scan(
    path: str | None = None,
    include_taint: bool = True,
    include_rules: bool = True,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Security scan (SAST, first iteration) over the repo or a sub-path.

    Runs a small bundled pack of high-signal OWASP/CWE ast-grep rules
    (eval/exec, subprocess shell=True with interpolation, SQL string
    concatenation, hardcoded secrets) plus a BOUNDED intra-procedural Python
    taint check (request/argv/env/input sources reaching exec/subprocess/SQL
    sinks). Scope to a file or directory with `path`; toggle the rule pack or
    taint pass with `include_rules`/`include_taint`.

    This is a first iteration, NOT a full SAST engine: every finding carries a
    `rule_id`, `severity`, and `confidence`, and heuristic findings are flagged
    (`heuristic: true`). It does not claim exhaustiveness.
    Returns: findings (path, line, rule_id, cwe, severity, confidence, message,
    source, heuristic) and a summary count.
    """
    from atelier.core.capabilities.security import scan_repository

    workspace = _workspace_root()
    root_arg = repo_root or "."
    root_path = Path(root_arg)
    resolved_root = (root_path if root_path.is_absolute() else workspace / root_path).resolve()
    paths = [path] if path else None
    findings = scan_repository(
        resolved_root,
        paths=paths,
        include_taint=include_taint,
        include_rules=include_rules,
    )
    severity_counts: dict[str, int] = {}
    for finding in findings:
        sev = str(finding.get("severity", "info"))
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    return {
        "findings": findings,
        "summary": {
            "total": len(findings),
            "by_severity": severity_counts,
            "heuristic": True,
            "note": "First-iteration SAST: bounded coverage, not exhaustive.",
        },
    }


@mcp_tool(name="orient")
def tool_orient(topic: str | None = None) -> dict[str, Any]:
    """Return Atelier's tool-usage playbook on demand (N8).

    One fetch for the optimal tool sequencing -- explore -> navigate -> edit ->
    verify -- and which tool to reach for in each phase, so this guidance need
    not be duplicated in every system prompt. Static and deterministic.

    Pass an optional `topic` (explore, navigate, edit, verify, selection) for a
    single focused section instead of the whole playbook. An unknown topic is
    not an error: it returns the overview plus the list of valid topics.
    Returns: sequence, sections (title/body), topics, and rendered `text`.
    """
    from atelier.core.capabilities.orientation import orientation_playbook

    return orientation_playbook(topic)


def _run_shell_tool(
    command: str = "",
    timeout: int = 30,
    cwd: str | None = None,
    max_lines: int = 200,
    background: bool = False,
    session_id: str | None = None,
    action: Literal["run", "poll", "cancel"] = "run",
) -> dict[str, Any]:
    """Execute a shell command and return compact structured output."""
    from atelier.core.capabilities.tool_supervision.bash_exec import (
        classify_command,
        poll_managed_command,
        start_managed_command,
    )

    def _render_grep_stdout(payload: dict[str, Any]) -> str:
        blocks = payload.get("content", [])
        if isinstance(blocks, list):
            texts: list[str] = []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        texts.append(text)
            if texts:
                normalized: list[str] = []
                for line in "\n".join(texts).splitlines():
                    if line.startswith("@@ "):
                        continue
                    normalized.append(line)
                return "\n".join(normalized)
        matches = payload.get("matches")
        if isinstance(matches, list):
            return json.dumps(matches, ensure_ascii=False)
        return json.dumps(payload, ensure_ascii=False)

    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    effective_cwd = cwd or workspace

    if action in {"poll", "cancel"}:
        if not session_id:
            raise ValueError(f"session_id is required for shell action={action}")
        if action == "cancel":
            return poll_managed_command(session_id, cancel=True)
        # Block until the backgrounded command finishes (or its own timeout
        # kills it). No artificial window -- the command's timeout is the bound.
        delay = 0.02
        while True:
            poll_result = poll_managed_command(session_id)
            if poll_result.get("status") != "running":
                return poll_result
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
    if not command.strip():
        raise ValueError("command is required for shell action=run")

    policy = classify_command(command)

    if policy.action == "rewrite" and policy.rewrite_target == "read" and policy.rewrite_payload:
        raw_file_path = str(policy.rewrite_payload.get("file_path") or "").strip()
        if raw_file_path:
            target_path = Path(raw_file_path)
            if not target_path.is_absolute():
                target_path = (Path(effective_cwd) / target_path).resolve()
            read_handler: Callable[[dict[str, Any]], Any] = TOOLS["read"]["handler"]
            rewritten = cast(dict[str, Any], read_handler({"path": str(target_path), "expand": True}))
            rewritten_stdout = str(rewritten.get("content") or "")
            return {
                "stdout": rewritten_stdout,
                "stderr": "",
                "exit_code": 0,
                "truncated": False,
                "lines_omitted": 0,
                "duration_ms": 0,
            }

    if policy.action == "rewrite" and policy.rewrite_target == "grep" and policy.rewrite_payload:
        raw_search_path = str(policy.rewrite_payload.get("file_path") or ".")
        content_regex = cast(str | None, policy.rewrite_payload.get("content_regex"))
        ignore_case = bool(policy.rewrite_payload.get("ignore_case", False))
        file_type = cast(str | None, policy.rewrite_payload.get("type"))

        resolved_search_path = Path(raw_search_path)
        if not resolved_search_path.is_absolute():
            resolved_search_path = (Path(effective_cwd) / resolved_search_path).resolve()
        glob_patterns = ["**/*"] if resolved_search_path.is_dir() else None
        grep_args: dict[str, Any] = {
            "path": raw_search_path,
            "content_regex": content_regex,
            "file_glob_patterns": glob_patterns,
            "ignore_case": ignore_case,
            "summary": False,
            "output_mode": cast(
                Literal[
                    "ranked_file_map",
                    "file_paths_with_content",
                    "file_paths_only",
                    "file_paths_with_match_count",
                ],
                policy.rewrite_payload.get("output_mode", "file_paths_with_content"),
            ),
        }
        if file_type:
            grep_args["type"] = file_type
        grep_handler: Callable[[dict[str, Any]], Any] = TOOLS["grep"]["handler"]
        rewritten = cast(dict[str, Any], grep_handler(grep_args))
        rewritten_stdout = _render_grep_stdout(rewritten)
        return {
            "stdout": rewritten_stdout,
            "stderr": "",
            "exit_code": 0,
            "truncated": False,
            "lines_omitted": 0,
            "duration_ms": 0,
        }

    # One execution model: every command runs as a managed session; the only
    # variable is how long we block inline before returning a poll handle.
    #   background → 0s (detach immediately, poll/cancel by session)
    #   default    → full timeout (block until the command finishes or is killed)
    inline_wait = 0.0 if background else float(timeout)

    started = start_managed_command(
        command,
        cwd=effective_cwd,
        timeout=timeout,
        max_lines=max_lines,
    )
    managed_id = str(started.get("session_id") or "")
    if started.get("status") != "running" or not managed_id:
        return started  # blocked by policy

    # When the inline wait covers the full timeout budget, the watcher kills
    # the command at that deadline; allow a short grace so we return the
    # reaped terminal result (timed_out) instead of a handle to a dying run.
    if inline_wait >= float(timeout):
        inline_wait = float(timeout) + 10.0
    deadline = time.monotonic() + inline_wait
    delay = 0.02
    polled: dict[str, Any] = started
    while True:
        polled = poll_managed_command(managed_id)
        if polled.get("status") != "running":
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return polled  # still running at the window edge — poll later
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, 0.5)

    # Finished inline: present as a plain synchronous result. The managed
    # session is already reaped, so status/session_id would only invite a
    # useless poll turn; exit_code/stderr carry the terminal state.
    polled.pop("session_id", None)
    polled.pop("status", None)
    chars_omitted = int(polled.pop("chars_omitted", 0) or 0)
    if chars_omitted > 0:
        # chars_omitted / 4 is the standard chars-per-token estimate.
        _tool_call_tokens_saved.value = chars_omitted // 4
    return polled


def _fmt_duration_ms(ms: int) -> str:
    """Render a millisecond span as a compact human duration (e.g. 95s, 29m25s)."""
    secs = max(0, ms) // 1000
    if secs < 60:
        return f"{secs}s"
    minutes, seconds = divmod(secs, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _render_shell_text(result: dict[str, Any]) -> str:
    """Render shell output as compact text while preserving structured internals."""
    exit_code = result.get("exit_code")
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    blocked = bool(result.get("blocked"))
    blocked_reason = str(result.get("blocked_reason") or "")
    truncated = bool(result.get("truncated"))
    lines_omitted = result.get("lines_omitted")
    status = str(result.get("status") or "")
    session_id = str(result.get("session_id") or "")

    parts: list[str] = []
    if status == "running":
        parts.append(f"status=running session_id={session_id}")
        if result.get("pid") is not None:
            parts.append(f"pid={result['pid']}")
        meta: list[str] = []
        duration_ms = result.get("duration_ms")
        if isinstance(duration_ms, int):
            meta.append(f"elapsed={_fmt_duration_ms(duration_ms)}")
        timeout_remaining_ms = result.get("timeout_remaining_ms")
        if isinstance(timeout_remaining_ms, int):
            meta.append(f"timeout_in={_fmt_duration_ms(timeout_remaining_ms)}")
        if meta:
            parts.append(" ".join(meta))
    elif status:
        parts.append(f"status={status} session_id={session_id}")
    if blocked:
        header = "blocked"
        if exit_code is not None:
            header = f"{header} (exit_code={exit_code})"
        parts.append(header)
        if blocked_reason:
            parts.append(blocked_reason)
    elif exit_code not in (None, 0):
        parts.append(f"exit_code={exit_code}")

    if stdout:
        parts.append(stdout)
    if stderr:
        if stdout:
            parts.append("")
        if exit_code in (None, 0) and not blocked:
            parts.append("stderr:")
        parts.append(stderr)
    if truncated and isinstance(lines_omitted, int) and lines_omitted > 0:
        if stdout or stderr:
            parts.append("")
        parts.append(f"[output truncated: {lines_omitted} lines omitted]")
    # No exit-code guard: pipelines (e.g. `... 2>&1 | tail`) mask failures.
    if "No module named pip" in stdout or "No module named pip" in stderr:
        parts.append(
            "[hint] This venv has no pip (uv-managed). Install with: "
            "uv pip install --python <venv>/bin/python <pkg>  (or python -m ensurepip first)"
        )
    discipline = str(result.get("discipline") or "")
    if discipline:
        if parts:
            parts.append("")
        parts.append(f"[discipline] {discipline}")

    rendered = "\n".join(parts).strip()
    if rendered:
        return rendered
    if exit_code is not None:
        return f"exit_code={exit_code}"
    return ""


def _run_native_grep(
    *,
    path: str,
    content_regex: str | None,
    file_glob_patterns: list[str] | None,
    output_mode: Literal[
        "ranked_file_map",
        "file_paths_with_content",
        "file_paths_only",
        "file_paths_with_match_count",
    ],
    lines_before: int,
    lines_after: int,
    ignore_case: bool,
    type: str | None,
    file_limit: int | None,
    lines_per_file: int | None,
    if_modified_since: str | None,
    multiline: bool,
    summary: bool | None,
    context_budget_tokens: int,
    include_meta: bool,
) -> dict[str, Any]:
    from atelier.core.capabilities.tool_supervision.native_search import search_workspace

    return search_workspace(
        path=path,
        content_regex=content_regex,
        file_glob_patterns=file_glob_patterns,
        output_mode=output_mode,
        lines_before=lines_before,
        lines_after=lines_after,
        ignore_case=ignore_case,
        type=type,
        file_limit=file_limit,
        lines_per_file=lines_per_file,
        if_modified_since=if_modified_since,
        max_line_length=1000,
        multiline=multiline,
        summary=summary,
        context_budget_tokens=context_budget_tokens,
        include_metadata=include_meta,
        repo_root=os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd()),
    )


@mcp_tool(
    name="grep",
    description=(
        "Search files with regex, glob, and type filters. Use this instead of `search` for "
        "grep-style matching, path listing, context lines, summaries, or incremental reruns.\n"
        "Maximise work per call: pass every glob/path you need at once (file_glob_patterns) and "
        "combine content_regex + type to narrow by scope and content in one call instead of "
        "chaining narrow calls — tool-side filtering is cheaper than another round-trip. When "
        "you'll need the matched code, set output_mode='file_paths_with_content' to discover AND "
        "read matched context in one step rather than grep-then-read. Run independent searches in "
        "parallel within one response. Pass a prior result's timestamp back as if_modified_since "
        "to skip files unchanged since then."
    ),
    hidden_params=("include_meta",),
)
def tool_grep(
    path: Annotated[
        str,
        Field(
            description=(
                "Workspace-relative file or directory to search. A single file may carry a "
                "'#start-end' suffix (e.g. 'store.py#60-100') to scope matches to that line range."
            ),
        ),
    ] = ".",
    content_regex: Annotated[
        str | None,
        Field(description="Regex to match file contents. Omit for pure path/type listings."),
    ] = None,
    file_glob_patterns: Annotated[
        list[str] | None,
        Field(description="Globs constraining candidate files, e.g. `src/**/*.py`."),
    ] = None,
    output_mode: Annotated[
        Literal[
            "ranked_file_map",
            "file_paths_with_content",
            "file_paths_only",
            "file_paths_with_match_count",
        ],
        Field(
            description=(
                "`ranked_file_map` (default): ranked navigation pointers. "
                "`file_paths_with_content`: matched lines with context. "
                "`file_paths_only`: just paths. "
                "`file_paths_with_match_count`: paths with hit counts."
            )
        ),
    ] = "ranked_file_map",
    lines_before: Annotated[
        int,
        Field(description="Context lines before each match."),
    ] = 0,
    lines_after: Annotated[
        int,
        Field(description="Context lines after each match."),
    ] = 0,
    ignore_case: Annotated[
        bool,
        Field(description="Case-insensitive matching."),
    ] = False,
    type: Annotated[
        str | None,
        Field(description="Language/file-type filter, e.g. `python` or `markdown`."),
    ] = None,
    file_limit: Annotated[
        int | None,
        Field(description="Max matching files to render."),
    ] = None,
    lines_per_file: Annotated[
        int | None,
        Field(description="Max matched lines per file (content mode)."),
    ] = 500,
    if_modified_since: Annotated[
        str | None,
        Field(
            description=(
                "Timestamp from the previous result header. Files unchanged since that "
                "moment are marked unchanged or skipped."
            )
        ),
    ] = None,
    multiline: Annotated[
        bool,
        Field(description="Let the regex span newlines."),
    ] = False,
    summary: Annotated[
        bool | None,
        Field(
            description=(
                "Omit: auto-summarize large Python/JS/TS files. "
                "`true`: always signatures-only. `false`: always raw lines."
            )
        ),
    ] = None,
    context_budget_tokens: Annotated[
        int,
        Field(description="Token budget capping output size (default 6000)."),
    ] = 6000,
    include_meta: Annotated[
        bool,
        Field(description="Include response metadata such as file counts and caps."),
    ] = False,
    format: Annotated[Literal["auto", "compact", "json"], _FORMAT_FIELD] = "auto",
) -> dict[str, Any]:
    """Run grep-style search with regex, globs, type filters, and token-budgeted rendering.

    Use this tool when you already know the pattern, file globs, or file types you want.
    Prefer `search` for ranked natural-language lookup and repo-map construction.
    Returns: results shaped by `output_mode` (default `ranked_file_map`: token-budgeted file pointers with line ranges and symbols).
    """
    payload = _run_native_grep(
        path=path,
        content_regex=content_regex,
        file_glob_patterns=file_glob_patterns,
        output_mode=output_mode,
        lines_before=lines_before,
        lines_after=lines_after,
        ignore_case=ignore_case,
        type=type,
        file_limit=file_limit,
        lines_per_file=lines_per_file,
        if_modified_since=if_modified_since,
        multiline=multiline,
        summary=summary,
        context_budget_tokens=context_budget_tokens,
        include_meta=include_meta,
    )
    # Plumb savings via thread-local (read by _extract_tokens_saved) and
    # strip from the LLM-facing payload to keep responses clean.
    ts = int(payload.pop("tokens_saved", 0) or 0)
    if ts > 0:
        _tool_call_tokens_saved.value = ts
    return payload


def _scope_search_matches_to_range(payload: dict[str, Any], line_range: tuple[int, int]) -> None:
    """Restrict ranked-search matches to snippets overlapping [lo, hi].

    A "path#start-end" search scopes results to that line window. Snippets carry
    line_start/line_end; matches with no overlapping snippet are dropped. Matches
    lacking snippet line data are kept (they cannot be filtered).
    """
    lo, hi = line_range
    matches = payload.get("matches")
    if not isinstance(matches, list):
        return
    kept: list[dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        snippets = match.get("snippets")
        if isinstance(snippets, list) and snippets:
            in_window = [
                snip
                for snip in snippets
                if isinstance(snip, dict)
                and int(snip.get("line_start", 0) or 0) <= hi
                and int(snip.get("line_end", snip.get("line_start", 0)) or 0) >= lo
            ]
            if not in_window:
                continue
            match = {**match, "snippets": in_window}
        kept.append(match)
    payload["matches"] = kept
    payload["match_paths"] = [str(match.get("path")) for match in kept if isinstance(match, dict) and match.get("path")]


@mcp_tool(
    name="search",
    description=(
        "Search code and docs by ranked query. Use this for relevance-ranked snippets, "
        "full-file ranked reads, or repo maps seeded from known files. Use `grep` for "
        "regex, glob, type-filter, or context-line search, then escalate with `node`, "
        "`callers`, `callees`, `usages`, or `explore` once grounded."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Ranked search query. Required for `chunks` and `full` mode.",
            },
            "path": {
                "type": "string",
                "default": ".",
                "description": (
                    "Workspace-relative file or directory to search. A single file may carry "
                    "a '#start-end' suffix (e.g. 'store.py#60-100') to scope ranked results to "
                    "that line range."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["chunks", "map"],
                "default": "chunks",
                "description": (
                    "`chunks` returns ranked snippets per file, and `map` builds a repo map from `seed_files`."
                ),
            },
            "max_files": {
                "type": "integer",
                "default": 10,
                "description": "Maximum number of ranked files to return.",
            },
            "seed_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Seed files that bias ranking. Required when `mode='map'` because repo-map "
                    "mode expands outward from these files."
                ),
            },
            "budget_tokens": {
                "type": "integer",
                "default": 2000,
                "description": "Total token budget for ranked search output or repo-map output.",
            },
            "include_meta": {
                "type": "boolean",
                "default": False,
                "description": "Include backend/cache metadata fields in the response.",
            },
            "format": _FORMAT_SCHEMA_PROPERTY,
        },
        "required": [],
    },
)
def tool_smart_search(
    query: Annotated[
        str | None,
        Field(description="Ranked search query. Required for `chunks` mode."),
    ] = None,
    path: Annotated[
        str,
        Field(
            description=(
                "Workspace-relative file or directory to search. A single file may carry a "
                "'#start-end' suffix (e.g. 'store.py#60-100') to scope ranked results to that line range."
            ),
        ),
    ] = ".",
    mode: Annotated[
        Literal["chunks", "map"],
        Field(
            description=("`chunks` returns ranked snippets per file, and `map` builds a repo map from `seed_files`.")
        ),
    ] = "chunks",
    max_files: Annotated[
        int,
        Field(description="Maximum number of ranked files to return."),
    ] = 10,
    max_chars_per_file: Annotated[
        int,
        Field(description=("Cap the returned characters per ranked file before the overall token budget is applied.")),
    ] = 2000,
    include_outline: Annotated[
        bool,
        Field(description="Include outline metadata for ranked files when the backend can provide it."),
    ] = True,
    seed_files: Annotated[
        list[str] | None,
        Field(
            description=(
                "Seed files that bias ranking. Required when `mode='map'` because repo-map "
                "mode expands outward from these files."
            )
        ),
    ] = None,
    budget_tokens: Annotated[
        int,
        Field(description="Total token budget for ranked search output or repo-map output."),
    ] = 2000,
    include_meta: Annotated[
        bool,
        Field(description="Include backend/cache metadata fields in the response."),
    ] = False,
    format: Annotated[str, _FORMAT_FIELD] = "auto",
) -> dict[str, Any]:
    """Search by ranked query or repo-map construction, then hand off to node/explore-style code intel.

    - Pass `query` for relevance-ranked search over code and docs.
    - Use `mode='chunks'` for snippets.
    - Use `mode='map'` with `seed_files` to build a repo map.
    - Use `grep` instead when you need regex, glob, type filters, summaries, or incremental reruns.
    - Once grounded, use `node`, `callers`, `callees`, `usages`, or `explore` for exact code-intel follow-up.
    - Run independent searches in parallel within a single response; don't chain them serially.
    """
    # A "path#start-end" suffix scopes ranked results to a line window of one file.
    line_range: tuple[int, int] | None = None
    path, suffix_range = _split_read_range_suffix(path)
    if suffix_range is not None:
        lo_text, _, hi_text = suffix_range.partition("-")
        lo = int(re.sub(r"\D", "", lo_text) or 0)
        hi = int(re.sub(r"\D", "", hi_text) or 0) if hi_text else lo
        if lo:
            line_range = (lo, hi or lo)
    if mode == "map":
        if not seed_files:
            raise ValueError("seed_files is required when mode='map'")
        from atelier.core.capabilities.tool_supervision.smart_search import smart_search

        payload = smart_search(
            query=query or "",
            path=path,
            mode=mode,
            max_files=max_files,
            max_chars_per_file=max_chars_per_file,
            include_outline=include_outline,
            seed_files=seed_files,
            budget_tokens=budget_tokens,
        )
    elif query is None:
        raise ValueError("query is required for ranked search; use grep for regex/glob search")
    else:
        from atelier.core.capabilities.grounded_loop.search_first import search_first

        workspace_root = _workspace_root()

        def indexed_search(
            *,
            query: str,
            path: str,
            max_files: int,
            budget_tokens: int,
        ) -> dict[str, Any]:
            requested = Path(path)
            resolved = requested if requested.is_absolute() else workspace_root / requested
            resolved = resolved.resolve()
            file_glob: str | None = None
            if resolved != workspace_root:
                relative = str(resolved.relative_to(workspace_root))
                file_glob = relative if resolved.is_file() else f"{relative}/**"
            return cast(
                dict[str, Any],
                _code_context_engine(str(workspace_root)).tool_search(
                    query,
                    limit=max(max_files * 4, 20),
                    mode="hybrid",
                    intent="auto",
                    snippet="head",
                    snippet_lines=12,
                    file_glob=file_glob,
                    budget_tokens=budget_tokens,
                ),
            )

        payload = search_first(
            query=query,
            task=query,
            path=path,
            max_files=max_files,
            max_chars_per_file=max_chars_per_file,
            include_outline=include_outline,
            budget_tokens=budget_tokens,
            indexed_search=indexed_search,
        )
    if line_range is not None and mode == "chunks":
        _scope_search_matches_to_range(payload, line_range)
    # Plumb savings via thread-local and strip from the LLM-facing payload.
    ts = int(payload.pop("tokens_saved", 0) or 0)
    if ts > 0:
        _tool_call_tokens_saved.value = ts
    if include_meta:
        return payload
    payload.pop("cache_hit", None)
    payload.pop("backend", None)
    payload.pop("index_age_seconds", None)
    payload.pop("total_tokens", None)
    return payload


@mcp_tool(name="compact")
def tool_compact(
    op: Annotated[
        str,
        Field(
            description=(
                'Operation: "compact" (default) compresses the run ledger into a compact '
                'session-state block; "consolidate" (T6) distills recent findings AND prunes '
                "stale history via the same compaction entrypoint — call it as an autonomous "
                'compaction lever when context is heavy; "retrieve" (T7/T8) reads a spilled '
                "tool-output payload back by ref_id (use slice_start/slice_length to window it)."
            )
        ),
    ] = "compact",
    session_id: Annotated[
        str | None,
        Field(description="Optional run-ledger session ID override. Usually omit."),
    ] = None,
    ref_id: Annotated[
        str | None,
        Field(description='For op="retrieve": the spill ref id ("spill:...") to read back.'),
    ] = None,
    slice_start: Annotated[
        int,
        Field(description='For op="retrieve": start character offset into the spilled content.'),
    ] = 0,
    slice_length: Annotated[
        int,
        Field(description='For op="retrieve": chars to return from slice_start; <=0 means to the end.'),
    ] = 0,
) -> dict[str, Any]:
    """Compress the full run ledger into a compact session state block.

    Ops: "compact" (default, unchanged behavior), "consolidate" (distill + prune,
    reusing the same compaction entrypoint), and "retrieve" (read a spilled
    oversized tool output back by ref id).
    """
    normalized = (op or "compact").strip().lower()
    if normalized == "retrieve":
        if not ref_id:
            return {"error": 'op="retrieve" requires ref_id'}
        from atelier.core.capabilities.tool_supervision import tool_output_spill

        window = (slice_start, slice_length) if (slice_start or slice_length) else None
        return tool_output_spill.retrieve(ref_id, slice=window)
    # "compact" and "consolidate" share the existing compaction entrypoint
    # (ContextCompressor().compress, via _compress_context) — do NOT reimplement
    # compression here. consolidate distills recent findings AND prunes history;
    # _compress_context already preserves recent turns + decisions and drops
    # stale history, so the lever is the same call surfaced as an agent op.
    result = cast(dict[str, Any], _compress_context(session_id=session_id))
    if normalized == "consolidate":
        result["op"] = "consolidate"
    return result


# --------------------------------------------------------------------------- #
# Remote mode & dispatcher                                                    #
# --------------------------------------------------------------------------- #

# Tools that are routed through the remote HTTP service in MCP remote mode.
_REMOTE_TOOLS = frozenset(
    {
        "context",
        "memory",
        "rescue",
        "trace",
        "verify",
    }
)

# Read-only tools for outcome tracking (distinguishes reads from writes).
_READ_TOOLS = frozenset(
    {
        "Read",
        "View",
        "read_file",
        "view",
        "view_range",
        "search_read",
        "grep",
        "glob",
        "cached_grep",
    }
)

# Read-style tools whose byte-identical results may be deduped within a session
# (registered tool names, post-alias). See context_dedup for the mechanism.
_DEDUP_TOOLS = frozenset({"read", "search", "grep", "explore"})


SHELL_TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Shell command to execute. Blocked: bash/sh/zsh/fish, rm -rf, git reset --hard, git clean -fd. Rewritten transparently: cat→read, rg/grep→grep tool.",
        },
        "cwd": {
            "type": "string",
            "description": "Working directory. Defaults to CLAUDE_WORKSPACE_ROOT.",
        },
        "timeout": {
            "type": "integer",
            "default": 1800,
            "description": "Seconds before the command is killed. Defaults to 30 minutes for builds and test suites.",
        },
        "max_lines": {
            "type": "integer",
            "default": 200,
            "description": "Max output lines. Excess lines are head+tail truncated; check truncated=true in response.",
        },
        "background": {
            "type": "boolean",
            "default": False,
            "description": "Return a managed session handle immediately instead of waiting. By default the command runs inline and blocks until it finishes or its timeout elapses -- no need to poll.",
        },
        "session_id": {
            "type": "string",
            "description": "Managed shell session returned by a background run.",
        },
        "action": {
            "type": "string",
            "enum": ["run", "poll", "cancel"],
            "default": "run",
            "description": (
                "Run a command, poll a managed (background) session, or cancel it. run blocks "
                "until the command finishes or its timeout elapses; poll blocks until a "
                "background session finishes. Most commands need only run."
            ),
        },
    },
    "additionalProperties": False,
}


@mcp_tool(name="shell", input_schema=SHELL_TOOL_INPUT_SCHEMA)
def tool_shell(
    command: str = "",
    timeout: int = 1800,
    cwd: str | None = None,
    max_lines: int = 200,
    background: bool = False,
    session_id: str | None = None,
    action: Literal["run", "poll", "cancel"] = "run",
) -> str:
    """Execute a shell command and return compact text output.

    Prefer Atelier read/grep/search tools directly — they are faster and cheaper.
    Use shell only for commands that have no Atelier equivalent (git, make, uv, npm, etc.).
    """
    result = _run_shell_tool(
        command,
        timeout=timeout,
        cwd=cwd,
        max_lines=max_lines,
        background=background,
        session_id=session_id,
        action=action,
    )
    return _render_shell_text(result)


@mcp_tool(
    name="web_fetch",
    description=(
        "Fetch a public HTTP/HTTPS page for coding-agent research. Requests Markdown when available, "
        "converts HTML to clean Markdown by default, blocks private/local network URLs, and caches "
        "fetched content for 5 minutes."
    ),
)
def tool_web_fetch(
    url: Annotated[str, Field(description="Public HTTP/HTTPS URL to fetch.")],
    output_format: Annotated[
        Literal["auto", "markdown", "text", "html"],
        Field(description="Return format. auto prefers Markdown and converts HTML to Markdown."),
    ] = "auto",
    max_chars: Annotated[
        int,
        Field(description="Maximum returned content characters. Clamped to a safe upper bound."),
    ] = 12_000,
    timeout_s: Annotated[
        float,
        Field(description="Network timeout in seconds. Clamped to a safe upper bound."),
    ] = 20.0,
    include_meta: Annotated[
        bool,
        Field(description="Include minimal debug metadata in the internal payload."),
    ] = False,
) -> dict[str, Any]:
    """Fetch a public web page and return coding-agent-friendly content.

    Returns: {content, format, tokens_saved}; the MCP layer renders `content` directly.
    """
    from atelier.core.capabilities.web_fetch import fetch_url

    return fetch_url(
        url,
        output_format=output_format,
        max_chars=max_chars,
        timeout_s=timeout_s,
        include_meta=include_meta,
    )


_remote_client: Any = None


def _get_remote_client() -> Any:
    global _remote_client
    with _STATE_LOCK:
        if _remote_client is None:
            from atelier.gateway.adapters.remote_client import RemoteClient

            _remote_client = RemoteClient()
    return _remote_client


def _dispatch_remote(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if _remote_client is None and not os.environ.get("ATELIER_SERVICE_URL"):
        if name == "context":
            # Route through the registered handler so bootstrap job queuing,
            # worker spawn throttle, and session bookkeeping all execute.
            spec = TOOLS.get("context")
            if spec is None:
                raise ValueError("context tool not registered")
            handler = cast(Callable[[dict[str, Any]], dict[str, Any]], spec["handler"])
            return handler(args)
        if name == "rescue":
            rescue_result = _runtime().rescue_failure(
                task=str(args.get("task") or ""),
                error=str(args.get("error") or ""),
                files=cast(list[str], args.get("files") or []),
                recent_actions=cast(list[str], args.get("recent_actions") or []),
                domain=cast(str | None, args.get("domain")),
            )
            return rescue_result.model_dump()
        spec = TOOLS.get(name)
        if spec is None:
            raise ValueError(f"unknown remote tool: {name}")
        handler = cast(Callable[[dict[str, Any]], dict[str, Any]], spec["handler"])
        return handler(args)
    client = _get_remote_client()

    if name == "context":
        context_args = dict(args)
        context_args["files"] = cast(list[str], args.get("files") or [])
        context_args["tools"] = cast(list[str], args.get("tools") or [])
        context_args["errors"] = cast(list[str], args.get("errors") or [])
        return cast(dict[str, Any], client.get_context(context_args))
    if name == "memory":
        return cast(dict[str, Any], client.memory(args))
    if name == "rescue":
        return cast(dict[str, Any], client.rescue_failure(args))
    if name in {"trace", "record"}:
        trace_result = cast(dict[str, Any], client.record_trace(args))
        trace_id = str(trace_result.get("trace_id") or trace_result.get("id") or "")
        event_recorded = bool(trace_result.get("event_recorded"))
        return {"trace_id": trace_id, "event_recorded": event_recorded}
    if name == "verify":
        return cast(dict[str, Any], client.run_rubric_gate(args))
    raise ValueError(f"tool not supported in remote mode: {name}")


# --------------------------------------------------------------------------- #
# MCP Protocol Handling                                                       #
# --------------------------------------------------------------------------- #


def _lever_for_tool(tool_name: str) -> str:
    lowered = tool_name.strip().lower().replace("-", "_").replace(" ", "_")
    if lowered in {"read", "search"} or lowered.endswith("_read") or lowered.endswith("_search"):
        return "search_read"
    if lowered == "edit" or lowered.endswith("_edit"):
        return "batch_edit"
    if lowered == "sql" or lowered.endswith("_sql"):
        return "sql_batch"
    if lowered == "compact" or lowered.endswith("_compact"):
        return "compact_lifecycle"
    if lowered == "memory" or lowered.endswith("_memory"):
        return "scoped_recall"
    if lowered == "context" or lowered.endswith("_context"):
        return "playbook_inject"
    return lowered or "unknown"


def _price_tokens_saved_usd(model: str, tokens_saved: int) -> float:
    """Price ``tokens_saved`` at *model*'s INPUT rate. No fallback.

    Saved tokens are bytes Atelier kept out of the LLM input — they would
    have been billed as new input tokens at the model in use at that turn.
    If the model is unknown or has no pricing entry, returns 0.0 (no guess).
    """
    if tokens_saved <= 0 or not model or model == "_default":
        return 0.0
    from atelier.core.capabilities.pricing import get_model_pricing

    pricing = get_model_pricing(model)
    if pricing is None or not pricing.known or pricing.input <= 0:
        return 0.0
    return pricing.cost_usd(input_tokens=int(tokens_saved))


def _classify_read_savings(
    tool_name: str,
    args: dict[str, Any],
    result: dict[str, Any],
    *,
    tokens_saved: int,
    default_lever: str,
) -> tuple[str, dict[str, Any]]:
    lowered = tool_name.strip().lower().replace("-", "_").replace(" ", "_")
    if lowered not in {"read", "smart_read"}:
        return default_lever, {}

    mode = str(result.get("mode") or "").strip().lower()
    if mode == "outline" and tokens_saved > 0:
        classified = "structure_map"
    elif mode == "range" and tokens_saved > 0:
        classified = "delta_read"
    else:
        classified = default_lever

    path = result.get("path") or args.get("file_path") or args.get("path")
    metadata: dict[str, Any] = {"read_mode": mode or "full"}
    if isinstance(path, str) and path:
        metadata["path"] = path
    range_spec = result.get("range") or args.get("range")
    if isinstance(range_spec, str) and range_spec:
        metadata["range"] = range_spec
    if "cache_hit" in result:
        metadata["cache_hit"] = bool(result.get("cache_hit"))
    return classified, metadata


def _record_context_budget_for_tool(
    tool_name: str,
    args: dict[str, Any],
    led: RunLedger,
    result: dict[str, Any],
    *,
    rendered_text_size: int | None = None,
) -> None:
    try:
        recorder = _get_context_budget_recorder()

        # Model is best-effort for the analytics recorder below; the
        # response-embedded `saved` field carries the per-event truth.
        model = str(getattr(led, "model", "") or os.environ.get("ATELIER_MODEL") or "").strip()

        compact_tool_tokens_saved = _extract_compact_output_tokens_saved(result)
        tokens_saved = _extract_tokens_saved(result)
        base_lever = _lever_for_tool(tool_name)
        lever, savings_metadata = _classify_read_savings(
            tool_name,
            args if isinstance(args, dict) else {},
            result,
            tokens_saved=tokens_saved,
            default_lever=base_lever,
        )
        if "cache_hit" in result and "cache_hit" not in savings_metadata:
            savings_metadata["cache_hit"] = bool(result.get("cache_hit"))
        if isinstance(result.get("provenance"), str):
            savings_metadata.setdefault("provenance", str(result["provenance"]))
        op = args.get("op") if isinstance(args, dict) else None
        if isinstance(op, str) and op:
            savings_metadata.setdefault("op", op)

        raw_lever_savings = result.get("tokens_saved")
        lever_savings = raw_lever_savings.copy() if isinstance(raw_lever_savings, dict) else {}
        if compact_tool_tokens_saved > 0 and not lever_savings:
            lever_savings[f"compact_tool_output:{lever}"] = compact_tool_tokens_saved
        elif tokens_saved > 0:
            lever_savings[lever] = max(int(lever_savings.get(lever, 0) or 0), tokens_saved)
        if tool_name:
            lever_savings.setdefault(f"tool:{tool_name}", 0)

        # Lifetime smart-state counters remain useful for cumulative "savings
        # since install" metrics; they're a single integer pair, not a
        # per-event log. Real per-session savings ride the MCP response's
        # content[].saved field into the Claude transcript.
        calls_avoided = _coerce_saved_tokens(result.get("calls_saved"))
        if tokens_saved > 0 or calls_avoided > 0:
            _record_smart_state_savings(tokens_saved=tokens_saved, calls_avoided=calls_avoided)

        actual_output_tokens = int(result.get("total_tokens", 0) or 0)
        if actual_output_tokens <= 0:
            if rendered_text_size is not None:
                actual_output_tokens = max(0, rendered_text_size // 4)
            else:
                actual_output_tokens = max(0, len(json.dumps(result, ensure_ascii=False, default=str)) // 4)

        if compact_tool_tokens_saved > 0 and not isinstance(raw_lever_savings, dict):
            recorder.record_compact_tool_output(
                session_id=led.session_id,
                turn_index=max(0, len(led.events) - 1),
                model=model,
                method=lever,
                tokens_in=actual_output_tokens + compact_tool_tokens_saved,
                tokens_out=actual_output_tokens,
            )
        else:
            recorder.record(
                session_id=led.session_id,
                turn_index=max(0, len(led.events) - 1),
                model=model,
                input_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
                output_tokens=actual_output_tokens,
                naive_input_tokens=actual_output_tokens + tokens_saved,
                lever_savings=lever_savings,
                tool_calls=1,
            )
    except Exception:
        logging.exception("Recovered from broad exception handler")
        logger.warning("Suppressed exception while recording context budget", exc_info=True)


_TASK_TEXT_KEYS = ("task", "user_goal", "query", "prompt", "content", "description", "error")


def _task_text_from_args(args: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _TASK_TEXT_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def _workflow_state_from_workspace() -> dict[str, Any]:
    workflow = _read_workspace_session_state().get("workflow")
    return workflow if isinstance(workflow, dict) else {}


def _route_outcome_calibration(tool_name: str, session_state: Mapping[str, Any], led: RunLedger) -> dict[str, Any]:
    from atelier.infra.runtime.outcome_capture import load_outcomes_from_state

    root = led._root
    if root is None:
        return {}
    outcomes = load_outcomes_from_state(outcomes_path(root, led.session_id))
    session_phase = str(session_state.get("session_phase") or "").strip()
    followed: list[float] = []
    unfollowed: list[float] = []
    samples = 0
    for entry in outcomes.get("route_outcomes", []):
        if str(entry.get("tool") or "") != tool_name:
            continue
        scored_state = entry.get("scored_state")
        if not isinstance(scored_state, dict):
            continue
        if session_phase and str(scored_state.get("session_phase") or "") != session_phase:
            continue
        outcome_window = entry.get("outcome_window")
        if not isinstance(outcome_window, dict):
            continue
        raw_score = outcome_window.get("outcome_score")
        if isinstance(raw_score, bool):
            continue
        if isinstance(raw_score, int | float):
            score = float(raw_score)
        elif isinstance(raw_score, str):
            try:
                score = float(raw_score.strip())
            except ValueError:
                continue
        else:
            continue
        samples += 1
        if bool(entry.get("recommendation_followed")):
            followed.append(score)
        else:
            unfollowed.append(score)
    if not followed or not unfollowed:
        return {}
    delta = round(sum(followed) / len(followed) - sum(unfollowed) / len(unfollowed), 4)
    if delta <= 0.0:
        return {"route_outcome_samples": samples}
    return {
        "route_outcome_score_delta": delta,
        "route_outcome_samples": samples,
    }


def _route_enforcement_enabled() -> bool:
    raw = os.environ.get("ATELIER_ENFORCE_ROUTE_MODEL")
    if raw is None:
        return False
    return raw.strip().lower() not in {"", "0", "false", "off", "no"}


def _restore_legacy_route(workflow: dict[str, Any], current_step: str) -> tuple[Any | None, int]:
    from atelier.core.capabilities.model_routing import ModelRecommendation

    routing = workflow.get("routing")
    if not isinstance(routing, dict):
        return None, 0
    if str(routing.get("step") or "") != current_step:
        return None, 0
    raw = routing.get("recommendation")
    if not isinstance(raw, dict):
        return None, 0
    tier = str(raw.get("tier") or "").strip()
    if tier not in {"cheap", "medium", "expensive"}:
        return None, 0
    typed_tier = cast(Literal["cheap", "medium", "expensive"], tier)
    route_tier = str(raw.get("route_tier") or "")
    if route_tier not in {
        "deterministic",
        "local_slm",
        "cheap_llm",
        "frontier_llm",
        "human_review",
    }:
        route_tier = "frontier_llm" if tier == "expensive" else "cheap_llm"
    typed_route_tier = cast(
        Literal["deterministic", "local_slm", "cheap_llm", "frontier_llm", "human_review"],
        route_tier,
    )
    baseline_tier_raw = str(raw.get("baseline_tier") or "").strip()
    baseline_tier = (
        cast(Literal["cheap", "medium", "expensive"], baseline_tier_raw)
        if baseline_tier_raw in {"cheap", "medium", "expensive"}
        else None
    )
    return (
        ModelRecommendation(
            tier=typed_tier,
            route_tier=typed_route_tier,
            model=str(raw.get("model") or ""),
            reasons=[str(reason) for reason in raw.get("reasons") or []],
            score=int(raw.get("score") or 0),
            cache_affinity_model=str(raw.get("cache_affinity_model") or "") or None,
            cache_cost_usd=float(raw.get("cache_cost_usd") or 0.0),
            quality_gain_usd_estimated=float(raw.get("quality_gain_usd_estimated") or 0.0),
            decision=str(raw.get("decision") or "baseline"),
            baseline_tier=baseline_tier,
            sticky_until_tool_calls=int(raw.get("sticky_until_tool_calls") or 0),
        ),
        max(0, int(routing.get("remaining_tool_calls") or 0)),
    )


def _persist_legacy_route(workflow: dict[str, Any], payload: dict[str, Any], current_step: str) -> None:
    if not current_step:
        return
    tier = str(payload.get("tier") or "").strip()
    model = str(payload.get("model") or "").strip()
    if tier not in {"cheap", "medium", "expensive"} or not model:
        return
    sticky_window = max(0, int(workflow.get("sticky_window") or 0))
    remaining = max(0, int(payload.get("sticky_until_tool_calls") or 0))
    if str(payload.get("decision") or "baseline") != "sticky":
        remaining = sticky_window
    workflow["routing"] = {
        "step": current_step,
        "remaining_tool_calls": remaining,
        "recommendation": {
            "tier": tier,
            "route_tier": payload.get("route_tier"),
            "model": model,
            "reasons": list(payload.get("reasons") or []),
            "score": int(payload.get("score") or 0),
            "cache_affinity_model": payload.get("cache_affinity_model"),
            "cache_cost_usd": float(payload.get("cache_cost_usd") or 0.0),
            "quality_gain_usd_estimated": float(payload.get("quality_gain_usd_estimated") or 0.0),
            "decision": str(payload.get("decision") or "baseline"),
            "baseline_tier": payload.get("baseline_tier"),
            "sticky_until_tool_calls": remaining,
        },
    }
    # Hold _STATE_LOCK across the read-modify-write so a concurrent handler's
    # session_state update is not lost. _STATE_LOCK is an RLock.
    with _STATE_LOCK:
        state = _read_workspace_session_state()
        state["workflow"] = workflow
        _write_workspace_session_state(state)


def _prepare_model_recommendation(
    tool_name: str,
    args: dict[str, Any],
    led: RunLedger,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    from atelier.core.capabilities.cross_vendor_routing.configuration import RouteConfigError
    from atelier.core.capabilities.cross_vendor_routing.router import NoFeasibleRouteError
    from atelier.core.capabilities.model_routing import ModelRouter
    from atelier.core.capabilities.pricing import get_model_pricing

    session_state = _model_recommendation_state(led, args)
    session_state.update(_route_outcome_calibration(tool_name, session_state, led))
    workflow = _workflow_state_from_workspace()
    current_step = str(session_state.get("workflow_step") or "")
    prior_route, stickiness_remaining = _restore_legacy_route(workflow, current_step)
    estimated_input_tokens = max(1_000, int(session_state.get("expected_input_tokens") or 0))
    try:
        decision = _select_owned_execution_route(
            tool_name=tool_name,
            task_text=_task_text_from_args(args),
            mode="auto",
            provider="",
            model="",
            runner="",
            session_state=session_state,
        )
        led.record("route_decision", f"{decision.mode} route for {tool_name}", decision.to_dict())
        actual_model = str(getattr(led, "model", "") or os.environ.get("ATELIER_MODEL") or "").strip()
        actual_vendor = _provider_for_model(actual_model)
        recommendation = {
            **decision.to_dict(),
            "vendor": decision.provider,
            "actual_model": actual_model,
            "actual_vendor": actual_vendor,
            "recommendation_followed": _normalize_model_id(actual_model) == _normalize_model_id(decision.model),
        }
        vs_model = actual_model or "auto"
        cost_saved_usd = 0.0
        if recommendation["model"] != vs_model and vs_model != "auto":
            expensive_pricing = get_model_pricing(vs_model)
            recommended_pricing = get_model_pricing(recommendation["model"])
            cost_saved_usd = max(
                0.0,
                expensive_pricing.cost_usd(input_tokens=estimated_input_tokens)
                - recommended_pricing.cost_usd(input_tokens=estimated_input_tokens),
            )
        payload = {
            "at": datetime.now(UTC).isoformat(),
            "kind": "model_recommendation",
            "lever": "model_routing",
            "session_id": led.session_id,
            "agent": led.agent or _detect_agent(),
            "tool_name": tool_name,
            "tokens_saved": 0,
            "cost_saved_usd": round(cost_saved_usd, 6),
            "vs_model": vs_model,
            "estimated_input_tokens": estimated_input_tokens,
            "configured": True,
            **recommendation,
        }
    except (RouteConfigError, NoFeasibleRouteError) as exc:

        def _record_route_decision(route_payload: dict[str, Any]) -> None:
            led.record(
                "route_decision",
                f"{route_payload.get('decision', 'baseline')} route for {tool_name}",
                route_payload,
            )

        legacy = ModelRouter().recommend(
            tool_name,
            _task_text_from_args(args),
            session_state,
            prior_route=prior_route,
            stickiness_remaining=stickiness_remaining,
            route_decision_sink=_record_route_decision,
        )
        if legacy is None:
            raise NoFeasibleRouteError("bench-off") from None
        vs_model = "auto"
        cost_saved_usd = 0.0
        if legacy.model != vs_model:
            expensive_pricing = get_model_pricing(vs_model)
            recommended_pricing = get_model_pricing(legacy.model)
            cost_saved_usd = max(
                0.0,
                expensive_pricing.cost_usd(input_tokens=estimated_input_tokens)
                - recommended_pricing.cost_usd(input_tokens=estimated_input_tokens),
            )
        payload = {
            "at": datetime.now(UTC).isoformat(),
            "kind": "model_recommendation",
            "lever": "model_routing",
            "session_id": led.session_id,
            "agent": led.agent or _detect_agent(),
            "tool_name": tool_name,
            "tokens_saved": 0,
            "configured": False,
            "cost_saved_usd": round(cost_saved_usd, 6),
            "estimated_input_tokens": estimated_input_tokens,
            "vs_model": vs_model,
            "error": str(exc),
            **legacy.to_dict(),
        }
    return payload, session_state, workflow, current_step


def _finalize_model_recommendation(
    payload: dict[str, Any],
    *,
    led: RunLedger,
    tool_name: str,
    session_state: Mapping[str, Any],
    workflow: dict[str, Any],
    current_step: str,
    wrapper_applied: bool = False,
    wrapper_model: str | None = None,
) -> dict[str, Any]:
    finalized = dict(payload)
    finalized["route_enforcement_active"] = _route_enforcement_enabled() and finalized.get("configured") is not False
    finalized["wrapper_applied"] = wrapper_applied
    if wrapper_model:
        finalized["wrapper_model"] = wrapper_model
        finalized["executed_model_scope"] = "local_mcp_only"
    if wrapper_applied:
        finalized["recommendation_followed"] = True
    led.record(
        "model_recommendation",
        f"recommend {finalized.get('model', 'unconfigured')} for {tool_name}",
        finalized,
    )
    if finalized.get("recommendation_followed") or float(finalized.get("cost_saved_usd") or 0.0) > 0:
        _append_live_savings_event(finalized)
    else:
        # Unfollowed zero-saving recommendation: keep the advisor-countable core
        # fields, drop the bulky static provider metadata (~80% of the payload).
        _append_live_savings_event(
            {
                key: finalized[key]
                for key in (
                    "at",
                    "kind",
                    "lever",
                    "session_id",
                    "agent",
                    "tool_name",
                    "tokens_saved",
                    "cost_saved_usd",
                    "configured",
                    "model",
                    "vs_model",
                    "tier",
                    "recommendation_followed",
                )
                if key in finalized
            }
        )
    # Mirror the routing saving into the per-session sidecar so the live
    # statusline / stop hook can show it cheaply: sessions/<id>/savings.jsonl is
    # read per render, while live_savings_events.jsonl is too large to scan there.
    # kind="routing" keeps it out of the context-savings tally (never double-counted).
    _routing_usd = float(finalized.get("cost_saved_usd") or 0.0)
    if _routing_usd > 0:
        with contextlib.suppress(Exception):
            _sidecar = _get_host_session_sidecar_path()
            _sidecar.parent.mkdir(parents=True, exist_ok=True)
            with _sidecar.open("a", encoding="utf-8") as _fh:
                _fh.write(
                    json.dumps(
                        {
                            "kind": "routing",
                            "usd": round(_routing_usd, 6),
                            "tool": tool_name,
                            "model": str(finalized.get("model") or ""),
                            "ts": str(finalized.get("at") or ""),
                        }
                    )
                    + "\n"
                )
    _persist_legacy_route(workflow, finalized, current_step)

    if finalized.get("configured") is not False:
        from atelier.infra.runtime import outcome_capture

        outcome_capture.schedule_route(
            session_id=led.session_id,
            tool=tool_name,
            recommended_vendor=str(finalized.get("vendor") or ""),
            recommended_tier=str(finalized.get("tier") or ""),
            recommended_model=str(finalized.get("model") or ""),
            actual_vendor=str(finalized.get("actual_vendor") or ""),
            actual_model=str(finalized.get("actual_model") or ""),
            recommendation_followed=bool(finalized.get("recommendation_followed")),
            applied_lessons=[str(item) for item in finalized.get("applied_lessons") or []],
            cost_cap_triggered=bool(finalized.get("cost_cap_triggered")),
            cost_cap_limit_usd_per_session=(
                float(finalized["cost_cap_limit_usd_per_session"])
                if finalized.get("cost_cap_limit_usd_per_session") is not None
                else None
            ),
            scored_state={
                "turn_number": int(session_state.get("turn_number") or 0),
                "prior_errors": len(led.errors_seen) + len(led.repeated_failures),
                "session_phase": str(session_state.get("session_phase") or "explore"),
                "workflow_step": str(session_state.get("workflow_step") or ""),
            },
            writer=_make_outcome_writer(led),
        )

    return finalized


def _latest_cache_affinity_model(led: RunLedger) -> str | None:
    for event in reversed(led.events):
        payload = event.payload
        raw_cache_write_tokens = (
            payload.get("cache_write_tokens")
            or payload.get("cache_creation_input_tokens")
            or payload.get("cache_creation_tokens")
            or 0
        )
        try:
            cache_write_tokens = int(raw_cache_write_tokens)
        except (TypeError, ValueError):
            cache_write_tokens = 0
        model = str(payload.get("model") or "").strip()
        if cache_write_tokens > 0 and model:
            return model
    return None


def _estimate_compacted_state_tokens(state: Any) -> int:
    prompt_block = state.to_prompt_block()
    preserved_chars = len(prompt_block) + sum(len(turn) for turn in state.recent_turns)
    return max(0, preserved_chars // 4)


def _session_compaction_savings_payload(
    led: RunLedger,
    state: Any,
    *,
    tokens_before: int,
    trigger: str,
    reason: str,
    utilisation_pct: float | None = None,
) -> dict[str, Any]:
    tokens_after_estimate = _estimate_compacted_state_tokens(state)
    tokens_freed = max(0, int(tokens_before) - tokens_after_estimate)
    model = (
        _latest_cache_affinity_model(led)
        or str(getattr(led, "model", "") or "").strip()
        or os.environ.get("ATELIER_MODEL", "")
    ).strip()
    cost_saved_usd = round(_price_tokens_saved_usd(model, tokens_freed), 6)
    utilisation = (
        round(float(utilisation_pct), 1)
        if utilisation_pct is not None
        else round(100.0 * max(0, int(tokens_before)) / CONTEXT_WINDOW_TOKENS, 1)
    )
    return {
        "at": datetime.now(UTC).isoformat(),
        "kind": "session_compaction",
        "lever": "session_compaction",
        "session_id": led.session_id,
        "agent": led.agent or _detect_agent(),
        "model": model,
        "trigger": trigger,
        "reason": reason,
        "tokens_saved": tokens_freed,
        "tokens_freed": tokens_freed,
        "cost_saved_usd": cost_saved_usd,
        "tokens_before": max(0, int(tokens_before)),
        "tokens_after_estimate": tokens_after_estimate,
        "utilisation_pct": utilisation,
    }


def _emit_model_recommendation(tool_name: str, args: dict[str, Any], led: RunLedger) -> dict[str, Any]:
    payload, session_state, workflow, current_step = _prepare_model_recommendation(tool_name, args, led)
    return _finalize_model_recommendation(
        payload,
        led=led,
        tool_name=tool_name,
        session_state=session_state,
        workflow=workflow,
        current_step=current_step,
    )


def _model_recommendation_state(led: RunLedger, args: dict[str, Any]) -> dict[str, Any]:
    tool_call_events = [e for e in led.events if e.kind == "tool_call"]
    recent_tool_calls = [e.payload.get("tool", "") for e in tool_call_events[-10:]]
    turn_number = len(tool_call_events)
    workflow = _workflow_state_from_workspace()
    session_state: dict[str, Any] = {
        "prior_errors": len(led.errors_seen) + len(led.repeated_failures),
        "cache_affinity_model": _latest_cache_affinity_model(led),
        "turn_number": turn_number,
        "recent_tool_calls": recent_tool_calls,
        "session_cost_usd": round(
            sum(
                float((event.payload or {}).get("cost_usd") or 0.0)
                for event in led.events
                if event.kind == "tool_call" and (event.payload or {}).get("kind") == "llm_call"
            ),
            6,
        ),
    }
    workflow_step = str(workflow.get("current_step") or workflow.get("workflow_step") or "").strip()
    if workflow_step:
        session_state["workflow_step"] = workflow_step
    session_phase = str(workflow.get("session_phase") or "").strip()
    if session_phase:
        session_state["session_phase"] = session_phase
    if "max_output_tokens" in args:
        session_state["max_output_tokens"] = args["max_output_tokens"]
    if "budget_tokens" in args:
        session_state["max_output_tokens"] = args["budget_tokens"]
    expected_input_tokens = max(1_000, int(led.token_count or 0) // max(1, _ledger_turn_count(led)))
    session_state["expected_input_tokens"] = expected_input_tokens
    session_state.setdefault("expected_output_tokens", max(1, int(expected_input_tokens * 0.2)))
    return session_state


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    rid = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
        _emit_mcp_session_start()
        return _ok(
            rid,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {}},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        tools = [
            {
                "name": n,
                "description": _tool_description(s),
                "inputSchema": s.get("inputSchema", {}),
            }
            for n, s in sorted(TOOLS.items())
            if _tool_visible_to_llm(n, s)
        ]
        return _ok(rid, {"tools": tools})

    if method == "tools/call":
        name = params.get("name") or ""
        if name == "run":
            name = "shell"
        args = params.get("arguments") or {}
        # Some MCP clients deliver the whole `arguments` payload as a JSON string
        # instead of an object. mypyc-compiled handlers enforce dict at the boundary
        # and would reject it with "dict object expected; got str", so parse it here.
        if isinstance(args, str):
            with contextlib.suppress(json.JSONDecodeError, ValueError):
                args = json.loads(args)
        if not isinstance(args, dict):
            args = {}
        spec = TOOLS.get(name)
        if spec is None:
            return _err(rid, -32601, f"unknown tool: {name}")
        if name == "memory" and isinstance(args, dict):
            properties = spec.get("inputSchema", {}).get("properties", {})
            allowed_args = set(properties) if isinstance(properties, dict) else set()
            unknown_args = sorted(set(args) - allowed_args)
            if unknown_args:
                return _err(
                    rid,
                    -32602,
                    f"unknown arguments for memory tool: {', '.join(unknown_args)}",
                )

        remote_routed = name in _REMOTE_TOOLS
        # mode="symbols" must always run locally (SCIP engine); bypass remote routing
        if name == "context" and isinstance(args, dict) and args.get("mode") == "symbols":
            remote_routed = False
        # N10 — request-scoped project isolation. Honor an Mcp-Project-Path-style
        # override for the lifetime of this request only; absent -> unchanged.
        _prior_project = _set_request_project(_extract_request_project(params, args if isinstance(args, dict) else {}))
        rendered_text: str | None = None
        _call_duration_ms: int = 0
        try:
            if remote_routed:
                _remote_start = time.perf_counter()
                result = _dispatch_remote(name, args)
                _call_duration_ms = round((time.perf_counter() - _remote_start) * 1000)
                if isinstance(result, dict):
                    result = _clean_tool_result(result, name)
            else:
                led = _get_ledger()
                route_payload, route_state, route_workflow, route_step = _prepare_model_recommendation(
                    name,
                    args if isinstance(args, dict) else {},
                    led,
                )
                handler: Callable[[dict[str, Any]], Any] = spec["handler"]
                if name == "edit" and isinstance(args, dict):
                    blocked_message = _benchmark_edit_block_message(args)
                    if blocked_message:
                        return _err(rid, -32000, blocked_message)
                _tool_call_tokens_saved.value = 0  # reset before handler so stale values can't bleed through
                _tool_call_rendered_text.value = None  # reset before handler
                wrapper_model = (
                    str(route_payload.get("model") or "")
                    if _route_enforcement_enabled() and route_payload.get("configured") is not False
                    else ""
                )
                from atelier.core.capabilities.pricing import active_model_override

                try:
                    _handler_start = time.perf_counter()
                    with active_model_override(wrapper_model or None):
                        result = handler(args)
                    _call_duration_ms = round((time.perf_counter() - _handler_start) * 1000)
                finally:
                    # Runs in finally; a raise here would mask the handler's real
                    # exception, so suppress like the sibling savings-event calls.
                    with contextlib.suppress(Exception):
                        _finalize_model_recommendation(
                            route_payload,
                            led=led,
                            tool_name=name,
                            session_state=route_state,
                            workflow=route_workflow,
                            current_step=route_step,
                            wrapper_applied=bool(wrapper_model),
                            wrapper_model=wrapper_model or None,
                        )

                if isinstance(result, dict):
                    result = _clean_tool_result(result, name)
                    _record_grounding_evidence_if_available(name, args if isinstance(args, dict) else {}, result)

                # Compute MD text for read-heavy tools
                _args = args if isinstance(args, dict) else {}
                rendered_text = render_tool_result_text(name, result)

                # Per-call savings accounting (read baseline de-dup + deferred
                # code-intel credit). Runs BEFORE budget recording so a zeroed
                # read saving flows into both the recorder and the `saved` field.
                # Local-handler path only; never touches the response bytes.
                _process_tool_accounting(name, _args, result, rid)

                _record_context_budget_for_tool(
                    name,
                    _args,
                    led,
                    result if isinstance(result, dict) else {"result": result},
                    rendered_text_size=len(rendered_text) if rendered_text else None,
                )

                with contextlib.suppress(Exception):
                    from atelier.infra.runtime import outcome_capture

                    outcome_capture.advance(
                        led.session_id,
                        tool_name=name,
                        is_error=False,
                        is_read_tool=name in _READ_TOOLS,
                        writer=_make_outcome_writer(led),
                    )

                _ok_session_id = getattr(_get_ledger(), "session_id", "") or ""
                with contextlib.suppress(Exception):
                    _append_live_savings_event(
                        {
                            "kind": "tool_call",
                            "tool": name,
                            "status": "ok",
                            "duration_ms": _call_duration_ms,
                            "session_id": _ok_session_id,
                            "ts": time.time(),
                        }
                    )

            response_text: str
            if rendered_text:
                response_text = rendered_text
            elif isinstance(result, str):
                response_text = result
            else:
                response_text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

            # Only pay the full-payload UTF-8 encode when a telemetry sink will
            # consume the byte count; otherwise approximate with the O(1) char len.
            if _mcp_debug_enabled():
                _ok_response_size = len(response_text.encode("utf-8", errors="replace"))
            else:
                _ok_response_size = len(response_text)
            _ok_sid = _ok_session_id if not remote_routed else (getattr(_get_ledger(), "session_id", "") or "")
            with contextlib.suppress(Exception):
                _append_mcp_debug_event(
                    tool=name,
                    args=args if isinstance(args, dict) else {},
                    duration_ms=_call_duration_ms,
                    response_size=_ok_response_size,
                    status="ok",
                    session_id=_ok_sid,
                )
            with contextlib.suppress(Exception):
                from atelier.gateway.integrations.langfuse import emit_tool_call as _lf_emit_tool

                _lf_emit_tool(
                    tool=name,
                    args=_scrub_args_for_debug(args) if isinstance(args, dict) else {},
                    duration_ms=_call_duration_ms,
                    response_size=_ok_response_size,
                    status="ok",
                    session_id=_ok_sid,
                )

            # G13 — caller-selectable output encoding (auto | compact | json).
            # Default `auto` returns response_text unchanged (byte-compatible);
            # `json` forces raw JSON; `compact` applies the N6-gated N7 columnar
            # form. Reads the selector from the always-defined request args (the
            # remote path never sets `_args`), with an explicit, non-default
            # value so today's default bytes are untouched.
            _fmt = args.get("format") if isinstance(args, dict) else None
            if isinstance(_fmt, str) and _fmt.strip().lower() in {"compact", "json"}:
                with contextlib.suppress(Exception):
                    from atelier.core.capabilities.tool_supervision.output_format import apply_output_format

                    response_text, _ = apply_output_format(
                        fmt=_fmt,
                        result=result,
                        rendered_text=response_text,
                    )

            # Within-session content dedup: if this read-style result is
            # byte-identical to one already returned this session (and the model
            # didn't pass force=true), return a small pointer instead of
            # re-paying input/cache cost to re-emit the same bytes. Reset on
            # compaction via context_dedup's epoch. Kill switch: ATELIER_CONTEXT_DEDUP=0.
            dedup_stubbed = False
            if name in _DEDUP_TOOLS and os.environ.get("ATELIER_CONTEXT_DEDUP", "1") != "0":
                with contextlib.suppress(Exception):
                    from atelier.core.capabilities import context_dedup as _cdedup

                    _dedup_sid = ""
                    with contextlib.suppress(Exception):
                        _dedup_sid = _get_ledger().session_id or ""
                    _dedup_outcome = _cdedup.registry().stub_for(
                        session_id=_dedup_sid,
                        content=response_text,
                        epoch=_cdedup.current_epoch(),
                        force=bool(_args.get("force")),
                    )
                    if _dedup_outcome is None and name == "read":
                        _dedup_resource = _read_dedup_resource(_args)
                        if _dedup_resource:
                            _dedup_outcome = _cdedup.registry().delta_for(
                                session_id=_dedup_sid,
                                resource=_dedup_resource,
                                content=response_text,
                                epoch=_cdedup.current_epoch(),
                                force=bool(_args.get("force")),
                            )
                    if _dedup_outcome is not None:
                        stub_text, dedup_chars_saved = _dedup_outcome
                        response_text = stub_text
                        dedup_stubbed = True
                        if dedup_chars_saved > 0:
                            _append_workspace_savings(name, dedup_chars_saved // 4, 0, rid=str(rid))
            # N4 — per-tool exact input/output token ledger. Measures the
            # request args (input) and the final emitted text (output) with the
            # local tiktoken counter, accumulates per tool name, and persists a
            # JSON sidecar under the atelier root. Additive only — never touches
            # the response bytes; best-effort so a write failure can't break the
            # tool call.
            # N4 ledger records ONLY savings-bearing calls: skip the full-output
            # tiktoken encode + sidecar rewrite entirely when nothing was saved.
            _n4_should_record = dedup_stubbed or (
                isinstance(result, dict)
                and (
                    _extract_tokens_saved(result) > 0
                    or _coerce_saved_tokens(result.get("calls_saved")) > 0
                )
            )
            if _n4_should_record:
                with contextlib.suppress(Exception):
                    from atelier.core.capabilities.tool_token_ledger import record_tool_tokens

                    record_tool_tokens(
                        _atelier_root(),
                        name,
                        input_payload=args,
                        output_payload=response_text,
                    )

            # Embed per-call savings on the content item so they also ride into
            # the Claude transcript JSONL. NOTE: this is a secondary record —
            # the live statusline/analytics source is the per-session sidecar
            # sessions/<id>/savings.jsonl written by _append_workspace_savings
            # below, not the transcript.
            # Shape: {"tokens": int, "calls": int}. Either may be 0 but the
            # object is omitted entirely when both are 0.
            # First bound, for context hygiene: head+tail compact a single
            # runaway result so it can't flood the host prompt (which the host
            # re-pays for on every later turn). Deterministic, so the compacted
            # bytes stay prefix-cache stable across identical calls.
            # T8 (ATELIER_AUTO_COMPACT_OUTPUT, default off): auto-compact an
            # oversized result (AST-aware for code) while preserving the
            # untransformed original in the T7 spill store so it stays
            # reversible. Off -> returns response_text unchanged.
            _spill_args = args if isinstance(args, dict) else {}
            response_text = _auto_compact_result_text(response_text, name, _spill_args)
            # T7 (ATELIER_TOOL_OUTPUT_SPILL, default off): spill the FULL,
            # UNTRANSFORMED payload BEFORE the legacy char compaction below, gated
            # on the same char threshold (_compact_result_chars) the compactor
            # uses. Otherwise the byte-gated spill (6MB) never fires under default
            # caps and _compact_result_text would drop the middle first, so the
            # spilled artifact would only ever hold already-compacted text.
            # Off / non-spill tools -> no-op, so _compact_result_text runs exactly
            # as before.
            response_text = _spill_oversized_result_text(
                response_text, name, _spill_args, _compact_result_chars(), unit="chars"
            )
            response_text = _compact_result_text(response_text, name)
            # Wire-byte backstop: a spill-worthy result still over the multi-MB
            # frame ceiling after compaction is spilled rather than truncated.
            # When the char-gated spill above already fired, response_text is now
            # a small summary, so this no-ops.
            response_text = _spill_oversized_result_text(response_text, name, _spill_args, _max_result_bytes())
            # Bound the result so one oversized frame can't trip the host's
            # stdout guard and disconnect the server (no mid-session reconnect).
            response_text = _truncate_result_text(response_text, _max_result_bytes())
            content_item: dict[str, Any] = {
                "type": "text",
                "text": response_text,
            }
            # Best-effort cache hint, NOT a measured saving. Tag large results
            # so a host that honors MCP cache_control can checkpoint them for
            # prompt caching. Caveats kept honest on purpose: (1) we do not
            # verify the host actually forwards this; (2) the conversation
            # prefix is already auto-cached by the host, so the marginal gain
            # is small; (3) a cache *write* costs ~25% over input, so a one-off
            # large result that is never re-read pays the write premium for
            # nothing. The ≥4096-char floor (~1024 tokens) is Anthropic's
            # minimum cacheable size.
            # ...and skip it entirely for dedup-eligible tools (read): an exact
            # re-read is elided by the dedup pass below, so the marker can never
            # earn its cache-read payoff there and only risks a redundant
            # breakpoint on top of the host's automatic prefix caching.
            if len(response_text) >= 4096 and name not in _DEDUP_TOOLS:
                content_item["cache_control"] = {"type": "ephemeral"}
            # When deduped, skip the original per-call savings (they'd otherwise be
            # credited against bytes we just elided).
            if not dedup_stubbed and isinstance(result, dict):
                saved_tokens = _extract_tokens_saved(result)
                saved_calls = _coerce_saved_tokens(result.pop("calls_saved", None))
                if saved_tokens > 0 or saved_calls > 0:
                    content_item["saved"] = {
                        "tokens": int(saved_tokens),
                        "calls": int(saved_calls),
                    }
                    _append_workspace_savings(name, saved_tokens, saved_calls, rid=str(rid))

            response_payload: dict[str, Any] = {"content": [content_item]}
            # Stash the full structured result for the in-process CLI so `tools call
            # ... --json` returns the dict for EVERY tool -- including the ones whose
            # host-facing content is rendered text (read, grep, search, shell, ...).
            # This never goes on response_payload, so the MCP host's main model only
            # ever sees `content`; no structured data rides the wire to any consumer.
            _tool_call_raw_result.value = result if isinstance(result, dict) else None
            return _ok(rid, response_payload)
        except Exception as exc:
            logging.exception("Recovered from broad exception handler")
            if not remote_routed:
                with contextlib.suppress(Exception):
                    from atelier.infra.runtime import outcome_capture

                    led = _get_ledger()
                    outcome_capture.advance(
                        led.session_id,
                        tool_name=name,
                        is_error=True,
                        is_env_error=isinstance(exc, (OSError, IOError)),
                        writer=_make_outcome_writer(led),
                    )
                _err_session_id = getattr(_get_ledger(), "session_id", "") or ""
                with contextlib.suppress(Exception):
                    _append_live_savings_event(
                        {
                            "kind": "tool_call",
                            "tool": name,
                            "status": "error",
                            "error": type(exc).__name__,
                            "duration_ms": _call_duration_ms,
                            "session_id": _err_session_id,
                            "ts": time.time(),
                        }
                    )
                with contextlib.suppress(Exception):
                    _append_mcp_debug_event(
                        tool=name,
                        args=args if isinstance(args, dict) else {},
                        duration_ms=_call_duration_ms,
                        response_size=0,
                        status="error",
                        error=type(exc).__name__,
                        session_id=_err_session_id,
                    )
                with contextlib.suppress(Exception):
                    from atelier.gateway.integrations.langfuse import emit_tool_call as _lf_emit_tool

                    _lf_emit_tool(
                        tool=name,
                        args=_scrub_args_for_debug(args) if isinstance(args, dict) else {},
                        duration_ms=_call_duration_ms,
                        response_size=0,
                        status="error",
                        error=type(exc).__name__,
                        session_id=_err_session_id,
                    )
            return _err(rid, _tool_error_code(exc), str(exc))
        finally:
            # Always drop the request-scoped project override (N10).
            _clear_request_project(_prior_project)

    return _err(rid, -32601, f"unknown method: {method}")


# Depth cap for _strip_nulls: deeply nested adversarial JSON (e.g. from web_fetch
# or a sql JSON column) could otherwise blow Python's recursion limit and turn
# benign data into a -32000 error. Beyond this depth we stop recursing and return
# the subtree untouched.
_STRIP_NULLS_MAX_DEPTH = 200


def _strip_nulls(value: Any, _depth: int = 0) -> Any:
    """Recursively remove None and "" values from response values.

    Strips:
      - None values
      - empty string values ""

    Keeps:
      - empty lists [] and dicts {} (semantic — "no items" is info)
      - numeric 0 / 0.0 (meaningful)
      - False (meaningful)
    """
    if _depth >= _STRIP_NULLS_MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {k: _strip_nulls(v, _depth + 1) for k, v in value.items() if v is not None and v != ""}
    if isinstance(value, list):
        return [_strip_nulls(item, _depth + 1) for item in value]
    return value


def _clean_tool_result(result: dict[str, Any], tool_name: str) -> dict[str, Any]:
    """Apply final response normalization before serialization."""
    _ = tool_name
    result = cast(dict[str, Any], _strip_nulls(result))
    return result


def _ok(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _tool_error_code(exc: Exception) -> int:
    if isinstance(exc, MemoryConcurrencyError):
        return 409
    if isinstance(exc, MemorySidecarUnavailable):
        return 503
    return -32000


def _mcp_max_workers() -> int:
    raw = os.environ.get("ATELIER_MCP_MAX_WORKERS", str(_DEFAULT_MCP_MAX_WORKERS))
    try:
        configured = int(raw)
    except ValueError:
        _log.warning(
            "invalid ATELIER_MCP_MAX_WORKERS=%r; using %d",
            raw,
            _DEFAULT_MCP_MAX_WORKERS,
        )
        return _DEFAULT_MCP_MAX_WORKERS
    return max(1, min(configured, _MAX_MCP_MAX_WORKERS))


_DEFAULT_MCP_HEAVY_WORKERS = 6
_MAX_MCP_HEAVY_WORKERS = 32
# Tools that can run for a long time (subprocess, network, mypy/pytest verify, or
# a workflow/agent spawn up to the 48h ceiling). They get a separate small
# executor lane so a burst can't evict cheap, frequent reads/searches from the
# main pool.
_HEAVY_TOOLS = frozenset({"shell", "run", "edit", "web_fetch", "workflow", "agent"})


def _mcp_heavy_max_workers() -> int:
    raw = os.environ.get("ATELIER_MCP_HEAVY_WORKERS", str(_DEFAULT_MCP_HEAVY_WORKERS))
    try:
        configured = int(raw)
    except ValueError:
        return _DEFAULT_MCP_HEAVY_WORKERS
    return max(1, min(configured, _MAX_MCP_HEAVY_WORKERS))


def _is_heavy_request(req: dict[str, Any]) -> bool:
    """True if this JSON-RPC request targets a long-running tool (heavy lane)."""
    if req.get("method") != "tools/call":
        return False
    params = req.get("params") or {}
    name = params.get("name") if isinstance(params, dict) else ""
    return name in _HEAVY_TOOLS


def _max_result_bytes() -> int:
    raw = os.environ.get("ATELIER_MCP_MAX_RESULT_BYTES", str(_DEFAULT_MAX_RESULT_BYTES))
    try:
        configured = int(raw)
    except ValueError:
        _log.warning(
            "invalid ATELIER_MCP_MAX_RESULT_BYTES=%r; using %d",
            raw,
            _DEFAULT_MAX_RESULT_BYTES,
        )
        return _DEFAULT_MAX_RESULT_BYTES
    # Floor avoids pathological tiny caps; ceiling keeps capped results safely
    # under the hard wire limit even after JSON string-escaping inflation.
    return max(64 * 1024, min(configured, _MAX_WIRE_BYTES - 1024 * 1024))


def _read_inline_budget_bytes() -> int:
    """Byte budget for a single inline file read before line-aligned truncation.

    Distinct from ``_max_result_bytes`` (the multi-MB host-disconnect wire guard):
    this is the much smaller threshold above which the *host's* MCP-output limit
    would persist the result to a temp file and make the agent re-read in blind
    ranges. Returning a line-aligned prefix with an exact continuation range keeps
    a whole-file read to a couple of clean calls. 0 disables the behavior.
    """
    raw = os.environ.get("ATELIER_READ_INLINE_BUDGET_BYTES", str(_DEFAULT_READ_INLINE_BUDGET_BYTES))
    try:
        configured = int(raw)
    except ValueError:
        return _DEFAULT_READ_INLINE_BUDGET_BYTES
    if configured <= 0:
        return 0
    return max(8 * 1024, configured)


def _truncate_result_text(text: str, limit: int) -> str:
    """Bound a tool-result string to *limit* UTF-8 bytes, appending a notice.

    A single oversized result would otherwise serialize into one JSON-RPC frame
    larger than the host's stdout guard, which disconnects the whole server.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    notice = (
        f"\n\n[atelier: result truncated to {limit} bytes to keep the MCP "
        f"connection alive ({len(encoded)} bytes total). Re-request a narrower slice — "
        'e.g. read with range="L1-L400", a tighter grep pattern, or smaller '
        "shell output.]"
    )
    headroom = max(0, limit - len(notice.encode("utf-8")))
    head = encoded[:headroom].decode("utf-8", "ignore")
    return head + notice


def _compact_result_chars() -> int:
    """Char threshold above which an oversized tool result is head+tail compacted.

    Distinct from the multi-MB wire guard (``_max_result_bytes``): that one only
    keeps the JSON-RPC frame under the host's stdout limit. This is a context-
    hygiene bound -- a single runaway result otherwise floods the host prompt and
    the host re-pays for it on every later turn. Set
    ``ATELIER_MCP_COMPACT_RESULT_CHARS=0`` to disable.
    """
    raw = os.environ.get("ATELIER_MCP_COMPACT_RESULT_CHARS", str(_DEFAULT_COMPACT_RESULT_CHARS))
    try:
        configured = int(raw)
    except ValueError:
        _log.warning(
            "invalid ATELIER_MCP_COMPACT_RESULT_CHARS=%r; using %d",
            raw,
            _DEFAULT_COMPACT_RESULT_CHARS,
        )
        return _DEFAULT_COMPACT_RESULT_CHARS
    return max(0, configured)


def _compact_result_text(text: str, tool_name: str) -> str:
    """Head+tail compact a single oversized tool result before it reaches the host.

    Deterministic (no LLM) so identical calls yield identical bytes and never
    bust the host's prefix cache. Keeps the head (command, first error, initial
    context) and the tail (final status/return value) with an omission marker in
    between, then appends a recovery hint. Results within the threshold pass
    through untouched.
    """
    threshold = _compact_result_chars()
    if threshold <= 0:
        return text
    # Gate on bytes, not just chars: a multibyte/CJK result can sit under the
    # char threshold while its UTF-8 footprint is several times larger and would
    # still flood the host prompt. len(text) is a lower bound on bytes, so only
    # pay the full encode when chars are under but bytes might exceed (x4 worst case).
    _over = len(text) > threshold
    if not _over and len(text) * 4 > threshold:
        _over = len(text.encode("utf-8")) > threshold
    if not _over:
        return text
    from atelier.core.capabilities.tool_supervision.compact_output import compress_tool_output

    target = max(4096, threshold // 4)
    head = int(target * 0.7)
    tail = max(1, target - head)
    compacted = compress_tool_output(text, threshold_chars=target, head_chars=head, tail_chars=tail)
    return (
        f"{compacted}\n\n[atelier: result compacted from {len(text)} chars to protect host "
        f"context; re-request a narrower slice (tighter {tool_name} query/range) for the full output]"
    )


# T7/T8 — tools whose oversized output is worth spilling/compacting reversibly.
# These produce expensive or non-idempotent output (shell side effects, sql
# query cost, large file reads, network fetches) where re-running to recover a
# truncated tail is wasteful or unsafe.
_SPILL_TOOLS = frozenset({"shell", "sql", "read", "web_fetch"})

_CODE_CONTENT_TOOLS = frozenset({"read"})


def _tool_output_spill_enabled() -> bool:
    """T7 flag: spill oversized output instead of discarding the overflow."""
    return os.environ.get("ATELIER_TOOL_OUTPUT_SPILL", "0").strip().lower() in {"1", "true", "yes", "on"}


def _auto_compact_output_enabled() -> bool:
    """T8 flag: auto-apply compact_output.compact() to oversized results."""
    return os.environ.get("ATELIER_AUTO_COMPACT_OUTPUT", "0").strip().lower() in {"1", "true", "yes", "on"}


def _read_path_arg(args: dict[str, Any]) -> str:
    """Best-effort extraction of the path a read-style call targeted."""
    raw = args.get("path") if isinstance(args, dict) else None
    if isinstance(raw, str) and raw:
        # A read path may carry a '#start-end' line-range suffix; strip it.
        return raw.split("#", 1)[0]
    return ""


def _auto_compact_result_text(text: str, tool_name: str, args: dict[str, Any]) -> str:
    """T8 — auto-apply compaction to an oversized result, reversibly.

    AST/structure-aware for code (uses the read-side source-projection compact so
    the projected view stays line-diffable); falls back to the deterministic
    head+tail compaction (``compact_output.compact``) for everything else.

    REVERSIBLE: the untransformed original is written to the T7 spill store and a
    recovery hint naming the ``compact`` retrieve op is appended, so the dropped
    detail is never lost. Flag-gated by ``ATELIER_AUTO_COMPACT_OUTPUT`` (off ->
    returns ``text`` unchanged).
    """
    if not _auto_compact_output_enabled():
        return text
    threshold = _compact_result_chars()
    if threshold <= 0 or len(text) <= threshold:
        return text

    from atelier.core.capabilities.tool_supervision import compact_output, tool_output_spill

    # 16x reduction from the char threshold: first chars/4 to estimate tokens
    # (the ~4-chars-per-token rule), then /4 again for headroom so the compacted
    # view lands well under the threshold. e.g. 256K chars -> ~16K-token budget.
    budget_tokens = max(256, threshold // 4 // 4)
    compacted_text = text
    method = "compact_output"

    # AST-aware path for code reads: project the source to its compact view.
    lang = ""
    if tool_name in _CODE_CONTENT_TOOLS:
        with contextlib.suppress(Exception):
            from atelier.core.capabilities.source_projection import build_compact_projection
            from atelier.infra.code_intel.languages import language_for_path

            lang_record = language_for_path(_read_path_arg(args))
            if lang_record is not None:
                lang = lang_record.name
                projection = build_compact_projection(text, lang)
                # Char-based gate (we budget in chars here): the projection is
                # token-neutral on pure whitespace but still trims bytes, which
                # is what shrinks the host-prompt footprint.
                if len(projection.content) < len(text):
                    compacted_text = projection.content
                    method = f"source_projection:{lang}"

    if compacted_text is text:
        compacted = compact_output.compact(
            text,
            content_type="file" if tool_name in _CODE_CONTENT_TOOLS else "tool_output",
            budget_tokens=budget_tokens,
        )
        compacted_text = compacted.compacted

    if len(compacted_text) >= len(text):
        return text  # compaction did not help — leave the original untouched.

    record = tool_output_spill.spill(
        text,
        tool_name=tool_name,
        kind="original",
        meta={"method": method, "path": _read_path_arg(args), "lang": lang},
    )
    if record is None:
        # Could not preserve the original -> do NOT lossily compact; return as-is
        # so the downstream wire guard handles it rather than dropping detail
        # irreversibly.
        return text
    return (
        f"{compacted_text}\n\n[atelier: result auto-compacted ({method}) from {len(text)} to "
        f"{len(compacted_text)} chars; ORIGINAL preserved at ref {record.ref_id}. Recover it "
        f'with the `compact` tool (op="retrieve", ref_id="{record.ref_id}").]'
    )


def _spill_oversized_result_text(
    text: str,
    tool_name: str,
    args: dict[str, Any],
    limit: int,
    *,
    unit: str = "bytes",
) -> str:
    """T7 — spill an over-budget result instead of discarding the overflow.

    When a ``shell``/``sql``/``read``/``web_fetch`` result exceeds the budget, the
    legacy path truncates/compacts and the middle is *lost*. Here the full,
    UNTRANSFORMED payload is written to the spill store and the host-facing text
    becomes a head/tail summary + the spill ref id + a retrieve hint, so the
    agent can pull the rest back without re-running the tool.

    M1 — the gate ``unit`` selects the budget basis: ``"chars"`` (compared
    against ``len(text)``) lets the spill fire at the legacy char threshold
    (``_compact_result_chars``), i.e. BEFORE ``_compact_result_text`` would have
    dropped the middle; ``"bytes"`` keeps the original wire-byte semantics.

    Flag-gated by ``ATELIER_TOOL_OUTPUT_SPILL`` and limited to ``_SPILL_TOOLS``
    (off / other tools -> returns ``text`` unchanged so the caller's existing
    compaction/truncation runs exactly as before).
    """
    if not _tool_output_spill_enabled() or tool_name not in _SPILL_TOOLS:
        return text
    measured = len(text) if unit == "chars" else len(text.encode("utf-8"))
    if limit <= 0 or measured <= limit:
        return text

    from atelier.core.capabilities.tool_supervision import tool_output_spill
    from atelier.core.capabilities.tool_supervision.compact_output import compress_tool_output

    record = tool_output_spill.spill(
        text,
        tool_name=tool_name,
        kind="tool_output",
        meta={"path": _read_path_arg(args), "limit": limit, "unit": unit},
    )
    if record is None:
        return text  # spill failed -> fall back to the legacy compaction/truncation.

    # A compact head+tail summary that comfortably fits the budget.
    summary_budget = limit if unit == "chars" else limit // 8
    target = max(4096, min(summary_budget, 16384))
    head = int(target * 0.7)
    tail = max(1, target - head)
    summary = compress_tool_output(text, threshold_chars=target, head_chars=head, tail_chars=tail)
    return tool_output_spill.summary_with_ref(summary, record, tool_name=tool_name, retrieve_op="compact")


def _write_jsonrpc(message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, sort_keys=True) + "\n"
    # Hard backstop: a frame above the host's ~16 MiB stdout guard disconnects
    # the server. Per-result capping should prevent this, but escaping overhead
    # or non-result frames could still exceed it — replace such a frame with
    # a small error so the session survives instead of dropping.
    if len(payload.encode("utf-8")) > _MAX_WIRE_BYTES and message.get("id") is not None:
        _log.warning(
            "jsonrpc frame exceeds %d bytes; replacing with error to protect the connection",
            _MAX_WIRE_BYTES,
        )
        message = _err(
            message["id"],
            -32000,
            f"result exceeded the {_MAX_WIRE_BYTES} byte MCP frame limit and was dropped to "
            "keep the connection alive; re-request a narrower slice.",
        )
        payload = json.dumps(message, ensure_ascii=False) + "\n"
    with _STDOUT_LOCK:
        sys.stdout.write(payload)
        sys.stdout.flush()


def _handle_and_write(request: dict[str, Any]) -> None:
    try:
        response = _handle(request)
    except Exception as exc:  # noqa: BLE001 - JSON-RPC worker boundary must return an error.
        _log.exception("unhandled MCP request failure")
        response = _err(request.get("id"), -32603, f"internal error: {exc}")
    if response is not None:
        _write_jsonrpc(response)


def serve() -> None:
    light_executor = ThreadPoolExecutor(
        max_workers=_mcp_max_workers(),
        thread_name_prefix="atelier",
    )
    # Separate small lane for genuinely long-running tools (shell, edit-with-verify,
    # web_fetch, and workflow/agent spawns up to the 48h ceiling) so a burst of them
    # can't saturate the pool and starve cheap, frequent reads/searches.
    heavy_executor = ThreadPoolExecutor(
        max_workers=_mcp_heavy_max_workers(),
        thread_name_prefix="atelier-heavy",
    )
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                _write_jsonrpc(_err(None, -32700, f"parse error: {exc}"))
                continue
            # Initialization establishes client capabilities and must complete
            # before later requests can observe them.
            if req.get("method") in {"initialize", "notifications/initialized"}:
                _handle_and_write(req)
                continue
            executor = heavy_executor if _is_heavy_request(req) else light_executor
            executor.submit(_handle_and_write, req)
    finally:
        light_executor.shutdown(wait=True, cancel_futures=False)
        heavy_executor.shutdown(wait=True, cancel_futures=False)
        _emit_mcp_session_end()
        from atelier.core.service.telemetry import shutdown_otel

        shutdown_otel()
        with contextlib.suppress(Exception):
            from atelier.gateway.integrations.langfuse import shutdown as _lf_shutdown

            _lf_shutdown()


def _setup_file_logging(root: str | Path) -> None:
    """Configure the atelier.mcp logger to write to a file.

    This ensures logs survive process termination and can be inspected
    via ``atelier logs mcp``.
    """
    log_dir = Path(root) / "mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "mcp.log"

    handler = logging.FileHandler(str(log_path), encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    mcp_logger = logging.getLogger("atelier.mcp")
    mcp_logger.addHandler(handler)
    mcp_logger.setLevel(logging.DEBUG)


def _warm_stdio_code_index() -> None:
    """Warm the single-workspace code-context engine for the stdio MCP path.

    Reuses the service ``_CodeWarmer`` patterns via ``warm_stdio_workspace``.
    Fail-open: any failure is swallowed so stdio server startup is unaffected.
    """
    try:
        from atelier.core.service.code_warm import warm_stdio_workspace

        warm_stdio_workspace(_workspace_root())
    except Exception:
        logging.exception("Recovered from broad exception handler")


def main() -> None:
    # Phase 1: Absorb wrapper logic into `atelier mcp` (zero-config)
    os.environ.setdefault("ATELIER_SERVICE_URL", "http://127.0.0.1:8787")
    # If no host has injected a workspace env var, detect the git repo root so
    # global-mode installs on any host always point at the project root.
    _HOST_WORKSPACE_VARS = ("CLAUDE_WORKSPACE_ROOT", "ATELIER_WORKSPACE_ROOT", "VSCODE_CWD")
    if not any(os.environ.get(v) for v in _HOST_WORKSPACE_VARS):
        try:
            import subprocess as _subprocess

            _git_result = _subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if _git_result.returncode == 0:
                os.environ["ATELIER_WORKSPACE_ROOT"] = _git_result.stdout.strip()
        except (OSError, _subprocess.SubprocessError):
            _log.debug("git rev-parse workspace-root detection failed", exc_info=True)
    os.environ.setdefault("ATELIER_WORKSPACE_ROOT", os.getcwd())
    os.environ.setdefault("ATELIER_LESSONS_ROOT", os.path.join(os.environ["ATELIER_WORKSPACE_ROOT"], ".lessons"))

    argv = sys.argv[1:]
    if "--version" in argv or "-V" in argv:
        sys.stdout.write(f"atelier mcp {SERVER_VERSION}\n")
        return
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            os.environ["ATELIER_ROOT"] = argv[i + 1]
    if "--host" in argv:
        i = argv.index("--host")
        if i + 1 < len(argv):
            os.environ["ATELIER_AGENT"] = argv[i + 1]

    # Set up file-based logging so logs survive process termination.
    atelier_root = os.environ.get("ATELIER_ROOT", str(Path.home() / ".atelier"))
    _setup_file_logging(atelier_root)

    # Register before serve() so the SessionStart hook can find this process
    # and write the Claude session UUID before the first tool call arrives.
    _register_mcp_session()

    # Warm the code-context engine/index once on stdio startup (G10) so the
    # first code-context tool call does not pay cold-start on Zoekt/scip/
    # ast-grep subprocesses. Off the hot path in a daemon thread; fail-open so
    # warming failure never breaks server startup.
    threading.Thread(target=_warm_stdio_code_index, daemon=True).start()

    threading.Thread(target=_check_auto_update, daemon=True).start()
    serve()


if __name__ == "__main__":
    main()
