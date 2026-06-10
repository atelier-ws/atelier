"""MCP server (stdio JSON-RPC) for the Atelier context runtime.

Implements a minimal subset of the Model Context Protocol sufficient for
Codex / Claude Code to discover and call the runtime tools.
"""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid as _uuid_mod
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal, cast

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
from atelier.core.capabilities.source_projection import SourceProjection
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
from atelier.infra.runtime.run_ledger import RunLedger
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


def mcp_tool(
    name: str | None = None,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[[dict[str, Any]], Any]]:
    """Decorator to register a tool and auto-derive its MCP schema."""

    def decorator(
        func: Callable[..., Any],
    ) -> Callable[[dict[str, Any]], Any]:
        tool_name = name or func.__name__.removeprefix("tool_")
        # Use the full docstring as the description so agents see all op detail.
        tool_description = description or (func.__doc__ or "").strip()

        sig = inspect.signature(func)
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
            ArgsModel = create_model(f"{func.__name__}_Args", **field_defs)  # type: ignore[call-overload]
            schema = ArgsModel.model_json_schema()
            # Clean up Pydantic-isms for MCP clients
            if "title" in schema:
                del schema["title"]

            @wraps(func)
            def handler_wrapper(args: dict[str, Any]) -> Any:
                validated = ArgsModel.model_validate(args)
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
_client_sampling_supported: bool = False
_sampling_seq: int = 0

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
_MCP_ID: str = f"atelier-mcp-{_uuid_mod.uuid4().hex[:16]}"
_cached_claude_session_id: str = ""
_cached_mcp_model: str = ""
_STDOUT_LOCK = threading.Lock()
_STATE_LOCK = threading.RLock()
_DEFAULT_MCP_MAX_WORKERS = 16
_MAX_MCP_MAX_WORKERS = 64


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
    with _STATE_LOCK:
        if _current_ledger is None:
            root = _atelier_root()
            _current_ledger = RunLedger(root=root, agent=_detect_agent())
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


