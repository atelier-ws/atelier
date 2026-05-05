"""MCP server (stdio JSON-RPC) for the Atelier reasoning runtime.

Implements a minimal subset of the Model Context Protocol sufficient for
Codex / Claude Code to discover and call the runtime tools.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import Field, create_model

from atelier.core.capabilities.archival_recall import ArchivalRecallCapability
from atelier.core.capabilities.lesson_promotion import LessonPromoterCapability
from atelier.core.capabilities.semantic_file_memory import SemanticFileMemoryCapability
from atelier.core.foundation.memory_models import MemoryBlock
from atelier.core.foundation.models import RawArtifact, Trace, to_jsonable
from atelier.core.foundation.plan_checker import check_plan
from atelier.core.foundation.redaction import redact
from atelier.core.foundation.rubric_gate import run_rubric
from atelier.gateway.adapters.runtime import ReasoningRuntime
from atelier.infra.embeddings.factory import make_embedder
from atelier.infra.runtime.realtime_context import RealtimeContextManager
from atelier.infra.runtime.run_ledger import RunLedger
from atelier.infra.storage.factory import make_memory_store
from atelier.infra.storage.memory_store import MemoryConcurrencyError, MemorySidecarUnavailable

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "atelier-reasoning"
SERVER_VERSION = "0.1.0"


# --------------------------------------------------------------------------- #
# Tool Registry Decorator                                                     #
# --------------------------------------------------------------------------- #

TOOLS: dict[str, dict[str, Any]] = {}


def mcp_tool(
    name: str | None = None, description: str | None = None
) -> Callable[[Callable[..., Any]], Callable[[dict[str, Any]], Any]]:
    """Decorator to register a tool and auto-derive its MCP schema."""

    def decorator(
        func: Callable[..., Any],
    ) -> Callable[[dict[str, Any]], Any]:
        tool_name = name or func.__name__.removeprefix("tool_")
        # Use the first line of the docstring as the description
        tool_description = description or (func.__doc__ or "").strip().split("\n")[0]

        sig = inspect.signature(func)
        fields = {}
        for param_name, param in sig.parameters.items():
            annotation = (
                param.annotation if param.annotation is not inspect.Parameter.empty else Any
            )
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
            def handler_wrapper(args: dict[str, Any]) -> Any:
                return func()

        TOOLS[tool_name] = {
            "handler": handler_wrapper,
            "description": tool_description,
            "inputSchema": schema,
        }
        return handler_wrapper

    return decorator


# --------------------------------------------------------------------------- #
# session_state.json helpers                                                  #
# --------------------------------------------------------------------------- #

_current_ledger: RunLedger | None = None
_realtime_ctx: RealtimeContextManager | None = None


def _detect_agent() -> str:
    """Derive the agent label from the runtime environment.

    Checks, in order:
    1. ATELIER_AGENT env var (explicit override — any host can set this)
    2. CLAUDE_SESSION_ID → "claude"
    3. GEMINI_SESSION_ID or GEMINI_CLI_VERSION → "gemini"
    4. CODEX_SESSION_ID → "codex"
    5. OPENCODE_SESSION_ID → "opencode"
    6. Falls back to "claude" (the MCP wrapper is shipped with the Claude plugin)
    """
    explicit = os.environ.get("ATELIER_AGENT", "").strip()
    if explicit:
        return explicit
    if os.environ.get("CLAUDE_SESSION_ID"):
        return "claude"
    if os.environ.get("GEMINI_SESSION_ID") or os.environ.get("GEMINI_CLI_VERSION"):
        return "gemini"
    if os.environ.get("CODEX_SESSION_ID"):
        return "codex"
    if os.environ.get("OPENCODE_SESSION_ID"):
        return "opencode"
    # Default: the plugin lives in the Claude Code plugin system
    return "claude"


def _get_ledger() -> RunLedger:
    global _current_ledger
    if _current_ledger is None:
        root = _atelier_root()
        _current_ledger = RunLedger(root=root, agent=_detect_agent())
        # Publish run_id AND atelier_root to session_state so PostToolUse hooks
        # can find the right run file regardless of ATELIER_ROOT in their env.
        _write_session_state(
            {
                "active_run_id": _current_ledger.run_id,
                "atelier_root": str(root),
            }
        )
    return _current_ledger


def _get_realtime_context() -> RealtimeContextManager:
    global _realtime_ctx
    if _realtime_ctx is None:
        _realtime_ctx = RealtimeContextManager(_atelier_root())
    return _realtime_ctx


_context_budget_recorder: Any = None


def _get_context_budget_recorder() -> Any:
    """Get or create the ContextBudgetRecorder singleton."""
    global _context_budget_recorder
    if _context_budget_recorder is None:
        try:
            from atelier.core.capabilities.telemetry.context_budget import ContextBudgetRecorder
            from atelier.infra.storage.factory import create_store

            store = create_store(_atelier_root())
            store.init()
            _context_budget_recorder = ContextBudgetRecorder(store)
        except Exception:
            # If recording fails, return a no-op recorder
            _context_budget_recorder = _NoOpContextBudgetRecorder()
    return _context_budget_recorder


def _parse_report_since(value: str) -> tuple[timedelta, datetime]:
    now = datetime.now(UTC)
    match = re.fullmatch(r"(\d+)([dhm])", value.strip())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            return timedelta(days=amount), now
        if unit == "h":
            return timedelta(hours=amount), now
        return timedelta(minutes=amount), now

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("since_iso must be a duration like 7d or an ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = now - parsed.astimezone(UTC)
    if delta.total_seconds() <= 0:
        raise ValueError("since_iso must be earlier than now")
    return delta, now


class _NoOpContextBudgetRecorder:
    """No-op recorder for when context budget recording is not available."""

    def record(self, **kwargs: Any) -> None:
        """No-op record method."""
        pass

    def aggregate_run(self, run_id: str) -> Any:
        """No-op aggregate method."""
        return {}


def _session_state_path() -> Path:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    return Path(workspace) / ".atelier" / "session_state.json"


def _read_session_state() -> dict[str, Any]:
    p = _session_state_path()
    if not p.exists():
        return {}
    try:
        import typing

        return typing.cast(dict[str, Any], json.loads(p.read_text("utf-8")))
    except Exception:
        return {}


def _write_session_state(updates: dict[str, Any]) -> None:
    try:
        p = _session_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        state = _read_session_state()
        state.update(updates)

        if updates.get("trace_recorded"):
            session_id = os.environ.get("CLAUDE_SESSION_ID", "")
            if session_id:
                sessions: dict[str, Any] = state.setdefault("sessions", {})
                sessions[session_id] = {"trace_recorded": True}

        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Tool implementations                                                        #
# --------------------------------------------------------------------------- #


def _atelier_root() -> Path:
    return Path(os.environ.get("ATELIER_ROOT", ".atelier"))


def _runtime() -> ReasoningRuntime:
    return ReasoningRuntime(_atelier_root())


_REDACTION_PLACEHOLDER_RE = re.compile(r"<redacted[^>]*>")


def _lesson_promoter() -> LessonPromoterCapability:
    return LessonPromoterCapability(_runtime().store)


def _core_runtime() -> Any:
    return _runtime().core_runtime


def _redact_memory_input(text: str, field_name: str) -> str:
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


def _workspace_path(file_path: str) -> Path:
    p = Path(file_path)
    if p.is_absolute():
        return p
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    return Path(workspace) / p


@mcp_tool(name="atelier_get_reasoning_context")
def tool_get_reasoning_context(
    task: str,
    domain: str | None = None,
    files: list[str] | None = None,
    tools: list[str] | None = None,
    errors: list[str] | None = None,
    max_blocks: int = 5,
    token_budget: int | None = 2000,
    dedup: bool = True,
    include_telemetry: bool = False,
    agent_id: str | None = None,
    recall: bool = True,
) -> dict[str, Any]:
    """Retrieve relevant ReasonBlocks for a task and render them as injection context."""
    if errors is None:
        errors = []
    if tools is None:
        tools = []
    if files is None:
        files = []
    rt = _runtime()
    led = _get_ledger()
    led.task = task
    if domain:
        led.domain = domain

    led.record_tool_call(
        "get_reasoning_context",
        {
            "task": task,
            "domain": domain,
            "files": files,
            "tools": tools,
            "errors": errors,
            "max_blocks": max_blocks,
            "token_budget": token_budget,
            "dedup": dedup,
            "include_telemetry": include_telemetry,
            "agent_id": agent_id,
            "recall": recall,
        },
    )

    payload = rt.get_reasoning_context(
        task=task,
        domain=domain,
        files=files,
        tools=tools,
        errors=errors,
        max_blocks=max_blocks,
        token_budget=token_budget,
        dedup=dedup,
        include_telemetry=include_telemetry,
        agent_id=agent_id,
        recall=recall,
    )
    return payload if isinstance(payload, dict) else {"context": payload}


@mcp_tool(name="atelier_check_plan")
def tool_check_plan(
    task: str,
    plan: list[str],
    domain: str | None = None,
    files: list[str] | None = None,
    tools: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Validate a proposed agent plan against ReasonBlocks. Returns status pass|warn|blocked."""
    if errors is None:
        errors = []
    if tools is None:
        tools = []
    if files is None:
        files = []
    rt = _runtime()
    led = _get_ledger()
    led.set_plan(plan)

    led.record_tool_call(
        "check_plan",
        {
            "task": task,
            "plan": plan,
            "domain": domain,
            "files": files,
            "tools": tools,
            "errors": errors,
        },
    )

    result = check_plan(
        rt.store,
        task=task,
        plan=plan,
        domain=domain,
        files=files,
        tools=tools,
        errors=errors,
    )

    if result.matched_blocks:
        for b_id in result.matched_blocks:
            if b_id not in led.active_reasonblocks:
                led.active_reasonblocks.append(b_id)

    if getattr(result, "status", None) in ("ok", "warn", "pass"):
        _write_session_state({"last_plan_check_ok_ts": time.time()})

    return to_jsonable(result)