def _emit_reasonblock_retrieved(scored: list[Any], domain: str | None) -> None:
    from atelier.core.service.telemetry import emit_product
    from atelier.core.service.telemetry.schema import hash_identifier

    for rank, item in enumerate(scored, start=1):
        block = getattr(item, "block", None)
        emit_product(
            "reasonblock_retrieved",
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
            runs_dir = Path(root) / "runs"
            return FileStateWriter(runs_dir / f"{led.session_id}_outcomes.json")
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

    Disabled by setting ``ATELIER_NO_AUTO_UPDATE=1`` in the environment.
    """
    import re
    import subprocess

    if os.environ.get("ATELIER_NO_AUTO_UPDATE") == "1":
        _log.info("auto-update disabled via ATELIER_NO_AUTO_UPDATE=1")
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
    _last_blocked_plan_hash_by_session.clear()
    _code_engine_cache.clear()
    _scoped_context_cache.clear()


def _live_savings_events_path() -> Path:
    return _atelier_root() / "live_savings_events.jsonl"


def _append_live_savings_event(event: dict[str, Any]) -> None:
    """Append a routing / compaction analytics event.

    Display savings ride the MCP response's content[].saved field into the
    transcript and are summed from there. This file remains the log for
    audit_export and cross_vendor_routing.advisor only.
    """
    path = _live_savings_events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
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
    decision = None
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
    completed = subprocess.run(
        command,
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
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
    runner: str | None = None,
    model: str | None = None,
    role_id: str = "",
    compiled_prompt: Any | None = None,
    spawn_envelope: dict[str, Any] | None = None,
    status: str,
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


def _default_workflow_tool_executor(step: Any, args: dict[str, Any], context_state: Any) -> Any:
    if step.tool == "workflow":
        raise ValueError("workflow cannot recursively invoke itself")
    spec = TOOLS.get(step.tool)
    if spec is None:
        raise ValueError(f"unknown workflow tool: {step.tool}")
    handler = cast(Callable[[dict[str, Any]], Any], spec["handler"])
    return handler(args)


def _default_workflow_shell_executor(step: Any, command: str, forked_context: dict[str, Any]) -> Any:
    spec = TOOLS.get("shell")
    if spec is None:
        raise ValueError("shell tool not registered")
    handler = cast(Callable[[dict[str, Any]], Any], spec["handler"])
    return handler({"command": command})


def _run_owned_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
    resume = bool(arguments.get("resume", False))
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
    runner_state = WorkflowContextState.from_mapping(runtime_state.get("runner")) if resume else WorkflowContextState()
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
    session_state = _read_workspace_session_state()
    if normalized_op == "status":
        return _coerce_workflow_runtime_status(session_state)
    if normalized_op == "inspect":
        return _inspect_workflow_runtime(session_state)
    if normalized_op not in {"pause", "resume", "stop"}:
        raise ValueError(f"unsupported workflow op: {op}")
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
    raise ValueError(f"unsupported workflow op: {op}")


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
        f"callees, usages, or impact first: {target_list}"
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
    # again on resume/compact with a different model.
    sid, model = _read_workspace_session_bridge()
    if sid and model:
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
    1. Claude: workspace bridge or MCP session file (both written exclusively by
       Claude Code's SessionStart hook — their presence is the reliable signal).
    2. All other hosts: native session-ID env var exposed to the MCP process.
    3. Fallback: workspace-scoped file (no per-session isolation).
    """
    # 1. Check the workspace bridge (written only by Claude Code's SessionStart hook).
    sid, _ = _read_workspace_session_bridge()
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
        return _atelier_root() / "session_stats" / "claude" / f"{sid}.jsonl"

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
    for env_var, host in _HOST_SESSION_ENVS:
        env_sid = os.environ.get(env_var, "").strip()
        if env_sid:
            return _atelier_root() / "session_stats" / host / f"{env_sid}.jsonl"

    return _workspace_savings_path()


def _context_savings_path(session_id: str) -> Path:
    """Per-session context-compression savings file, alongside the run ledger."""
    return _atelier_root() / "runs" / f"{session_id}_context_savings.jsonl"


def _current_context_state() -> tuple[int, str]:
    """Measured (context size, model) from the host transcript's last usage entry.

    Context size is input + cache_read + cache_creation tokens of the most
    recent usage entry; model is the one that produced it — the per-turn ground
    truth, unlike the SessionStart bridge which goes stale when the user
    switches models mid-session via /model. Returns (0, "") when no
    transcript/usage is available. Callers must treat 0/"" as "unknown" and
    skip pricing — never synthesize values.
    """
    try:
        from atelier.core.capabilities.savings_summary import (
            claude_transcript_candidates,
            is_real_model,
        )

        sid, _ = _read_workspace_session_bridge()
        if not sid:
            return 0, ""
        for cand in claude_transcript_candidates(sid):
            try:
                with cand.open("rb") as fh:
                    fh.seek(0, os.SEEK_END)
                    fh.seek(max(0, fh.tell() - 65536))
                    tail = fh.read().decode("utf-8", errors="replace")
            except OSError:
                continue
            best = 0
            best_model = ""
            for line in tail.splitlines():
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
                return best, best_model
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
    """Write per-call savings to two places:

    1. session_stats/<host>/<id>.jsonl  — host session UUID, read by statusline/stop hook
    2. runs/<ledger_session_id>_context_savings.jsonl — per-session, read by session report
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
    # --- sidecar for statusline / stop hook ---
    try:
        path = _get_host_session_sidecar_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "tool": tool_name,
            # Field names match the in-response `saved: {tokens, calls}` shape.
            # The file lives under session_stats/<host>/ so "savings" is implicit
            # from context — no need to suffix the keys.
            "tokens": int(tokens_saved),
            "calls": int(calls_saved),
            "model": model,
            "ts": ts,
        }
        if calls_usd > 0:
            entry["calls_usd"] = calls_usd
            entry["ctx_tokens"] = ctx_tokens
        if rid:
            entry["rid"] = rid
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        logging.exception("Recovered from broad exception handler")
        # Best-effort statusline sidecar; a failed write must not break the tool call.
        _log.debug("savings sidecar append failed", exc_info=True)
    # --- per-session context savings for session report / analytics ---
    try:
        led = _get_ledger()
        cost_saved = round(_price_tokens_saved_usd(model, tokens_saved), 6)
        event: dict[str, Any] = {
            "at": ts,
            "tool": tool_name,
            "model": model,
            "tokens_saved": int(tokens_saved),
            "calls_saved": int(calls_saved),
            "cost_saved_usd": cost_saved,
            "calls_cost_saved_usd": calls_usd,
        }
        if rid:
            event["rid"] = rid
        # Key the file by the Claude host session UUID (workspace bridge) when
        # available so that session_report.py can find savings via
        # runs/<uuid>_context_savings.jsonl — matching the UUID-keyed run ledger
        # files. Falls back to the MCP ledger hex session_id for non-Claude hosts.
        host_sid, _ = _read_workspace_session_bridge()
        cpath = _context_savings_path(host_sid or led.session_id)
        cpath.parent.mkdir(parents=True, exist_ok=True)
        with cpath.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except Exception:
        logging.exception("Recovered from broad exception handler")
        # Best-effort per-session savings ledger; a failed write must not break the tool call.
        _log.debug("context savings ledger append failed", exc_info=True)


def _append_workspace_savings(tool_name: str, tokens_saved: int, calls_saved: int, rid: str = "") -> None:
    """Backward-compat shim — delegates to _append_savings."""
    _append_savings(tool_name, tokens_saved, calls_saved, rid=rid)


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
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
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


def _workspace_root() -> Path:
    workspace = (
        os.environ.get("CLAUDE_WORKSPACE_ROOT")
        or os.environ.get("ATELIER_WORKSPACE_ROOT")
        or os.environ.get("VSCODE_CWD")
        or os.getcwd()
    )
    return Path(workspace)


# Thread-local slot for passing real tokens_saved from tool handlers to the
# budget recorder without polluting the LLM-facing response dict.
_tool_call_tokens_saved: threading.local = threading.local()
_tool_call_rendered_text: threading.local = threading.local()


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
    """Record task context and retrieve relevant ReasonBlocks for the task.

    Call this at the start of every task to seed your context with prior
    procedures, bootstrap repo knowledge, and per-agent memory.

    Pass mode="symbols" to surface the most relevant code symbols and files
    for the task (powered by the SCIP code index) instead of procedure blocks.

    Args:
        task:         Current task description (required). Drives block retrieval ranking.
        domain:       Optional domain tag (e.g. "python", "infra") to narrow retrieval.
        files:        File paths relevant to the task — boosts blocks associated with those files.
                      In mode="pull", these become the scoped subtask's affected_paths.
        keywords:     Optional explicit retrieval keywords. In mode="pull", these seed keyword retrieval.
        excluded_paths:
                      Optional path prefixes/globs to exclude. In mode="pull", these become
                      the scoped subtask's excluded_paths.
        tools:        Tools you plan to use — helps rank procedure blocks that match.
        errors:       Recent error messages — triggers rescue-mode block retrieval.
        max_blocks:   Maximum number of ReasonBlocks to inject (default 5).
        token_budget: Token cap for injected procedures (default 2000). Pass None for unlimited.
        dedup:        Deduplicate near-identical blocks before returning (default True).
        agent_id:     When set, loads per-agent archival memory passages via recall.
        recall:       Set False to skip archival memory recall entirely (default True).
        mode:         "procedures" (default) returns ReasonBlocks. "symbols" returns relevant
                      code symbols and files from the SCIP index for the given task.

    Returns a dict with:
        context:            Full context string ready to prepend to your prompt.
        bootstrap:          Repo bootstrap status (status, repo_id, queued, missing_labels).
        recalled_passages:  Per-agent memory passages (empty list when agent_id is None).
        tokens_breakdown:   Token counts by source (reasonblocks / bootstrap / memory / total).
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
    _monitor_composite, _fsm_skip_etraces = _advance_monitors(
        _get_product_session_id(), task, led.task or task
    )

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
                    kind=BlockKind.REASONBLOCK,
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


_TASK_TYPE_TO_ADVISOR_TOOL: dict[str, str] = {
    "debug": "shell",
    "feature": "edit",
    "refactor": "edit",
    "test": "context",
    "explain": "search",
    "review": "read",
    "docs": "compact",
    "ops": "shell",
}

_TIER_PRIORITY: dict[str, int] = {"cheap": 0, "medium": 1, "high": 2, "expensive": 2}


def _get_available_models() -> list[dict[str, Any]]:
    """Return models the current session can access, ordered cheapest-first."""
    from atelier.core.capabilities.counterfactual.pricing import load_pricing_table
    from atelier.core.capabilities.cross_vendor_routing.configuration import (
        detect_configured_vendors,
    )

    configured = set(detect_configured_vendors())
    return [
        {"vendor": c.vendor, "model_id": c.model_id, "tier": c.tier}
        for c in load_pricing_table().candidates
        if c.vendor in configured
    ]


def _compute_route_tier_for_response(tier: str, led: Any) -> str:
    """Map raw tier string to semantic RouteTier string for the route response."""
    from atelier.core.capabilities.model_routing.router import _detect_local_slm

    escalating = any(e.payload.get("escalate") for e in led.events if e.kind == "watchdog_alert")
    if escalating:
        return "human_review"
    if tier == "expensive":
        return "frontier_llm"
    if tier == "cheap" and _detect_local_slm():
        return "local_slm"
    return "cheap_llm"


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


def _sampling_invoke(prompt: str, model_hint: str, max_tokens: int) -> dict[str, Any]:
    """Send a sampling/createMessage request to the MCP client and return its response."""
    global _sampling_seq
    if not _client_sampling_supported:
        return {
            "sampling_supported": False,
            "error": (
                "Host does not support MCP sampling. Use the host agent's native sub-agent "
                "mechanism (e.g. Claude Code's Task tool) with model='" + model_hint + "'."
            ),
            "prompt": prompt,
            "model_hint": model_hint,
        }
    _sampling_seq += 1
    req_id = f"samp-{_sampling_seq}"
    request = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "sampling/createMessage",
        "params": {
            "messages": [{"role": "user", "content": {"type": "text", "text": prompt}}],
            "modelPreferences": {
                "hints": [{"name": model_hint}] if model_hint else [],
                "costPriority": 0.3,
                "speedPriority": 0.3,
                "intelligencePriority": 0.4,
            },
            "maxTokens": max_tokens,
            "includeContext": "none",
        },
    }
    sys.stdout.write(json.dumps(request, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            return {
                "sampling_supported": True,
                "error": "invalid sampling response from host",
                "model_used": None,
            }
        if msg.get("id") != req_id:
            # Unexpected message — process inline and keep waiting
            inline_resp = _handle(msg)
            if inline_resp is not None:
                sys.stdout.write(json.dumps(inline_resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            continue
        if "error" in msg:
            return {
                "sampling_supported": True,
                "error": msg["error"].get("message", "sampling failed"),
                "model_used": None,
            }
        result = msg.get("result", {})
        content = result.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content)
        return {
            "sampling_supported": True,
            "model_used": result.get("model", model_hint),
            "response": text,
            "stop_reason": result.get("stopReason", "end_turn"),
        }
    return {
        "sampling_supported": True,
        "error": "stdin closed before sampling response",
        "model_used": None,
    }


def _spawn_subprocess(prompt: str, model: str) -> dict[str, Any] | None:
    """Run a real agentic task via claude/codex CLI subprocess.

    Returns a result dict on success/error, or None if no supported CLI is found.
    The spawned process is a full agentic loop with tool access — not a single LLM call.
    """
    import subprocess as _sp

    for cli_name in ("claude", "codex"):
        cli = shutil.which(cli_name)
        if not cli:
            continue
        # -p (print mode): full agentic loop, exits when done; json output for structured parsing
        cmd = [
            cli,
            "-p",
            prompt,
            "--model",
            model,
            "--output-format",
            "json",
            "--no-session-persistence",
        ]
        try:
            result = _sp.run(cmd, capture_output=True, text=True, timeout=300)
        except _sp.TimeoutExpired:
            return {
                "spawn_method": "cli_subprocess",
                "error": "timeout: subprocess exceeded 300s",
                "model_used": model,
            }
        except Exception as exc:
            logging.exception("Recovered from broad exception handler")
            return {"spawn_method": "cli_subprocess", "error": str(exc), "model_used": model}

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return {
                    "spawn_method": "cli_subprocess",
                    "model_used": data.get("model", model),
                    "response": data.get("result", result.stdout),
                    "stop_reason": data.get("stop_reason", "end_turn"),
                    "cost_usd": data.get("cost_usd"),
                    "num_turns": data.get("num_turns", 1),
                }
            except json.JSONDecodeError:
                return {
                    "spawn_method": "cli_subprocess",
                    "model_used": model,
                    "response": result.stdout.strip(),
                    "stop_reason": "end_turn",
                }
        else:
            return {
                "spawn_method": "cli_subprocess",
                "error": f"CLI exited {result.returncode}: {result.stderr[:500]}",
                "model_used": model,
            }

    return None  # No supported CLI available


@mcp_tool(
    name="route",
    input_schema={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Describe what you are about to do so the router can pick the right model.",
            },
            "task_type": {
                "type": "string",
                "enum": [
                    "debug",
                    "feature",
                    "refactor",
                    "test",
                    "explain",
                    "review",
                    "docs",
                    "ops",
                ],
                "default": "feature",
                "description": "Task category — used to calibrate expected model complexity.",
            },
            "budget": {
                "type": "string",
                "enum": ["cheap", "balanced", "best"],
                "default": "balanced",
                "description": "Cost preference: cheap=lowest cost, balanced=smart default, best=highest quality.",
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "explicit"],
                "default": "auto",
                "description": "Owned route selection mode.",
            },
            "provider": {
                "type": "string",
                "description": "Explicit provider/vendor for owned execution when mode=explicit.",
            },
            "model": {
                "type": "string",
                "description": "Explicit model for owned execution when mode=explicit.",
            },
            "runner": {
                "type": "string",
                "description": "Optional runner profile override for the selected provider.",
            },
        },
        "required": [],
    },
)
def tool_route(
    task: str = "",
    task_type: Literal["debug", "feature", "refactor", "test", "explain", "review", "docs", "ops"] = "feature",
    budget: Literal["cheap", "balanced", "best"] = "balanced",
    mode: Literal["auto", "explicit"] = "auto",
    provider: str = "",
    model: str = "",
    runner: str = "",
) -> dict[str, Any]:
    """Pick the provider/model for an upcoming Atelier-owned subcall.

    `mode="auto"` lets policy choose from task class, budget, provider health, and cache warmth;
    `mode="explicit"` (or setting `provider`/`model`/`runner`) pins a route for control or benchmark isolation.

    Returns: {model, tier, route_tier, rationale} — echoes the resolved provider/model when explicit.
    """
    led = _get_ledger()

    led.record_tool_call(
        "route",
        {
            "task_type": task_type,
            "budget": budget,
            "mode": mode,
            "provider": provider,
            "model": model,
        },
    )
    available = _get_available_models()

    # Try the owned execution selector first so the route is executable, not advisory-only.
    chosen_model = ""
    tier = ""
    rationale = ""
    payload: dict[str, Any] = {}
    explicit_requested = mode == "explicit" or any(value.strip() for value in (provider, model, runner))
    try:
        from atelier.core.capabilities.cross_vendor_routing.configuration import RouteConfigError
        from atelier.core.capabilities.cross_vendor_routing.router import NoFeasibleRouteError

        advisor_tool = _TASK_TYPE_TO_ADVISOR_TOOL.get(task_type, "edit")
        decision = _select_owned_execution_route(
            tool_name=advisor_tool,
            task_text=task,
            mode=mode,
            provider=provider,
            model=model,
            runner=runner,
            session_state=_model_recommendation_state(led, {}),
        )
        payload = decision.to_dict()
        chosen_model = decision.model
        tier = decision.tier
        rationale = decision.reason
    except (RouteConfigError, NoFeasibleRouteError):
        if explicit_requested:
            raise
    except Exception:
        logging.exception("Recovered from broad exception handler")
        _log.debug("owned route selection failed", exc_info=True)

    # Apply budget override on top of advisor recommendation
    if budget == "cheap" and available:
        cheap_models = [m for m in available if m["tier"] == "cheap"]
        if cheap_models:
            chosen_model = cheap_models[0]["model_id"]
            tier = "cheap"
            rationale = "cheapest available model selected per budget=cheap"
    elif budget == "best" and available:
        expensive_models = sorted(
            available,
            key=lambda m: _TIER_PRIORITY.get(m["tier"], 0),
            reverse=True,
        )
        if expensive_models:
            chosen_model = expensive_models[0]["model_id"]
            tier = expensive_models[0]["tier"]
            rationale = "highest-capability available model selected per budget=best"

    # Final fallback: pick cheapest available model
    if not chosen_model and available:
        chosen_model = available[0]["model_id"]
        tier = available[0]["tier"]
        rationale = "fallback: cheapest configured model"

    # Emit route_tier using the semantic 5-tier model
    route_tier = _compute_route_tier_for_response(tier, led)

    payload.update(
        {
            "model": chosen_model,
            "tier": tier,
            "route_tier": payload.get("route_tier", route_tier),
            "rationale": rationale,
        }
    )
    return payload


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
            rescue_type="reasonblock" if matched else "summary",
            session_id=_get_product_session_id(),
        )

    # Lemma-style failure incident analysis from prior failed traces.
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
        for fpath in capture_files:
            try:
                p = Path(fpath)
                if not p.is_file():
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

    # Write learnings to archival memory (not ReasonBlocks - those are curated).
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

    # Kick off an immediate background consolidation tick so knowledge blocks
    # are extracted from this trace without waiting for the daemon's next cycle.
    threading.Thread(
        target=_run_worker_tick_safe,
        args=(_atelier_root(),),
        daemon=True,
    ).start()

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
            must_keep_keywords=list(led.active_reasonblocks),
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
    """Recall relevant archival memory passages."""
    return (
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
            "store_fact",
            "vote_fact",
        ],
        Field(
            description=(
                "Operation to execute. recall requires query; "
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
        str | None,
        Field(description="Scope for store_fact/vote_fact: repository or user."),
    ] = None,
    direction: Annotated[
        str | None,
        Field(description="Vote direction for vote_fact: upvote or downvote."),
    ] = None,
) -> dict[str, Any] | None:
    """Memory op-dispatch: recall, store_fact, or vote_fact."""

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
        lines.append("imports:")
        for imp in imports_list:
            lines.append(f"- {imp}")
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
        return json.dumps(result, ensure_ascii=False)
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


@mcp_tool(name="read")
def tool_smart_read(
    path: Annotated[
        str,
        Field(
            description="Workspace-relative file path to read.",
        ),
    ],
    range: str | None = None,
    expand: bool = False,
    max_lines: int | None = None,
    include_meta: Annotated[
        bool,
        Field(description="Include tool metadata fields (cache and token counters)."),
    ] = False,
) -> dict[str, Any]:
    """Read a file with automatic source projection for large files.

    Returns less context than native `Read` / `cat` for files >200 LOC:
      - outline mode: signatures, imports, structure -- no bodies.
        Measured token savings (tiktoken cl100k_base, median):
        Python 85%, Markdown 85%, Go 77%, Java 77%, Rust 65%.
        Tree-sitter outlines for: python, typescript, javascript, go, rust,
        java, ruby, c, c++, c#, kotlin, php, swift, scala, bash.
        Generic structural skeleton (column-0 declarations + signature lines)
        as a fallback for any other text-like language.
      - range mode (when range="42-118", range="L42-L118", or open-ended like "L42-"): exact line slice,
        cheaper than reading the whole file when you already know the range.
      - full mode: untransformed file text (for tiny files or expand=True).
      - compact projection: safe whitespace-only transformation on default full
        reads when it saves tokens; preserves strings and indentation-sensitive
        languages, but is not identical to the original text.

    Prefer over native `Read` whenever you don't already know the file is small.
    For files <200 LOC the cost is the same; for larger files outline mode
    typically saves 50-90% of the tokens you'd consume with `Read` / `cat`.

    Returns: {
      mode: "outline" | "range" | "full",
      language: str,                     # detected language (python, go, typescript, ...)
      outline: {kind, language, ...},    # only when mode == "outline"
      content: str,                      # only when mode in {range, full}
      path: str,
      range: str,                        # only when mode == "range"
      projection: {view, transformed, body_complete, untransformed_text, ...},
    }
    """
    target_path = path
    if not target_path:
        raise ValueError("provide path")
    if max_lines is not None and range is None and not expand:
        payload = cast(dict[str, Any], _core_runtime().smart_read(target_path, max_lines=max_lines))
        payload.setdefault("mode", "summary")
        payload["projection"] = SourceProjection.summary().to_dict()
        if include_meta:
            return payload
        payload.pop("cache_hit", None)
        payload.pop("tokens_saved", None)
        return payload

    target = _workspace_path(target_path)

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
                "Use `atelier_code op=files` to list indexed code files, "
                "or `atelier_grep` with `file_glob_patterns` to list non-code files."
            ),
        }

    cap = SemanticFileMemoryCapability(_atelier_root())
    payload = cap.smart_read(target, range_spec=range, expand=expand)
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
    compact = None
    exact_read = expand or range is not None
    if isinstance(content, str) and content and mode in ("full", "range") and not exact_read:
        from atelier.core.capabilities.source_projection import (
            ProjectionDelta,
            build_compact_projection,
        )

        language = str(payload.get("language") or "")
        compact = build_compact_projection(content, language, include_mapping=include_meta, path=str(target))
        if compact.applied:
            content = compact.content
            projection = SourceProjection.compact()
            projection_saved = compact.saved_tokens
            projection_delta = ProjectionDelta(
                path=str(payload.get("path", str(target))),
                lang=language,
                original_tokens=compact.original_tokens,
                projected_tokens=compact.projected_tokens,
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
    if include_meta:
        response["cache_hit"] = bool(payload.get("cache_hit", False))
        response["tokens_saved"] = ts
        if projection_delta is not None:
            response["projection_delta"] = projection_delta
        if compact is not None and compact.applied and compact.mapping is not None:
            response["projection_mapping"] = compact.mapping.to_dict()
    # Always save real savings via thread-local for the budget recorder
    if ts > 0:
        _tool_call_tokens_saved.value = ts
    return response


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


def _snapshot_paths(paths: dict[str, Path]) -> dict[str, tuple[Path, str | None]]:
    """Read each file's current content; None means the file does not exist."""
    snap: dict[str, tuple[Path, str | None]] = {}
    for display, fp in paths.items():
        try:
            snap[display] = (fp, fp.read_text(encoding="utf-8") if fp.exists() else None)
        except Exception:
            logging.exception("Recovered from broad exception handler")
            snap[display] = (fp, None)
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


def _existing_test_contract_paths(
    snapshots: dict[str, tuple[Path, str | None]],
    ) -> list[str]:
    return sorted(path for path, (_fp, old_content) in snapshots.items() if old_content is not None and _looks_like_test_path(path))


def _compute_and_record_diffs(    snapshots: dict[str, tuple[Path, str | None]],
) -> None:
    """Compute unified diffs from *snapshots* vs current file content and record them in the ledger."""
    import difflib

    led = _get_ledger()
    for path, (fp, old_content) in snapshots.items():
        try:
            new_content = fp.read_text(encoding="utf-8") if fp.exists() else None
        except Exception:
            logging.exception("Recovered from broad exception handler")
            new_content = None
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
        else:
            led.record_file_event(path=path, event="edit")


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


EDIT_TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "minItems": 1,
            "description": "Homogeneous edit descriptors. Do not mix legacy op/path descriptors with rich descriptors in one call.",
            "items": {
                "oneOf": [
                    {
                        "title": "Legacy replace",
                        "type": "object",
                        "required": ["path", "op", "old_string", "new_string"],
                        "properties": {
                            "path": {"type": "string"},
                            "op": {"const": "replace"},
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                            "fuzzy": {"type": "boolean"},
                        },
                        "additionalProperties": True,
                    },
                    {
                        "title": "Legacy insert_after",
                        "type": "object",
                        "required": ["path", "op", "anchor", "new_string"],
                        "properties": {
                            "path": {"type": "string"},
                            "op": {"const": "insert_after"},
                            "anchor": {"type": "string"},
                            "new_string": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                    {
                        "title": "Legacy replace_range",
                        "type": "object",
                        "required": ["path", "op", "line_start", "line_end", "new_string"],
                        "properties": {
                            "path": {"type": "string"},
                            "op": {"const": "replace_range"},
                            "line_start": {"type": "integer", "minimum": 1},
                            "line_end": {"type": "integer", "minimum": 1},
                            "new_string": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                    {
                        "title": "Rich file edit",
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
                        "additionalProperties": True,
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
                        "additionalProperties": True,
                    },
                    {
                        "title": "Symbol edit",
                        "type": "object",
                        "required": ["kind"],
                        "properties": {
                            "kind": {"const": "symbol"},
                            "symbol_id": {"type": "string"},
                            "qualified_name": {"type": "string"},
                            "symbol_name": {"type": "string"},
                            "name": {"type": "string"},
                            "file_path": {"type": "string"},
                            "mode": {"enum": ["replace", "prepend", "append"]},
                            "new_body": {"type": "string"},
                            "preserve_signature": {"type": "boolean"},
                        },
                        "additionalProperties": True,
                    },
                ]
            },
        },
        "atomic": {
            "type": "boolean",
            "default": True,
            "description": "Roll back all edits if any one descriptor fails. Set false only when partial success is acceptable.",
        },
        "post_edit_hooks": {
            "type": "boolean",
            "default": True,
            "description": "Run post-edit hooks (formatter, linter, LSP diagnostics) on touched files. Diagnostics appear in the result.",
        },
        "post_edit_timeout_ms": {
            "type": "integer",
            "default": 30000,
            "minimum": 0,
            "description": "Maximum total timeout for post-edit hooks in milliseconds.",
        },
    },
    "required": ["edits"],
    "additionalProperties": False,
}


@mcp_tool(name="edit", input_schema=EDIT_TOOL_INPUT_SCHEMA)
def tool_smart_edit(
    edits: list[dict[str, Any]],
    atomic: bool = True,
    post_edit_hooks: bool = True,
    post_edit_timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Apply many mechanical edits across files in one deterministic call.

    Choose the right descriptor family for each edit (all must be the same family):

    Rich (preferred) — ``file_path`` required:
      - Replace text:    {file_path, old_string, new_string}
      - Create/overwrite:{file_path, new_string, overwrite: true}
      - Line-scoped:     {file_path: "foo.py#10-20", old_string, new_string}
      - Notebook cell:   {file_path, cell_action: insert_after|delete|..., new_string}
      - Symbol:          {kind: "symbol", symbol_id|qualified_name|name, mode, new_body}

    Legacy — ``path`` + ``op`` required:
      - replace:       {path, op: "replace", old_string, new_string, fuzzy?}
      - insert_after:  {path, op: "insert_after", anchor, new_string}
      - replace_range: {path, op: "replace_range", line_start, line_end, new_string}

    Returns: {applied, failed, rolled_back, writes?}
    """
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    repo_root = Path(workspace)
    family = _validate_edit_descriptor_families(edits)

    paths = _collect_touched_paths(edits, repo_root=repo_root)
    snapshots = _snapshot_paths(paths)

    if family == "rich":
        from atelier.core.capabilities.tool_supervision.rich_edit import apply_rich_edits

        result = apply_rich_edits(edits, atomic=atomic, repo_root=repo_root)
    else:
        from atelier.core.capabilities.tool_supervision.batch_edit import apply_batch_edit

        result = apply_batch_edit(edits, atomic=atomic, repo_root=repo_root)

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
        _compute_and_record_diffs(snapshots)
        contract_paths = _existing_test_contract_paths(snapshots)
        if contract_paths:
            result["contract_review"] = {
                "required": True,
                "paths": contract_paths,
                "guidance": (
                    "Existing tests are behavioral-contract evidence. Do not change them merely to make a failure pass; "
                    "verify that the task or another repository source of truth explicitly requires the contract change."
                ),
            }
    result.pop("diagnostics", None)
    result.pop("hooks", None)    # Batched edits collapse N would-be individual edit calls into 1.
    # Use successful applies as the count; the dispatcher reads this and
    # writes it into the response's content[].saved.calls field.
    applied_count = len(result.get("applied") or [])
    if applied_count > 1:
        result.setdefault("calls_saved", applied_count - 1)
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
                "connect: discover DB + overview. tables: table names + count. schema: columns + foreign keys "
                "per table. table: one table's columns + FKs (needs name). relationships: foreign-key graph. "
                "search: keyword over table/column names -> matching tables with columns + FKs (needs name). "
                "lint: validate SQL without running it (needs sql). query: execute SQL (needs sql or queries[])."
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
            "description": "Batch of named queries for action=query: [{name, sql}, ...]. Prefer over repeated query calls.",
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
            "description": "Explicit DSN (sqlite:///path, postgresql://...). Auto-discovered from DATABASE_URL env or .env if omitted.",
        },
        "max_rows": {
            "type": "integer",
            "default": 500,
            "description": "Row cap for query results.",
        },
        "allow_writes": {
            "type": "boolean",
            "default": True,
            "description": "Set false to reject INSERT/UPDATE/DELETE/DROP.",
        },
        "auto_limit": {
            "type": "boolean",
            "default": True,
            "description": "Automatically append LIMIT max_rows when missing.",
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
    allow_writes: bool = True,
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
    run_dir = root / "runs" / led.session_id
    run_dir.mkdir(parents=True, exist_ok=True)
    handover_path = run_dir / "HANDOVER.md"
    packet = HandoverPacket.from_ledger(led, state, workspace_root=_workspace_root())
    handover_path.write_text(packet.to_markdown(), encoding="utf-8")
    return handover_path


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
        state = ContextCompressor().compress(led, preserve_last_n_turns=10, workspace_root=_workspace_root())
        compaction_savings = _session_compaction_savings_payload(
            led,
            state,
            tokens_before=int(lifecycle["tokens_used"]),
            trigger="compact_advise",
            reason=str(lifecycle["reason"]),
            utilisation_pct=utilisation_pct,
        )

        # Collect preserve_blocks: top active ReasonBlocks from ledger
        preserve_blocks = list(set(led.active_reasonblocks))[:3]

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
                f"Please preserve these ReasonBlocks: {', '.join(preserve_blocks) or '(none yet)'}. "
                f"Recently edited files: {', '.join(open_files) or '(none)'}. "
                "Preserve the last 10 raw turns, active errors, and current CLAUDE.md hash."
            )

        # Persist manifest to disk
        try:
            root = _atelier_root()
            run_dir = root / "runs" / led.session_id
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
                "preserve_blocks": preserve_blocks,
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
            "preserve_blocks": preserve_blocks,
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
            "preserve_blocks": [],
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
                engine = CodeContextEngine(resolved)
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
# Keep: provenance (data quality/source), repo_name (multi-repo), origin (external vs internal scope).
_CODE_OP_TOP_STRIP: frozenset[str] = frozenset(
    {
        "symbol_id",
        "cache_hit",
        "rendered_format",
        "repo_id",
        "total_tokens",
        "tokens_saved",
        "provenance_breakdown",
        "mode",
        "view",
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


def _strip_code_op_response(op: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Remove internal/telemetry fields that waste LLM context."""
    drop = _CODE_OP_TOP_STRIP | _CODE_OP_EXTRA_STRIP.get(op, frozenset())
    if op == "search":
        keep = {"mode", "provenance", "view"}
        if payload.get("provenance") != "graveyard":
            keep.add("cache_hit")
        drop = frozenset(key for key in drop if key not in keep)
    result: dict[str, Any] = {k: v for k, v in payload.items() if k not in drop}

    # Save real tokens_saved via thread-local so _record_context_budget_for_tool
    # can read it without polluting the LLM-facing response.
    ts = int(payload.get("tokens_saved", 0) or 0)
    if ts > 0:
        _tool_call_tokens_saved.value = ts

    # Strip internal keys from the target object
    if isinstance(result.get("target"), dict):
        result["target"] = {k: v for k, v in result["target"].items() if k not in _CODE_OP_ITEM_STRIP}

    # Strip internal keys from list fields
    for field in _CODE_OP_ITEM_LIST_FIELDS:
        lst = result.get(field)
        if isinstance(lst, list):
            result[field] = [
                {k: v for k, v in item.items() if k not in _CODE_OP_ITEM_STRIP} if isinstance(item, dict) else item
                for item in lst
            ]

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


_CODE_SEARCH_SUGGESTED_NEXT = (
    {"op": "usages", "query": "{query}"},
    {"op": "context", "query": "{query}"},
)


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
        "score": item.get("score"),
        "role": item.get("role") or "definition",
        "deleted_at": item.get("deleted_at"),
        "deleted_at_sha": item.get("deleted_at_sha"),
        "rename_target": item.get("rename_target"),
        "rename_note": item.get("rename_note"),
    }
    return {key: value for key, value in result.items() if value is not None}


def _code_search_suggested_next(query: str) -> list[dict[str, str]]:
    return [
        {key: value.format(query=query) for key, value in suggestion.items()}
        for suggestion in _CODE_SEARCH_SUGGESTED_NEXT
    ]


def _code_search_target_view(payload: dict[str, Any], *, query: str) -> dict[str, Any]:
    items = payload.get("items")
    if isinstance(items, list):
        payload["items"] = [_code_search_target_item(item) if isinstance(item, dict) else item for item in items]
    if payload.get("items"):
        payload["has_more_context"] = True
        payload["suggested_next"] = _code_search_suggested_next(query)
    payload["view"] = "target"
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
            "view": view,
            "mode": search_payload.get("mode"),
            "provenance": search_payload.get("provenance"),
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
        "view": view,
        "mode": "lexical+graph" if view == "explain" else "graph",
        "provenance": search_payload.get("provenance"),
    }
    if view == "explain":
        payload["items"] = [
            _code_search_target_item(item) if isinstance(item, dict) else item
            for item in cast(list[Any], search_payload.get("items", []))
        ]
        payload["explanation"] = (
            "items are primary search targets; related contains graph evidence from usages, " "callers, and callees."
        )
        payload["suggested_next"] = _code_search_suggested_next(query)
    return payload


SYMBOLS_TOOL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Symbol name or natural-language description. "
                "Use an identifier ('MyClass', 'module.MyClass.method') for lexical/hybrid lookup, "
                "or a description ('function that handles HTTP errors') for semantic search."
            ),
        },
        "symbol_name": {
            "type": "string",
            "description": "Short unqualified symbol name (internal, prefer query).",
        },
        "qualified_name": {
            "type": "string",
            "description": "Fully qualified dotted path (internal).",
        },
        "symbol_id": {
            "type": "string",
            "description": "Stable SCIP symbol ID from a prior result (internal).",
        },
        "mode": {
            "type": "string",
            "enum": ["auto", "lexical", "semantic", "hybrid"],
            "default": "auto",
            "description": "'auto': picks best mode. 'lexical': exact identifier match. 'semantic': description/intent match.",
        },
        "intent": {
            "type": "string",
            "enum": ["auto", "symbol", "text", "semantic"],
            "default": "auto",
            "description": (
                "Search intent. 'symbol' forces symbol-index search for functions/classes/variables; "
                "'text' forces local text/substring search; 'semantic' forces semantic search; "
                "'auto' uses query heuristics."
            ),
        },
        "view": {
            "type": "string",
            "enum": ["target", "graph", "context", "explain"],
            "default": "target",
            "description": (
                "Response shape for op='search'. "
                "'target' returns primary definition/file matches only. "
                "'graph' returns relationships for the best target. "
                "'context' returns a broader code context pack. "
                "'explain' returns targets plus ranking/graph evidence."
            ),
        },
        "kind": {
            "type": "string",
            "description": "Filter by symbol kind: 'function', 'method', 'class', 'variable', etc.",
        },
        "language": {
            "type": "string",
            "description": "Filter by language: 'python', 'typescript', etc.",
        },
        "limit": {"type": "integer", "default": 20, "description": "Maximum results to return."},
        "snippet": {
            "type": "string",
            "enum": ["none", "head", "full"],
            "default": "none",
            "description": "Source snippet in results: 'none' (smallest), 'head' (first N lines), 'full'.",
        },
        "snippet_lines": {
            "type": "integer",
            "default": 8,
            "description": "Lines when snippet='head'.",
        },
        "file_glob": {
            "type": "string",
            "description": "Restrict to a subtree, e.g. 'src/api/**/*.py'.",
        },
        "repo_root": {
            "type": "string",
            "description": "Optional absolute or workspace-relative repository root override for local code-intel operations.",
        },
        "scope": {
            "type": "string",
            "enum": ["repo", "external", "deleted"],
            "default": "repo",
            "description": "'repo': live symbols. 'external': dependencies. 'deleted': git graveyard.",
        },
        "since": {
            "type": "string",
            "description": "ISO date or relative ('7d') to filter to recently changed.",
        },
    },
}