@mcp_tool(name="atelier_route_decide")
def tool_route_decide(
    user_goal: str,
    repo_root: str,
    task_type: Literal["debug", "feature", "refactor", "test", "explain", "review", "docs", "ops"],
    risk_level: Literal["low", "medium", "high"],
    changed_files: list[str] | None = None,
    domain: str | None = None,
    step_type: Literal[
        "classify",
        "compress",
        "retrieve",
        "plan",
        "edit",
        "debug",
        "verify",
        "summarize",
        "lesson_extract",
    ] = "plan",
    step_index: int = 0,
    evidence_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute a deterministic quality-aware route decision from runtime evidence."""
    rt = _runtime()
    led = _get_ledger()

    if changed_files is None:
        changed_files = []
    if evidence_summary is None:
        evidence_summary = {}

    led.record_tool_call(
        "route_decide",
        {
            "task_type": task_type,
            "risk_level": risk_level,
            "changed_files": changed_files,
            "domain": domain,
            "step_type": step_type,
            "step_index": step_index,
        },
    )

    decision = rt.route_decide(
        user_goal=user_goal,
        repo_root=repo_root,
        task_type=task_type,
        risk_level=risk_level,
        changed_files=changed_files,
        domain=domain,
        step_type=step_type,
        step_index=step_index,
        run_id=led.run_id,
        evidence_summary=evidence_summary,
        ledger=led,
    )
    return to_jsonable(decision)


@mcp_tool(name="atelier_route_verify")
def tool_route_verify(
    route_decision_id: str,
    changed_files: list[str] | None = None,
    validation_results: list[dict[str, Any]] | None = None,
    rubric_status: Literal["not_run", "pass", "warn", "fail"] = "not_run",
    required_verifiers: list[str] | None = None,
    protected_file_match: bool = False,
    repeated_failure_signatures: list[str] | None = None,
    diff_line_count: int = 0,
    human_accepted: bool | None = None,
    benchmark_accepted: bool | None = None,
) -> dict[str, Any]:
    """Convert observed verification signals into pass/warn/fail/escalate routing outcome."""
    rt = _runtime()
    led = _get_ledger()

    if changed_files is None:
        changed_files = []
    if validation_results is None:
        validation_results = []
    if required_verifiers is None:
        required_verifiers = []
    if repeated_failure_signatures is None:
        repeated_failure_signatures = []

    led.record_tool_call(
        "route_verify",
        {
            "route_decision_id": route_decision_id,
            "changed_files": changed_files,
            "rubric_status": rubric_status,
            "required_verifiers": required_verifiers,
            "protected_file_match": protected_file_match,
            "repeated_failure_signatures": repeated_failure_signatures,
            "diff_line_count": diff_line_count,
            "human_accepted": human_accepted,
            "benchmark_accepted": benchmark_accepted,
        },
    )

    envelope = rt.core_runtime.quality_router.verify(
        route_decision_id=route_decision_id,
        run_id=led.run_id,
        changed_files=changed_files,
        validation_results=validation_results,
        rubric_status=rubric_status,
        required_verifiers=required_verifiers,
        protected_file_match=protected_file_match,
        repeated_failure_signatures=repeated_failure_signatures,
        diff_line_count=diff_line_count,
        human_accepted=human_accepted,
        benchmark_accepted=benchmark_accepted,
    )
    return to_jsonable(envelope)


@mcp_tool(name="atelier_route_contract")
def tool_route_contract(
    host: Literal["claude", "codex", "copilot", "opencode", "gemini"],
) -> dict[str, Any]:
    """Return the routing execution contract for a named host (WP-31).

    The contract states whether Atelier can enforce route decisions on the host
    (advisory / wrapper_enforced) or only advise.  The provider_enforced mode
    is always disabled until a provider execution packet enables it.
    """
    from atelier.core.capabilities.quality_router.execution_contract import (
        route_execution_contract,
    )

    contract = route_execution_contract(host)
    return to_jsonable(contract)


@mcp_tool(name="atelier_proof_report")
def tool_proof_report(
    run_id: str | None = None,
    context_reduction_pct: float | None = None,
) -> dict[str, Any]:
    """Return the cost-quality proof report (WP-32).

    When ``run_id`` is provided a new proof run is executed and saved to
    ``.atelier/proof/proof-report.json``.  When ``run_id`` is omitted the last
    saved report is loaded and returned.

    ``context_reduction_pct`` is the WP-19 context savings percentage.  If
    omitted and a new run is requested, a default of 55.0 is used (the
    deterministic savings bench result for the seeded 11-prompt suite).
    """
    from atelier.core.capabilities.proof_gate.capability import (
        BenchmarkCase,
        ProofGateCapability,
    )

    rt = _runtime()
    capability: ProofGateCapability = rt.core_runtime.proof_gate

    if run_id is not None:
        # Build deterministic cases (same logic as CLI `proof run`)
        _CASES: list[dict[str, Any]] = [
            {
                "case_id": f"{run_id}:cheap-01",
                "task_type": "coding",
                "tier": "cheap",
                "accepted": True,
                "cost_usd": 0.002,
                "trace_id": f"{run_id}:trace:cheap-01",
                "run_id": run_id,
                "verifier_outcome": "pass",
            },
            {
                "case_id": f"{run_id}:cheap-02",
                "task_type": "coding",
                "tier": "cheap",
                "accepted": False,
                "cost_usd": 0.002,
                "trace_id": f"{run_id}:trace:cheap-02",
                "run_id": run_id,
                "verifier_outcome": "fail",
            },
            {
                "case_id": f"{run_id}:cheap-03",
                "task_type": "coding",
                "tier": "cheap",
                "accepted": True,
                "cost_usd": 0.002,
                "trace_id": f"{run_id}:trace:cheap-03",
                "run_id": run_id,
                "verifier_outcome": "pass",
            },
            {
                "case_id": f"{run_id}:mid-01",
                "task_type": "coding",
                "tier": "mid",
                "accepted": True,
                "cost_usd": 0.008,
                "trace_id": f"{run_id}:trace:mid-01",
                "run_id": run_id,
                "verifier_outcome": "pass",
            },
            {
                "case_id": f"{run_id}:premium-01",
                "task_type": "coding",
                "tier": "premium",
                "accepted": True,
                "cost_usd": 0.05,
                "trace_id": f"{run_id}:trace:premium-01",
                "run_id": run_id,
                "verifier_outcome": "pass",
            },
        ]
        cases = [BenchmarkCase(**c) for c in _CASES]
        reduction_pct = context_reduction_pct if context_reduction_pct is not None else 55.0
        report = capability.run(
            run_id=run_id,
            context_reduction_pct=reduction_pct,
            benchmark_cases=cases,
            save=True,
        )
        return to_jsonable(report)

    # Load last saved report
    maybe_report = capability.load()
    if maybe_report is None:
        return {
            "error": "No proof report found. Call atelier_proof_report with run_id to generate one."
        }
    return to_jsonable(maybe_report)


@mcp_tool(name="atelier_rescue_failure")
def tool_rescue_failure(
    task: str,
    error: str,
    domain: str | None = None,
    files: list[str] | None = None,
    recent_actions: list[str] | None = None,
) -> dict[str, Any]:
    """Suggest a rescue procedure for a repeated failure."""
    if recent_actions is None:
        recent_actions = []
    if files is None:
        files = []
    rt = _runtime()
    led = _get_ledger()
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


@mcp_tool(name="atelier_record_trace")
def tool_record_trace(
    agent: str,
    domain: str,
    task: str,
    status: Literal["success", "failed", "partial"],
    files_touched: list[str] | None = None,
    tools_called: list[Any] | None = None,
    commands_run: list[str] | None = None,
    errors_seen: list[str] | None = None,
    diff_summary: str = "",
    output_summary: str = "",
    validation_results: list[Any] | None = None,
    prompt: str | None = None,
    response: str | None = None,
    bash_outputs: list[Any] | None = None,
    tool_outputs: list[Any] | None = None,
    run_id: str | None = None,
    trace_confidence: str | None = None,
    capture_sources: list[str] | None = None,
    missing_surfaces: list[str] | None = None,
) -> dict[str, Any]:
    """Record an observable trace from an agent run."""
    from atelier.core.foundation.redaction import redact, redact_list

    if validation_results is None:
        validation_results = []
    if errors_seen is None:
        errors_seen = []
    if commands_run is None:
        commands_run = []
    if tools_called is None:
        tools_called = []
    if files_touched is None:
        files_touched = []
    if bash_outputs is None:
        bash_outputs = []
    if tool_outputs is None:
        tool_outputs = []
    if capture_sources is None:
        capture_sources = []
    if missing_surfaces is None:
        missing_surfaces = []
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
                tool_call = {
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

    # Derive host label from agent string
    def _derive_host(a: str) -> str:
        al = a.lower()
        if "gemini" in al:
            return "gemini"
        if "copilot" in al:
            return "copilot"
        if "codex" in al:
            return "codex"
        if "opencode" in al:
            return "opencode"
        if al.startswith("atelier:") or "claude" in al:
            return "claude"
        return al

    # Validate: full_live requires capture_sources to include hooks/live
    _VALID_CONFIDENCE = {"full_live", "mcp_live", "wrapper_live", "imported", "manual"}
    if trace_confidence is not None and trace_confidence not in _VALID_CONFIDENCE:
        trace_confidence = None
    if trace_confidence == "full_live" and not any(
        s in ("hooks", "live_hooks", "plugin_hooks") for s in capture_sources
    ):
        # Downgrade silently to mcp_live; caller must include hooks in capture_sources
        trace_confidence = "mcp_live"
        if "hooks" not in missing_surfaces:
            missing_surfaces = [*list(missing_surfaces), "hooks"]

    payload = {
        "agent": agent,
        "domain": domain,
        "task": redact(task),
        "status": status,
        "files_touched": redact_list([str(v) for v in files_touched]),
        "tools_called": _normalize_tool_calls(tools_called),
        "commands_run": redact_list([str(v) for v in commands_run]),
        "errors_seen": redact_list([str(v) for v in errors_seen]),
        "diff_summary": redact(diff_summary),
        "output_summary": redact(output_summary),
        "run_id": run_id or led.run_id,
        "host": _derive_host(agent),
        "trace_confidence": trace_confidence,
        "capture_sources": capture_sources,
        "missing_surfaces": missing_surfaces,
    }

    payload["validation_results"] = _normalize_validation_results(validation_results)

    if prompt:
        rtc.record_prompt_response(redact(prompt), redact(response or ""))
    if bash_outputs:
        for item in bash_outputs:
            if isinstance(item, dict):
                command = str(item.get("command", ""))
                stdout = redact(str(item.get("stdout", "")))
                stderr = redact(str(item.get("stderr", "")))
                ok = bool(item.get("ok", True))
                rtc.record_bash_output(command, stdout=stdout, stderr=stderr, ok=ok)
            else:
                rtc.record_bash_output("bash", stdout=redact(str(item)), ok=True)
    if tool_outputs:
        for item in tool_outputs:
            rtc.record_tool_output("external_tool", {"output": redact(str(item))})

    raw_artifacts: list[str] = []
    if prompt or response or bash_outputs or tool_outputs:
        source_session_id = (
            os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("CODEX_SESSION_ID")
            or os.environ.get("OPENCODE_SESSION_ID")
            or "unknown"
        )
        artifact_content = {
            "prompt": redact(prompt or ""),
            "response": redact(response or ""),
            "bash_outputs": bash_outputs,
            "tool_outputs": tool_outputs,
        }
        redacted_content = json.dumps(artifact_content, ensure_ascii=False, indent=2)
        artifact_id = f"trace-ctx-{Trace.make_id(task, agent)}"
        digest = sha256(redacted_content.encode("utf-8", errors="replace")).hexdigest()
        artifact = RawArtifact(
            id=artifact_id,
            source="mcp",
            source_session_id=source_session_id,
            kind="trace.context.json",
            relative_path=f"{artifact_id}.json",
            content_path=f"raw/mcp/{source_session_id}/{artifact_id}.json",
            sha256_original=digest,
            sha256_redacted=digest,
            byte_count_original=len(redacted_content.encode("utf-8")),
            byte_count_redacted=len(redacted_content.encode("utf-8")),
            redacted=True,
        )
        with contextlib.suppress(Exception):
            rt.store.record_raw_artifact(artifact, redacted_content)
            raw_artifacts.append(artifact_id)

    if raw_artifacts:
        payload["raw_artifact_ids"] = raw_artifacts

    if "id" not in payload:
        payload["id"] = Trace.make_id(task, agent)

    trace = Trace.model_validate(payload)
    rt.store.record_trace(trace)

    led.close(status=status)
    led.persist()

    _write_session_state({"trace_recorded": True})
    rtc.persist()

    # Emit to Langfuse if configured (fail-open)
    from atelier.gateway.integrations.langfuse import emit_trace as _lf_emit

    _lf_emit(payload)
    return {"id": trace.id, "run_id": led.run_id, "realtime_context": rtc.snapshot()}


@mcp_tool(name="atelier_run_rubric_gate")
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


@mcp_tool(name="atelier_lesson_inbox")
def tool_lesson_inbox(domain: str | None = None, limit: int = 25) -> dict[str, Any]:
    """List lesson candidates currently waiting in the inbox."""
    led = _get_ledger()
    led.record_tool_call("lesson_inbox", {"domain": domain, "limit": limit})
    lessons = _lesson_promoter().inbox(domain=domain, limit=limit)
    return {"lessons": [lesson.model_dump(mode="json") for lesson in lessons]}


@mcp_tool(name="atelier_lesson_decide")
def tool_lesson_decide(
    lesson_id: str,
    decision: str,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    """Approve or reject a lesson candidate."""
    led = _get_ledger()
    led.record_tool_call(
        "lesson_decide",
        {
            "lesson_id": lesson_id,
            "decision": decision,
            "reviewer": reviewer,
        },
    )
    return _lesson_promoter().decide(
        lesson_id=lesson_id,
        decision=decision,
        reviewer=reviewer,
        reason=reason,
    )


@mcp_tool(name="atelier_report")
def tool_report(
    since_iso: str = "7d", format: Literal["markdown", "json"] = "markdown"
) -> dict[str, Any]:
    """Generate a deterministic governance report for traces and lesson candidates."""
    from atelier.core.capabilities.reporting.weekly_report import generate_report, render_markdown

    delta, now = _parse_report_since(since_iso)
    led = _get_ledger()
    led.record_tool_call("report", {"since_iso": since_iso, "format": format})
    report = generate_report(delta, store=_runtime().store, now=now, repo_root=Path.cwd())
    payload = report.model_dump(mode="json")
    if format == "markdown":
        return {"format": "markdown", "markdown": render_markdown(report), "report": payload}
    return {"format": "json", "report": payload}


@mcp_tool()
def tool_record_call(
    operation: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cost_usd: float | None = None,
    lessons_used: list[str] | None = None,
    prompt: str | None = None,
    response: str | None = None,
) -> dict[str, Any]:
    """Record a single LLM call with full prompt and response."""
    led = _get_ledger()
    led.record_call(
        operation=operation,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cost_usd=cost_usd,
        lessons_used=lessons_used,
        prompt=prompt,
        response=response,
    )
    led.persist()
    return {"recorded": True, "run_id": led.run_id}


@mcp_tool(name="atelier_sql_inspect")
def tool_sql_inspect(
    connection_alias: str,
    sql: str,
    params: list[Any] | dict[str, Any] | None = None,
    row_limit: int = 200,
) -> dict[str, Any]:
    """Execute deterministic SQL inspection against an allowlisted connection alias."""
    rt = _runtime()
    led = _get_ledger()
    led.record_tool_call(
        "sql_inspect",
        {
            "connection_alias": connection_alias,
            "has_params": params is not None,
            "row_limit": row_limit,
        },
    )
    return rt.sql_inspect(
        connection_alias=connection_alias,
        sql=sql,
        params=params,
        row_limit=row_limit,
    )


@mcp_tool(name="atelier_compress_context")
def tool_compress_context(run_id: str | None = None) -> Any:
    """Compress the current ledger state into a compact prompt block for context continuation."""
    from atelier.infra.runtime.context_compressor import ContextCompressor

    led = _get_ledger()
    rtc = _get_realtime_context()
    state = ContextCompressor().compress(led)
    return {
        "environment_id": state.environment_id,
        "preserved": {
            "latest_error": state.error_fingerprints[-1] if state.error_fingerprints else None,
            "active_rubrics": led.active_rubrics,
            "active_reasonblocks": led.active_reasonblocks,
        },
        "prompt_block": state.to_prompt_block(),
        "realtime": rtc.snapshot(),
    }


@mcp_tool(name="atelier_memory_upsert_block")
def tool_memory_upsert_block(
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
    version = (
        expected_version if expected_version is not None else (existing.version if existing else 1)
    )
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
        stored = store.upsert_block(
            block, actor=actor or f"agent:{agent_id}", reason=decision.reason
        )
    else:
        stored = store.upsert_block(block, actor=actor or f"agent:{agent_id}")
    return {
        "id": stored.id,
        "version": stored.version,
        "arbitration": decision.model_dump(mode="json"),
    }


@mcp_tool(name="atelier_memory_get_block")
def tool_memory_get_block(agent_id: str, label: str) -> dict[str, Any] | None:
    """Fetch one editable memory block by agent and label."""
    block = _memory_store().get_block(agent_id, label)
    return block.model_dump(mode="json") if block is not None else None


@mcp_tool(name="atelier_memory_archive")
def tool_memory_archive(
    agent_id: str,
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


@mcp_tool(name="atelier_memory_recall")
def tool_memory_recall(
    agent_id: str,
    query: str,
    top_k: int = 5,
    tags: list[str] | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Recall relevant archival memory passages."""
    since_dt = datetime.fromisoformat(since) if since else None
    passages, recall = _archival_recall().recall(
        agent_id=agent_id,
        query=query,
        top_k=top_k,
        tags=tags or None,
        since=since_dt,
    )
    return {
        "passages": [
            {
                "id": passage.id,
                "text": passage.text,
                "source_ref": passage.source_ref,
                "tags": passage.tags,
                "legacy_stub": passage.embedding_provenance == "legacy_stub",
            }
            for passage in passages
        ],
        "recall_id": recall.id,
    }


@mcp_tool(name="atelier_smart_read")
def tool_smart_read(
    path: str | None = None,
    file_path: str | None = None,
    range: str | None = None,
    expand: bool = False,
    max_lines: int | None = None,
) -> dict[str, Any]:
    """Smart file read with outline-first mode for large Python/TypeScript files."""
    target_path = file_path or path
    if not target_path:
        raise ValueError("provide path or file_path")
    if max_lines is not None and range is None and not expand:
        return cast(dict[str, Any], _core_runtime().smart_read(target_path, max_lines=max_lines))

    cap = SemanticFileMemoryCapability(_atelier_root())
    target = _workspace_path(target_path)
    payload = cap.smart_read(target, range_spec=range, expand=expand)
    return {
        "mode": payload["mode"],
        "cache_hit": bool(payload.get("cache_hit", False)),
        "tokens_saved": int(payload.get("tokens_saved", 0)),
        "outline": payload.get("outline"),
        "content": payload.get("content"),
        "path": payload.get("path", str(target)),
        "range": payload.get("range"),
    }


@mcp_tool(name="atelier_batch_edit")
def tool_batch_edit(
    edits: list[dict[str, Any]],
    atomic: bool = True,
) -> dict[str, Any]:
    """Apply many mechanical edits across files in one deterministic call.

    This is an *optional* Atelier augmentation.  Host-native Edit/MultiEdit
    tools remain the default path for ordinary coding.

    Each edit must have ``path`` and ``op``.  Supported ops:

    - ``replace``       — requires ``old_string``, ``new_string``
    - ``insert_after``  — requires ``anchor``, ``new_string``
    - ``replace_range`` — requires ``line_start``, ``line_end``, ``new_string``

    When ``atomic=true`` (default) any failure causes all changes to be
    reverted.  Files are snapshotted to ``.atelier/run/<id>/batch_edit_backup/``
    before editing and the backup is removed on success.

    Safety: never deletes files; never writes outside the repo root.
    """
    from atelier.core.capabilities.tool_supervision.batch_edit import apply_batch_edit

    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    result = apply_batch_edit(
        edits,
        atomic=atomic,
        repo_root=Path(workspace),
    )
    return result


@mcp_tool(name="atelier_compact_advise")
def tool_compact_advise(run_id: str | None = None) -> dict[str, Any]:
    """Advise when to compact and what context to preserve.

    Returns a manifest with:
    - should_compact: bool (true if utilisation >= 60%)
    """
    try:
        led = _get_ledger()
        if run_id:
            led.run_id = run_id

        # Estimate tokens used: token_count from ledger + events
        tokens_used = led.token_count
        # Rough estimation: each event ~50 tokens average
        event_tokens = max(0, len(led.events) * 10)
        tokens_used += event_tokens

        # Claude 3.5 Sonnet context window is 200K
        context_window = 200_000
        utilisation_pct = round(100.0 * tokens_used / context_window, 1)

        # Determine if compaction is advised
        should_compact = utilisation_pct >= 60.0

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
            pass  # Fail-open

        # Collect open_files: last 5 files touched
        open_files = led.files_touched[-5:] if led.files_touched else []

        # Build suggested prompt
        suggested_prompt = (
            f"Compact this conversation. Context utilisation: {utilisation_pct}%. "
            f"Please preserve these ReasonBlocks: {', '.join(preserve_blocks) or '(none yet)'}. "
            f"Recently edited files: {', '.join(open_files) or '(none)'}"
        )

        # Persist manifest to disk
        try:
            root = _atelier_root()
            run_dir = root / "runs" / led.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = run_dir / "compact_manifest.json"
            manifest = {
                "created_at": datetime.now(UTC).isoformat(),
                "run_id": led.run_id,
                "should_compact": should_compact,
                "utilisation_pct": utilisation_pct,
                "preserve_blocks": preserve_blocks,
                "pin_memory": pin_memory,
                "open_files": open_files,
                "suggested_prompt": suggested_prompt,
            }
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass  # Fail-open: don't block the tool if persistence fails

        return {
            "should_compact": should_compact,
            "utilisation_pct": utilisation_pct,
            "preserve_blocks": preserve_blocks,
            "pin_memory": pin_memory,
            "open_files": open_files,
            "suggested_prompt": suggested_prompt,
        }
    except Exception:
        # Fail-open: return conservative defaults
        return {
            "should_compact": False,
            "utilisation_pct": 0.0,
            "preserve_blocks": [],
            "pin_memory": [],
            "open_files": [],
            "suggested_prompt": "Unable to compute compaction advice; proceed with default compaction.",
        }


@mcp_tool(name="atelier_memory_summary")
def tool_memory_summary(run_id: str) -> dict[str, Any]:
    """Run the sleeptime summarizer for a given run and return a summary.

    Input:
        run_id: The run identifier to summarize.

    Output:
        tokens_pre, tokens_post, summary_md, evicted_event_ids,
        archived_passage_ids, strategy
    """
    try:
        from atelier.core.capabilities.context_compression.capability import (
            ContextCompressionCapability,
        )

        led = _get_ledger()
        if run_id:
            led.run_id = run_id

        cap = ContextCompressionCapability()
        result = cap.compress_with_sleeptime(led)

        summary_lines = [f"## Sleeptime Summary — run `{led.run_id}`", ""]
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
            "archived_passage_ids": [],
            "strategy": "tfidf",
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp_tool(name="atelier_search_read")
def tool_search_read(
    query: str,
    path: str = ".",
    max_files: int = 10,
    max_chars_per_file: int = 2000,
    include_outline: bool = True,
) -> dict[str, Any]:
    """Combined search + read (wozcode 1). Collapses grep→read→read into one ranked-snippet call.

    Runs a grep over *path* for *query*, clusters per-file matches into context
    windows (±8 lines), attaches AST outlines for files with >5 hits, and
    returns token-accounted results.  Typically saves ≥70 % of the tokens
    compared to separate grep + full-file-read calls.

    Host-native search/read tools remain available for raw exploration; this
    tool is the optimised path, not the only path.
    """
    from atelier.core.capabilities.tool_supervision.search_read import (
        search_read,
        search_read_to_dict,
    )

    result = search_read(
        query=query,
        path=path,
        max_files=max_files,
        max_chars_per_file=max_chars_per_file,
        include_outline=include_outline,
    )
    return search_read_to_dict(result)


@mcp_tool(name="atelier_compact_tool_output")
def tool_compact_tool_output(
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


@mcp_tool(name="atelier_repo_map")
def tool_repo_map(
    seed_files: list[str],
    budget_tokens: int = 2000,
    languages: list[str] | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
) -> dict[str, Any]:
    """Build a budgeted PageRank repo map from seed files."""
    _ = languages
    from atelier.core.capabilities.repo_map import build_repo_map

    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    result = build_repo_map(
        workspace,
        seed_files=seed_files,
        budget_tokens=budget_tokens,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
    )
    return result.model_dump(mode="json")


@mcp_tool(name="atelier_consolidation_inbox")
def tool_consolidation_inbox(limit: int = 25) -> dict[str, Any]:
    """List pending consolidation candidates."""
    store = _runtime().store
    items = store.list_consolidation_candidates(limit=limit)
    return {"candidates": [item.model_dump(mode="json") for item in items]}


@mcp_tool(name="atelier_consolidation_decide")
def tool_consolidation_decide(
    id: str,
    decision: str,
    reviewer: str = "agent",
) -> dict[str, Any]:
    """Apply or reject a consolidation candidate decision."""
    store = _runtime().store
    candidate = store.get_consolidation_candidate(id)
    if candidate is None:
        raise ValueError(f"consolidation candidate not found: {id}")
    candidate.decided_at = datetime.now(UTC)
    candidate.decided_by = reviewer
    candidate.decision = decision
    store.upsert_consolidation_candidate(candidate)
    return candidate.model_dump(mode="json")


# --------------------------------------------------------------------------- #
# Remote mode & dispatcher                                                    #
# --------------------------------------------------------------------------- #

# Tools that are routed through the remote HTTP service in MCP remote mode.
_REMOTE_TOOLS = frozenset(
    {
        "get_reasoning_context",
        "check_plan",
        "rescue_failure",
        "run_rubric_gate",
        "record_trace",
        "atelier_get_reasoning_context",
        "atelier_check_plan",
        "atelier_rescue_failure",
        "atelier_record_trace",
        "atelier_run_rubric_gate",
        "atelier_lesson_inbox",
        "atelier_lesson_decide",
    }
)

_remote_client: Any = None


def _get_remote_client() -> Any:
    global _remote_client
    if _remote_client is None:
        from atelier.gateway.adapters.remote_client import RemoteClient

        _remote_client = RemoteClient()
    return _remote_client


def _dispatch_remote(name: str, args: dict[str, Any]) -> dict[str, Any]:
    client = _get_remote_client()
    import typing

    if name in {"get_reasoning_context", "atelier_get_reasoning_context"}:
        return typing.cast(dict[str, Any], client.get_reasoning_context(args))
    if name in {"check_plan", "atelier_check_plan"}:
        return typing.cast(dict[str, Any], client.check_plan(args))
    if name in {"rescue_failure", "atelier_rescue_failure"}:
        return typing.cast(dict[str, Any], client.rescue_failure(args))
    if name in {"record_trace", "atelier_record_trace"}:
        return typing.cast(dict[str, Any], client.record_trace(args))
    if name in {"run_rubric_gate", "atelier_run_rubric_gate"}:
        return typing.cast(dict[str, Any], client.run_rubric_gate(args))
    if name == "atelier_lesson_inbox":
        return typing.cast(dict[str, Any], client.lesson_inbox(args))
    if name == "atelier_lesson_decide":
        return typing.cast(dict[str, Any], client.lesson_decide(args))
    raise ValueError(f"tool not supported in remote mode: {name}")


for alias, target in {
    "get_reasoning_context": "atelier_get_reasoning_context",
    "check_plan": "atelier_check_plan",
    "route_decide": "atelier_route_decide",
    "route_verify": "atelier_route_verify",
    "rescue_failure": "atelier_rescue_failure",
    "record_trace": "atelier_record_trace",
    "run_rubric_gate": "atelier_run_rubric_gate",
    "memory_upsert_block": "atelier_memory_upsert_block",
    "memory_get_block": "atelier_memory_get_block",
    "memory_archive": "atelier_memory_archive",
    "memory_recall": "atelier_memory_recall",
}.items():
    TOOLS.setdefault(alias, TOOLS[target])


# --------------------------------------------------------------------------- #
# MCP Protocol Handling                                                       #
# --------------------------------------------------------------------------- #


def _record_context_budget_for_tool(tool_name: str, led: RunLedger, result: dict[str, Any]) -> None:
    """Record context budget metrics for a tool execution.

    Args:
        tool_name: The name of the tool being executed.
        led: The RunLedger for the current run.
        result: The result from the tool.
    """
    try:
        recorder = _get_context_budget_recorder()

        # Extract lever_savings from result if present, otherwise use empty dict
        lever_savings = result.get("tokens_saved", {})
        if not isinstance(lever_savings, dict):
            lever_savings = {}

        # Record the tool execution metrics
        # Note: actual token counts would come from the LLM provider
        # For now we record with placeholder values
        recorder.record(
            run_id=led.run_id,
            turn_index=getattr(led, "turn_index", 0),
            model=getattr(led, "model", "unknown"),
            input_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=0,
            naive_input_tokens=0,
            lever_savings=lever_savings,
            tool_calls=1,
        )
    except Exception:
        # Silently fail if context budget recording is not available
        pass


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    rid = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
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
                "description": s.get("description", ""),
                "inputSchema": s.get("inputSchema", {}),
            }
            for n, s in TOOLS.items()
        ]
        return _ok(rid, {"tools": tools})

    if method == "tools/call":
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        spec = TOOLS.get(name)
        if spec is None:
            return _err(rid, -32601, f"unknown tool: {name}")

        mcp_mode = os.environ.get("ATELIER_MCP_MODE", "local")
        try:
            rtc = _get_realtime_context()
            rtc.record_tool_input(name, args)
            if mcp_mode == "remote" and name in _REMOTE_TOOLS:
                result = _dispatch_remote(name, args)
            else:
                handler: Callable[[dict[str, Any]], dict[str, Any]] = spec["handler"]
                result = handler(args)

            led = _get_ledger()
            result_text = json.dumps(result, ensure_ascii=False, default=str)
            compact_text = (
                result_text
                if len(result_text) <= 1200
                else result_text[:600] + "..." + result_text[-600:]
            )
            led.record(
                "tool_result",
                f"{name} result",
                {
                    "tool": name,
                    "output": compact_text,
                    "output_chars": len(result_text),
                },
            )
            rtc.record_tool_output(name, result)
            rtc.persist()

            # Record context budget metrics
            _record_context_budget_for_tool(name, led, result)

            return _ok(
                rid,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
                    ],
                    "structuredContent": result,
                },
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                rtc = _get_realtime_context()
                rtc.record_tool_error(name, str(exc))
                rtc.persist()
            return _err(rid, _tool_error_code(exc), str(exc))

    return _err(rid, -32601, f"unknown method: {method}")


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


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(_err(None, -32700, f"parse error: {exc}")) + "\n")
            sys.stdout.flush()
            continue
        resp = _handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main() -> None:
    argv = sys.argv[1:]
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            os.environ["ATELIER_ROOT"] = argv[i + 1]
    serve()


if __name__ == "__main__":
    main()