@mcp_tool(name="symbols", input_schema=SYMBOLS_TOOL_INPUT_SCHEMA)
def tool_symbols(
    op: str = "search",
    repo: str | None = None,
    repo_root: str | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    query: str | None = None,
    pattern: str | None = None,
    rewrite: str | None = None,
    limit: int = 20,
    mode: Literal["auto", "lexical", "semantic", "hybrid"] = "auto",
    intent: Literal["auto", "symbol", "text", "semantic"] = "auto",
    view: Literal["target", "graph", "context", "explain"] = "target",
    kind: str | None = None,
    language: str | None = None,
    snippet: Literal["none", "head", "full"] = "none",
    snippet_lines: int = 8,
    group_by: Literal["file", "caller", "none"] = "file",
    depth: int = 1,
    snapshot: bool = False,
    file_glob: str | None = None,
    scope: Literal["repo", "external", "deleted"] = "repo",
    since: str | None = None,
    touched_by: str | None = None,
    include_churn: bool = True,
    symbol_id: str | None = None,
    qualified_name: str | None = None,
    symbol_name: str | None = None,
    path: str | None = None,
    max_files: int = 8,
    include_source: bool = True,
    include_relationships: bool = True,
    line_numbers: bool = True,
    line: int | None = None,
    col: int | None = None,
    new_name: str | None = None,
    rename_backend: Literal["auto", "rope", "ts-morph", "ast-grep", "naive"] = "auto",
    seed_files: list[str] | None = None,
    budget_tokens: int = 4000,
    max_symbols: int = 4,
    dry_run: bool = True,
    cache_tool: (
        Literal[
            "all",
            "search",
            "symbol",
            "outline",
            "context",
            "impact",
            "usages",
            "callers",
            "callees",
            "pattern",
            "hover",
            "explore",
        ]
        | None
    ) = None,
    render_compact: bool = False,
    provenance: str | None = None,
    force: bool = False,  # op=index only: True = full rebuild, False = incremental (default)
) -> dict[str, Any]:
    """Search the SCIP code index for symbols by name or description.

    Prefer over `grep` for symbol lookup — results are exact (not textual), indexed, and token-budgeted.
    Use `grep` for regex on arbitrary text. Use `search` for ranked file/snippet retrieval.

    For `op="search"`, `view` controls response shape: `target` locates primary
    definitions/files, `graph` returns relationships for the best target, `context`
    returns a broader context pack, and `explain` combines targets with graph evidence.

    For call-graph, reference, and structural work use the dedicated tools:
    `node` (read a definition), `callers` / `callees` (call graph), `usages`
    (all references), `impact` (blast radius), `pattern` (AST search/rewrite),
    `explore` (grouped context).
    """
    if op == "node":
        op = "symbol"
    engine_root = repo_root or "."
    workspace_router = _workspace_code_router(engine_root)
    if repo is not None and not workspace_router.is_configured:
        raise ValueError("repo filter requires .atelier/workspace.toml")
    if repo is not None and op not in {"search", "symbol"}:
        raise ValueError("repo filter is only supported for workspace search and symbol operations")

    engine = _code_context_engine(engine_root)
    _code_engine_for_current_call.value = engine

    if op == "index":
        return _maybe_attach_code_rendered(
            op,
            cast(
                dict[str, Any],
                engine.tool_index(
                    include_globs=include_globs,
                    exclude_globs=exclude_globs,
                    force=force,
                    budget_tokens=budget_tokens,
                ),
            ),
            render_compact=render_compact,
        )

    if op == "search":
        if not query:
            raise ValueError("query is required for code search")
        if view == "context":
            context_payload = engine.tool_context(
                task=query,
                seed_files=seed_files,
                budget_tokens=budget_tokens,
                max_symbols=max_symbols,
            )
            context_payload["view"] = "context"
            return _maybe_attach_code_rendered(
                "context",
                cast(dict[str, Any], context_payload),
                render_compact=render_compact,
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
            routed_payload = _code_search_target_view(routed_payload, query=query)
            if view in {"graph", "explain"}:
                routed_payload["view"] = view
            return _maybe_attach_code_rendered(
                op,
                routed_payload,
                render_compact=render_compact,
            )
        search_payload = cast(dict[str, Any], engine.tool_search(query, **search_kwargs))
        if view == "target":
            search_payload = _code_search_target_view(search_payload, query=query)
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
        return _maybe_attach_code_rendered(
            op,
            search_payload,
            render_compact=render_compact,
        )

    if op == "blame":
        if not (query or symbol_id or qualified_name or symbol_name):
            raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code blame")
        return _maybe_attach_code_rendered(
            op,
            cast(
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
            ),
            render_compact=render_compact,
        )

    if op == "hover":
        if not any([symbol_id, qualified_name, symbol_name, query, (path and line is not None)]):
            raise ValueError(
                "symbol_id, qualified_name, symbol_name, query, or (file_path + line) is required for hover"
            )
        return _maybe_attach_code_rendered(
            op,
            cast(
                dict[str, Any],
                engine.tool_hover(
                    symbol_id=symbol_id,
                    qualified_name=qualified_name,
                    symbol_name=symbol_name or query,
                    file_path=path,
                    line=line,
                    col=col,
                    budget_tokens=budget_tokens,
                ),
            ),
            render_compact=render_compact,
        )

    if op == "symbol":
        if workspace_router.is_configured:
            return _maybe_attach_code_rendered(
                op,
                cast(
                    dict[str, Any],
                    workspace_router.route(
                        "symbol",
                        repo=repo,
                        symbol_id=symbol_id,
                        qualified_name=qualified_name,
                        symbol_name=symbol_name,
                        file_path=path,
                        budget_tokens=budget_tokens,
                    ),
                ),
                render_compact=render_compact,
            )
        return _maybe_attach_code_rendered(
            op,
            cast(
                dict[str, Any],
                engine.tool_symbol(
                    symbol_id=symbol_id,
                    qualified_name=qualified_name,
                    symbol_name=symbol_name,
                    file_path=path,
                    budget_tokens=budget_tokens,
                ),
            ),
            render_compact=render_compact,
        )

    if op == "outline":
        return _maybe_attach_code_rendered(
            op,
            cast(
                dict[str, Any],
                engine.tool_outline(file_path=path, limit=limit, budget_tokens=budget_tokens),
            ),
            render_compact=render_compact,
        )

    if op == "explore":
        if not query:
            raise ValueError("query is required for code explore")
        return _maybe_attach_code_rendered(
            op,
            cast(
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
            ),
            render_compact=render_compact,
        )

    if op in {"routes", "status", "files", "context"}:
        raise ValueError(
            f"op={op!r} is no longer available on this tool. "
            "Use: `context` tool with mode='symbols' (was context), "
            "`grep` (was files), status/routes are retired."
        )

    if op == "pattern":
        if not pattern:
            raise ValueError("pattern is required for code pattern")
        return _maybe_attach_code_rendered(
            op,
            cast(
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
            ),
            render_compact=render_compact,
        )

    if op == "usages":
        if not any([query, symbol_id, qualified_name, symbol_name]):
            raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code usages")
        return _maybe_attach_code_rendered(
            op,
            cast(
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
            ),
            render_compact=render_compact,
        )

    if op == "callers":
        if not any([query, symbol_id, qualified_name, symbol_name]):
            raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code callers")
        return _maybe_attach_code_rendered(
            op,
            cast(
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
            ),
            render_compact=render_compact,
        )

    if op == "callees":
        if not any([query, symbol_id, qualified_name, symbol_name]):
            raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code callees")
        return _maybe_attach_code_rendered(
            op,
            cast(
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
            ),
            render_compact=render_compact,
        )

    if op == "rename":
        if not new_name:
            raise ValueError("new_name is required for code rename")
        if not any([query, symbol_id, qualified_name, symbol_name]):
            raise ValueError("query, symbol_id, qualified_name, or symbol_name is required for code rename")
        from atelier.core.capabilities.tool_supervision.rename_symbol import build_rename_edits

        workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
        edits = build_rename_edits(
            engine,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name or query,
            file_path=path,
            new_name=new_name,
            repo_root=Path(workspace),
            backend=rename_backend,
        )
        # Filter out ast-grep sentinel entries (already applied on disk)
        rich_edits = [e for e in edits if not e.get("_astgrep_applied")]
        if not rich_edits and edits:
            # ast-grep applied everything directly; return summary
            return _maybe_attach_code_rendered(
                op,
                {
                    "op": "rename",
                    "files_changed": len(edits),
                    "backend": "ast-grep",
                    "new_name": new_name,
                },
                render_compact=render_compact,
            )
        from atelier.core.capabilities.tool_supervision.rich_edit import apply_rich_edits

        touched = _collect_touched_paths(rich_edits, repo_root=Path(workspace))
        snaps = _snapshot_paths(touched)
        result = apply_rich_edits(rich_edits, atomic=True, repo_root=Path(workspace))
        if not result.get("failed") and not result.get("rolled_back"):
            _compute_and_record_diffs(snaps)
        result["op"] = "rename"
        result["new_name"] = new_name
        result["backend"] = rename_backend
        return _maybe_attach_code_rendered(op, result, render_compact=render_compact)

    if op == "cache_status":
        if cache_tool is None:
            return _maybe_attach_code_rendered(
                op,
                cast(dict[str, Any], engine.tool_cache_status(budget_tokens=budget_tokens)),
                render_compact=render_compact,
            )
        return _maybe_attach_code_rendered(
            op,
            cast(
                dict[str, Any],
                engine.tool_cache_status(cache_tool=cache_tool, budget_tokens=budget_tokens),
            ),
            render_compact=render_compact,
        )

    if op == "cache_invalidate":
        if cache_tool is None:
            return _maybe_attach_code_rendered(
                op,
                cast(dict[str, Any], engine.tool_cache_invalidate(budget_tokens=budget_tokens)),
                render_compact=render_compact,
            )
        return _maybe_attach_code_rendered(
            op,
            cast(
                dict[str, Any],
                engine.tool_cache_invalidate(cache_tool=cache_tool, budget_tokens=budget_tokens),
            ),
            render_compact=render_compact,
        )

    if op == "impact":
        if not any([path, query, symbol_id, qualified_name, symbol_name]):
            raise ValueError("path or symbol identifier is required for code impact")
        return _maybe_attach_code_rendered(
            op,
            cast(
                dict[str, Any],
                engine.tool_impact(
                    path,
                    query=query,
                    symbol_id=symbol_id,
                    qualified_name=qualified_name,
                    symbol_name=symbol_name,
                    file_path=path,
                    kind=kind,
                    language=language,
                    file_glob=file_glob,
                    budget_tokens=budget_tokens,
                ),
            ),
            render_compact=render_compact,
        )

    raise ValueError(f"unknown op: {op!r}")


# Normalize "code:callers" → "callers" etc. so legacy callers using the
# "code:" prefix alias convention still route correctly.
_raw_tool_symbols_handler = TOOLS["symbols"]["handler"]


# Result keys that represent batched discoveries — each item would have
# required its own naive grep/read in a side-by-side baseline.
_CODE_BATCH_KEYS: tuple[str, ...] = (
    "matches",
    "callers",
    "callees",
    "usages",
    "results",
    "items",
    "files",
    "symbols",
    "routes",
)


def _tool_symbols_alias_handler(args: dict[str, Any]) -> dict[str, Any]:
    op = args.get("op")
    if isinstance(op, str) and op.startswith("code:"):
        args = {**args, "op": op[5:]}
    result: dict[str, Any] = _raw_tool_symbols_handler(args)
    # Infer calls_saved for batched ops: each list-of-items result represents
    # N findings that would have cost N naive calls (grep + read + scan).
    if isinstance(result, dict) and "calls_saved" not in result:
        for key in _CODE_BATCH_KEYS:
            items = result.get(key)
            if isinstance(items, list) and len(items) > 1:
                result["calls_saved"] = len(items) - 1
                break
    return result


TOOLS["symbols"]["handler"] = _tool_symbols_alias_handler
tool_symbols = _tool_symbols_alias_handler  # noqa: F811
tool_code = _tool_symbols_alias_handler

# ------------------------------------------------------------------ #
# Dedicated code-intel tools — thin wrappers over the `symbols` op.  #
# Dedicated names let LLMs pick the right tool without knowing the   #
# op parameter; each has a focused schema and clear description.      #
# ------------------------------------------------------------------ #

_CODE_INTEL_TOOLS: frozenset[str] = frozenset({"node", "callers", "callees", "impact", "explore"})


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
    or SCIP id (from a prior search/callers result). Or use path+line for positional lookup.
    """
    kwargs: dict[str, Any] = {"op": "node"}
    if symbol:
        kwargs.update(_parse_symbol(symbol))
    if path:
        kwargs["path"] = path
    if line is not None:
        kwargs["line"] = line
    return _tool_symbols_alias_handler(kwargs)


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
    return _tool_symbols_alias_handler({"op": "callers", **_parse_symbol(symbol), "depth": depth, "limit": limit})


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
    return _tool_symbols_alias_handler({"op": "callees", **_parse_symbol(symbol), "depth": depth, "limit": limit})


@mcp_tool(name="impact")
def tool_impact(
    query: str,
) -> dict[str, Any]:
    """Blast radius for a file or symbol — all files/symbols affected by changing it.

    Use before refactoring to understand scope.
    Pass a file path (e.g. 'src/auth.py') for file-level, or a symbol name/qualified path/scip-id for symbol-level.
    Returns: files grouped by reason (calls, imports, inherits, etc.).
    """
    result = _tool_symbols_alias_handler({"op": "impact", "query": query})
    if isinstance(result, dict) and "affected_files" in result:
        result["files"] = result.pop("affected_files")
    return result


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
    return _tool_symbols_alias_handler(
        {"op": "explore", "query": query, "seed_files": seed_files, "max_files": max_files}
    )


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
    return _tool_symbols_alias_handler({"op": "usages", **_parse_symbol(symbol), "limit": limit})


@mcp_tool(name="pattern")
def tool_pattern(
    pattern: str,
    language: str | None = None,
    file_glob: str | None = None,
    rewrite: str | None = None,
    limit: int = 20,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Structural (AST) search and optional rewrite via ast-grep.

    Prefer over `grep` when you want to match code *shape* rather than text:
    e.g. `$X == None`, `if ($C) { $$$ }`, a call with specific argument forms.
    Pass `rewrite` to transform matches; `dry_run=True` (default) previews
    changes without writing. Use `language` (e.g. 'python') and `file_glob` to
    scope the search.
    Returns: matches (snippet, file_path, line) -- or, with rewrite and dry_run=False, {files_changed, total_rewrites}.
    """
    return _tool_symbols_alias_handler(
        {
            "op": "pattern",
            "pattern": pattern,
            "language": language,
            "file_glob": file_glob,
            "rewrite": rewrite,
            "limit": limit,
            "dry_run": dry_run,
        }
    )


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
        run_command,
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
        return poll_managed_command(session_id, cancel=action == "cancel")
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

    sync_limit = max(1, int(os.environ.get("ATELIER_MCP_SYNC_SHELL_MAX_SECONDS", "90")))
    if background or timeout > sync_limit:
        return start_managed_command(
            command,
            cwd=effective_cwd,
            timeout=timeout,
            max_lines=max_lines,
        )

    result = run_command(
        command,
        cwd=effective_cwd,
        timeout=timeout,
        max_lines=max_lines,
    )
    response: dict[str, Any] = {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "truncated": result.truncated,
        "lines_omitted": result.lines_omitted,
        "duration_ms": result.duration_ms,
    }
    if result.policy_action == "block":
        response["blocked"] = True
        response["blocked_reason"] = result.policy_reason
    if result.lines_omitted > 0:
        # chars_omitted / 4 is the standard chars-per-token estimate.
        _tool_call_tokens_saved.value = result.chars_omitted // 4
    return response


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
        "grep-style matching, path listing, context lines, summaries, or incremental reruns."
    ),
)
def tool_grep(
    path: Annotated[
        str,
        Field(
            description=("Workspace-relative file or directory to search."),
        ),
    ] = ".",
    content_regex: Annotated[
        str | None,
        Field(
            description=(
                "Regular expression to match file contents. Leave unset when you only want "
                "globbed file paths or type-filtered file listings."
            )
        ),
    ] = None,
    file_glob_patterns: Annotated[
        list[str] | None,
        Field(description="Glob patterns that constrain candidate files, such as `src/**/*.py`."),
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
                "`ranked_file_map` (default): token-budgeted pointers with line ranges and symbols — best for navigation. "
                "`file_paths_with_content`: matched lines with context — best for reading content. "
                "`file_paths_only`: just paths — best for listings. "
                "`file_paths_with_match_count`: paths with hit counts — best for frequency analysis."
            )
        ),
    ] = "ranked_file_map",
    lines_before: Annotated[
        int,
        Field(description="Number of context lines to include before each content match."),
    ] = 0,
    lines_after: Annotated[
        int,
        Field(description="Number of context lines to include after each content match."),
    ] = 0,
    ignore_case: Annotated[
        bool,
        Field(description="Ignore case while matching `content_regex`."),
    ] = False,
    type: Annotated[
        str | None,
        Field(
            description=(
                "Language or file-type filter, such as `python`, `markdown`, or another " "supported type alias."
            )
        ),
    ] = None,
    file_limit: Annotated[
        int | None,
        Field(description="Maximum number of matching files to render."),
    ] = None,
    lines_per_file: Annotated[
        int | None,
        Field(
            description="Cap the number of matched lines rendered per file (applies to `file_paths_with_content` mode)."
        ),
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
        Field(description=("Enable multiline regex matching so `.` spans newlines and `^` / `$` work per line.")),
    ] = False,
    summary: Annotated[
        bool | None,
        Field(
            description=(
                "Control structural summarization of matched files. "
                "Omit (default): auto — summarizes Python/JS/TS files over 500 LOC. "
                "`true`: always summarize (signatures and imports only). "
                "`false`: never summarize (always return raw matched lines)."
            )
        ),
    ] = None,
    context_budget_tokens: Annotated[
        int,
        Field(
            description=(
                "Token budget that caps output size. For `ranked_file_map` mode this limits "
                "the number of file handles returned; for `file_paths_with_content` it caps "
                "total rendered characters. Default 6000 is suitable for most queries."
            )
        ),
    ] = 6000,
    include_meta: Annotated[
        bool,
        Field(description="Include response metadata such as file counts and caps."),
    ] = False,
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


@mcp_tool(
    name="search",
    description=(
        "Search code and docs by ranked query. Use this for relevance-ranked snippets, "
        "full-file ranked reads, or repo maps seeded from known files. Use `grep` for "
        "regex, glob, type-filter, or context-line search, then escalate with `node`, "
        "`callers`, `callees`, `usages`, `impact`, or `explore` once grounded."
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
                "description": "Workspace-relative file or directory to search.",
            },
            "mode": {
                "type": "string",
                "enum": ["chunks", "map"],
                "default": "chunks",
                "description": (
                    "`chunks` returns ranked snippets per file, and `map` builds a repo map " "from `seed_files`."
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
            description="Workspace-relative file or directory to search.",
        ),
    ] = ".",
    mode: Annotated[
        Literal["chunks", "map"],
        Field(
            description=("`chunks` returns ranked snippets per file, and `map` builds a repo map " "from `seed_files`.")
        ),
    ] = "chunks",
    max_files: Annotated[
        int,
        Field(description="Maximum number of ranked files to return."),
    ] = 10,
    max_chars_per_file: Annotated[
        int,
        Field(
            description=("Cap the returned characters per ranked file before the overall token " "budget is applied.")
        ),
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
) -> dict[str, Any]:
    """Search by ranked query or repo-map construction, then hand off to node/explore-style code intel.

    - Pass `query` for relevance-ranked search over code and docs.
    - Use `mode='chunks'` for snippets.
    - Use `mode='map'` with `seed_files` to build a repo map.
    - Use `grep` instead when you need regex, glob, type filters, summaries, or incremental reruns.
    - Once grounded, use `node`, `callers`, `callees`, `usages`, `impact`, or `explore` for exact code-intel follow-up.
    """
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


def _compact_tool_output(
    content: str,
    content_type: str = "unknown",
    budget_tokens: int = 500,
    recovery_hint: str | None = None,
) -> dict[str, Any]:
    """Compact large tool output with deterministic or Ollama-backed methods."""
    from atelier.core.capabilities.tool_supervision.compact_output import compact

    result = compact(
        content=content,
        content_type=content_type,
        budget_tokens=budget_tokens,
        recovery_hint=recovery_hint,
    )
    return result.model_dump(mode="json")


def _compact_score(
    complexity: float,
    must_keep: list[str],
) -> dict[str, Any]:
    """Record the model's self-assessed complexity and must-keep keywords.

    Parameters
    ----------
    complexity:
        Float 0.0-1.0. 0 = trivial/read-only, 1.0 = deep debugging or
        large refactor with many interdependencies.
    must_keep:
        Keywords or short phrases the model needs preserved verbatim.
    """
    complexity = max(0.0, min(1.0, float(complexity)))
    return {
        "complexity": complexity,
        "must_keep_count": len(must_keep),
        "message": (
            f"Complexity {complexity:.2f} scored with {len(must_keep)} must-keep hints; "
            "persisted to ledger for advise and session compaction."
        ),
    }


@mcp_tool(name="compact")
def tool_compact(
    session_id: Annotated[
        str | None,
        Field(description="Optional run-ledger session ID override. Usually omit."),
    ] = None,
) -> dict[str, Any]:
    """Compress the full run ledger into a compact session state block."""
    return cast(dict[str, Any], _compress_context(session_id=session_id))


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
            "default": 30,
            "description": "Seconds before the command is killed. Increase for slow builds.",
        },
        "max_lines": {
            "type": "integer",
            "default": 200,
            "description": "Max output lines. Excess lines are head+tail truncated; check truncated=true in response.",
        },
        "background": {
            "type": "boolean",
            "default": False,
            "description": "Start immediately as a managed session. Commands whose timeout exceeds the synchronous MCP window are detached automatically.",
        },
        "session_id": {
            "type": "string",
            "description": "Managed shell session returned by a background or automatically detached run.",
        },
        "action": {
            "type": "string",
            "enum": ["run", "poll", "cancel"],
            "default": "run",
            "description": "Run a command, poll a managed session, or cancel it.",
        },
    },
    "additionalProperties": False,
}


@mcp_tool(name="shell", input_schema=SHELL_TOOL_INPUT_SCHEMA)
def tool_shell(
    command: str = "",
    timeout: int = 30,
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
        return "reasonblock_inject"
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


def _route_outcome_calibration(tool_name: str, session_state: Mapping[str, Any]) -> dict[str, Any]:
    from atelier.infra.runtime.outcome_capture import load_outcomes_from_state

    outcomes = load_outcomes_from_state(_workspace_session_state_file())
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
    session_state.update(_route_outcome_calibration(tool_name, session_state))
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
        global _client_sampling_supported
        _client_sampling_supported = "sampling" in (params.get("capabilities") or {})
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
            for n, s in TOOLS.items()
            if _tool_visible_to_llm(n, s)
        ]
        return _ok(rid, {"tools": tools})

    if method == "tools/call":
        name = params.get("name") or ""
        if name == "run":
            name = "shell"
        args = params.get("arguments") or {}
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
        rendered_text: str | None = None
        try:
            if remote_routed:
                result = _dispatch_remote(name, args)
                if isinstance(result, dict):
                    result = _clean_tool_result(result, name)
            else:
                led = _get_ledger()
                route_payload, route_state, route_workflow, route_step = _prepare_model_recommendation(
                    name,
                    args if isinstance(args, dict) else {},
                    led,
                )
                handler: Callable[[dict[str, Any]], dict[str, Any]] = spec["handler"]
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
                    with active_model_override(wrapper_model or None):
                        result = handler(args)
                finally:
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
                if name in {"symbols"} | _CODE_INTEL_TOOLS:
                    rendered_text = getattr(_tool_call_rendered_text, "value", None)
                elif name == "read":
                    with contextlib.suppress(Exception):
                        rendered_text = _render_read_md(result if isinstance(result, dict) else {})
                elif name == "grep":
                    with contextlib.suppress(Exception):
                        rendered_text = _render_grep_md(result if isinstance(result, dict) else {})
                elif name == "search":
                    with contextlib.suppress(Exception):
                        rendered_text = _render_search_md(result if isinstance(result, dict) else {})
                elif name == "shell":
                    with contextlib.suppress(Exception):
                        rendered_text = _render_shell_text(result if isinstance(result, dict) else {})
                elif name == "web_fetch":
                    with contextlib.suppress(Exception):
                        rendered_text = str((result if isinstance(result, dict) else {}).get("content") or "")

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

            response_text: str
            if rendered_text:
                response_text = rendered_text
            elif isinstance(result, str):
                response_text = result
            else:
                response_text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))

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
                    if _dedup_outcome is not None:
                        stub_text, dedup_chars_saved = _dedup_outcome
                        response_text = stub_text
                        dedup_stubbed = True
                        if dedup_chars_saved > 0:
                            _append_workspace_savings(name, dedup_chars_saved // 4, 0, rid=str(rid))
            # Embed real savings on the content item itself so the values
            # land in the Claude transcript JSONL. Statusline / analytics /
            # frontends read the transcript and sum these — no side files,
            # no session-id filter, no model-resolution dance.
            # Shape: {"tokens": int, "calls": int}. Either may be 0 but the
            # object is omitted entirely when both are 0.
            content_item: dict[str, Any] = {
                "type": "text",
                "text": response_text,
            }
            # Mark large responses for ephemeral caching. Claude Code forwards
            # cache_control from MCP tool results to the Anthropic API, turning
            # repeated large context reads into cheap cache hits. Anthropic
            # requires ≥1024 tokens (~4096 chars) for a cache checkpoint to be
            # eligible; smaller responses are not worth the write overhead.
            if len(response_text) >= 4096:
                content_item["cache_control"] = {"type": "ephemeral"}
            # When deduped, skip the original per-call savings and structuredContent
            # (which would otherwise re-carry the full bytes we just elided).
            if not dedup_stubbed and isinstance(result, dict):
                saved_tokens = _extract_tokens_saved(result)
                saved_calls = _coerce_saved_tokens(result.get("calls_saved"))
                if saved_tokens > 0 or saved_calls > 0:
                    content_item["saved"] = {
                        "tokens": int(saved_tokens),
                        "calls": int(saved_calls),
                    }
                    _append_workspace_savings(name, saved_tokens, saved_calls, rid=str(rid))

            response_payload: dict[str, Any] = {"content": [content_item]}
            if not dedup_stubbed and isinstance(result, dict):
                response_payload["structuredContent"] = result
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
            return _err(rid, _tool_error_code(exc), str(exc))

    return _err(rid, -32601, f"unknown method: {method}")


def _strip_nulls(value: Any) -> Any:
    """Recursively remove None and "" values from response values.

    Strips:
      - None values
      - empty string values ""

    Keeps:
      - empty lists [] and dicts {} (semantic — "no items" is info)
      - numeric 0 / 0.0 (meaningful)
      - False (meaningful)
    """
    if isinstance(value, dict):
        return {k: _strip_nulls(v) for k, v in value.items() if v is not None and v != ""}
    if isinstance(value, list):
        return [_strip_nulls(item) for item in value]
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


def _write_jsonrpc(message: dict[str, Any]) -> None:
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
    executor = ThreadPoolExecutor(
        max_workers=_mcp_max_workers(),
        thread_name_prefix="atelier-mcp",
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
            executor.submit(_handle_and_write, req)
    finally:
        executor.shutdown(wait=True, cancel_futures=False)
        _emit_mcp_session_end()
        from atelier.core.service.telemetry import shutdown_otel

        shutdown_otel()


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


def main() -> None:
    # Phase 1: Absorb wrapper logic into atelier-mcp (zero-config)
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
        sys.stdout.write(f"atelier-mcp {SERVER_VERSION}\n")
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

    threading.Thread(target=_check_auto_update, daemon=True).start()
    serve()


if __name__ == "__main__":
    main()
