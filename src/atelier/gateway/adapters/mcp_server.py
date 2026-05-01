"""MCP server (stdio JSON-RPC) for the Atelier reasoning runtime.

Implements a minimal subset of the Model Context Protocol sufficient for
Codex / Claude Code to discover and call the runtime tools.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, create_model

from atelier.core.foundation.extractor import extract_candidate
from atelier.core.foundation.models import Trace, to_jsonable
from atelier.core.foundation.plan_checker import check_plan
from atelier.core.foundation.rubric_gate import run_rubric
from atelier.gateway.adapters.runtime import ReasoningRuntime
from atelier.infra.runtime.run_ledger import RunLedger

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "atelier-reasoning"
SERVER_VERSION = "0.1.0"


# --------------------------------------------------------------------------- #
# Tool Registry Decorator                                                     #
# --------------------------------------------------------------------------- #

TOOLS: dict[str, dict[str, Any]] = {}


def mcp_tool(
    name: str | None = None, description: str | None = None
) -> Callable[[Callable[..., dict[str, Any]]], Callable[[dict[str, Any]], dict[str, Any]]]:
    """Decorator to register a tool and auto-derive its MCP schema."""

    def decorator(
        func: Callable[..., dict[str, Any]],
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
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
            def handler_wrapper(args: dict[str, Any]) -> dict[str, Any]:
                validated = ArgsModel.model_validate(args)
                return func(**validated.model_dump())

        else:
            schema = {"type": "object", "properties": {}}

            @wraps(func)
            def handler_wrapper(args: dict[str, Any]) -> dict[str, Any]:
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
        _write_session_state({
            "active_run_id": _current_ledger.run_id,
            "atelier_root": str(root),
        })
    return _current_ledger


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


def _core_runtime() -> Any:
    from atelier.core.runtime import AtelierRuntimeCore

    return AtelierRuntimeCore(_atelier_root())


@mcp_tool()
def tool_get_reasoning_context(
    task: str,
    domain: str | None = None,
    files: list[str] | None = None,
    tools: list[str] | None = None,
    errors: list[str] | None = None,
    max_blocks: int = 5,
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
        },
    )

    text = rt.get_reasoning_context(
        task=task,
        domain=domain,
        files=files,
        tools=tools,
        errors=errors,
        max_blocks=max_blocks,
    )
    return {"context": text}


@mcp_tool()
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


@mcp_tool()
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
    return to_jsonable(result)


@mcp_tool()
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
    run_id: str | None = None,
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
    rt = _runtime()
    led = _get_ledger()

    payload = {
        "agent": agent,
        "domain": domain,
        "task": redact(task),
        "status": status,
        "files_touched": redact_list([str(v) for v in files_touched]),
        "tools_called": tools_called,
        "commands_run": redact_list([str(v) for v in commands_run]),
        "errors_seen": redact_list([str(v) for v in errors_seen]),
        "diff_summary": redact(diff_summary),
        "output_summary": redact(output_summary),
        "run_id": run_id or led.run_id,
    }

    cleaned_vr: list[dict[str, Any]] = []
    for vr in validation_results:
        if isinstance(vr, dict):
            vr2 = dict(vr)
            if isinstance(vr2.get("detail"), str):
                vr2["detail"] = redact(vr2["detail"])
            cleaned_vr.append(vr2)
        else:
            cleaned_vr.append(vr)
    payload["validation_results"] = cleaned_vr

    if "id" not in payload:
        payload["id"] = Trace.make_id(task, agent)

    trace = Trace.model_validate(payload)
    rt.store.record_trace(trace)

    led.close(status=status)
    led.persist()

    _write_session_state({"trace_recorded": True})
    return {"id": trace.id, "run_id": led.run_id}


@mcp_tool()
def tool_extract_reasonblock(trace_id: str, save: bool = False) -> Any:
    """Extract a candidate ReasonBlock from a recorded trace."""
    rt = _runtime()
    led = _get_ledger()
    led.record_tool_call("extract_reasonblock", {"trace_id": trace_id, "save": save})

    trace = rt.store.get_trace(trace_id)
    if trace is None:
        raise ValueError(f"trace not found: {trace_id}")
    candidate = extract_candidate(trace)
    if save:
        rt.store.upsert_block(candidate.block)
    return {
        "block": to_jsonable(candidate.block),
        "confidence": candidate.confidence,
        "reasons": candidate.reasons,
        "saved": bool(save),
    }


@mcp_tool()
def tool_run_rubric_gate(rubric_id: str, checks: dict[str, Any]) -> Any:
    """Evaluate agent results against a domain rubric."""
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


@mcp_tool()
def tool_record_note(summary: str, payload: dict[str, Any] | None = None) -> Any:
    """Record a technical note or rationale into the ledger."""
    if payload is None:
        payload = {}
    led = _get_ledger()
    led.record("note", summary, payload)
    led.persist()
    return {"recorded": True, "run_id": led.run_id}


# --------------------------------------------------------------------------- #
# V2 tool implementations                                                     #
# --------------------------------------------------------------------------- #


def _runs_dir() -> Path:
    return _atelier_root() / "runs"


def _ledger_path_for(run_id: str | None) -> Path:
    runs = _runs_dir()
    if run_id:
        return runs / f"{run_id}.json"
    if not runs.is_dir():
        raise ValueError("no run ledger found")
    paths = sorted(runs.glob("*.json"))
    if not paths:
        raise ValueError("no run ledger found")
    return paths[-1]


@mcp_tool(name="get_run_ledger")
def tool_get_run_ledger(run_id: str | None = None) -> Any:
    """Retrieve the run ledger for a specific run or the latest run."""
    path = _ledger_path_for(run_id)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@mcp_tool(name="update_run_ledger")
def tool_update_run_ledger(updates: dict[str, Any], run_id: str | None = None) -> Any:
    """Update fields in the active or specified run ledger."""
    led = _get_ledger()
    for k, v in updates.items():
        if hasattr(led, k):
            setattr(led, k, v)
    led.persist()
    return {"updated": list(updates.keys()), "run_id": led.run_id}


@mcp_tool(name="monitor_event")
def tool_monitor_event(
    monitor: str, message: str, severity: str = "medium", run_id: str | None = None
) -> dict[str, Any]:
    """Record an alert from a monitor into the ledger."""
    led = _get_ledger()
    led.record_alert(monitor, severity, message)
    led.persist()
    return {"recorded": True, "run_id": led.run_id}


@mcp_tool(name="compress_context")
def tool_compress_context(run_id: str | None = None) -> Any:
    """Compress the current ledger state into a compact prompt block."""
    from atelier.infra.runtime.context_compressor import ContextCompressor

    led = _get_ledger()
    state = ContextCompressor().compress(led)
    return {
        "environment_id": state.environment_id,
        "preserved": {
            "latest_error": state.error_fingerprints[-1] if state.error_fingerprints else None,
            "active_rubrics": led.active_rubrics,
            "active_reasonblocks": led.active_reasonblocks,
        },
        "prompt_block": state.to_prompt_block(),
    }


@mcp_tool(name="get_environment_context")
def tool_get_environment_context(env_id: str) -> Any:
    """Get the full environment configuration including related ReasonBlocks and rubric."""
    from atelier.core.foundation.environments import load_packaged_environments

    rt = _runtime()
    envs = {e.id: e for e in load_packaged_environments()}
    if env_id not in envs:
        raise ValueError(f"environment not found: {env_id}")
    e = envs[env_id]
    blocks = [rt.store.get_block(bid) for bid in e.related_blocks if rt.store.get_block(bid)]
    rubric = rt.store.get_rubric(e.rubric_id) if e.rubric_id else None
    return {
        "environment": to_jsonable(e),
        "blocks": [to_jsonable(b) for b in blocks if b],
        "rubric": to_jsonable(rubric) if rubric else None,
    }


@mcp_tool(name="smart_read")
def tool_smart_read(path: str) -> Any:
    """Read a file with summarization and related-ReasonBlock attachment."""
    rt = _runtime()
    led = _get_ledger()
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"file not found: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")
    led.record_file_event(str(p), "read")

    return {
        "path": str(p),
        "summary": text[:8000],
        "related_blocks": [
            {"id": b.id, "title": b.title} for b in rt.store.search_blocks(p.name, limit=3)
        ],
    }


@mcp_tool(name="smart_search")
def tool_smart_search(query: str, limit: int = 10) -> Any:
    """Search for relevant ReasonBlocks using a text query."""
    rt = _runtime()
    blocks = rt.store.search_blocks(query, limit=int(limit))
    return {"matches": [{"id": b.id, "title": b.title, "domain": b.domain} for b in blocks]}


@mcp_tool(name="atelier_reasoning_reuse")
def tool_atelier_reasoning_reuse(
    task: str,
    domain: str | None = None,
    files: list[str] | None = None,
    tools: list[str] | None = None,
    errors: list[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Return reusable procedures for the current task."""
    if errors is None:
        errors = []
    if tools is None:
        tools = []
    if files is None:
        files = []
    rt = _core_runtime()
    scored = rt.reasoning_reuse.retrieve(
        task=task,
        domain=domain,
        files=files,
        tools=tools,
        errors=errors,
        limit=limit,
    )
    return {
        "procedures": [
            {
                "id": item.block.id,
                "title": item.block.title,
                "domain": item.block.domain,
                "score": item.score,
                "procedure": item.block.procedure,
                "verification": item.block.verification,
            }
            for item in scored
        ]
    }


@mcp_tool(name="atelier_semantic_memory")
def tool_atelier_semantic_memory(
    path: str | None = None,
    query: str | None = None,
    max_lines: int = 120,
    limit: int = 10,
) -> dict[str, Any]:
    """Summarize a file or run semantic lookup from local file memory."""
    rt = _core_runtime()
    import typing

    if path:
        return typing.cast(dict[str, Any], rt.smart_read(path, max_lines=max_lines))
    if query:
        return {"matches": rt.semantic_memory.semantic_search(query, limit=limit)}
    raise ValueError("provide either path or query")


@mcp_tool(name="atelier_loop_monitor")
def tool_atelier_loop_monitor(run_id: str | None = None) -> Any:
    """Detect loop signals from a run ledger."""
    rt = _core_runtime()
    summary = rt.summarize_memory(run_id=run_id)
    return {
        "run_id": summary.get("run_id"),
        "loop_alerts": summary.get("loop_alerts", []),
        "current_blocker": summary.get("current_blocker"),
    }


@mcp_tool(name="atelier_tool_supervisor")
def tool_atelier_tool_supervisor() -> Any:
    """Return tool supervision status and efficiency counters."""
    rt = _core_runtime()
    return rt.capability_status()


@mcp_tool(name="atelier_context_compressor")
def tool_atelier_context_compressor(run_id: str | None = None) -> Any:
    """Compress a run ledger into actionable context."""
    rt = _core_runtime()
    return rt.summarize_memory(run_id=run_id)


@mcp_tool(name="atelier_smart_search")
def tool_atelier_smart_search(query: str, limit: int = 10) -> Any:
    """Unified smart search over procedures and semantic memory."""
    rt = _core_runtime()
    return rt.smart_search(query, limit=limit)


@mcp_tool(name="atelier_smart_read")
def tool_atelier_smart_read(path: str, max_lines: int = 120) -> Any:
    """AST-aware smart file read with semantic caching."""
    rt = _core_runtime()
    return rt.smart_read(path, max_lines=max_lines)


@mcp_tool(name="atelier_smart_edit")
def tool_atelier_smart_edit(edits: list[dict[str, str]]) -> Any:
    """Batch fuzzy edits across multiple files."""
    rt = _core_runtime()
    return rt.smart_edit(edits)


@mcp_tool(name="atelier_sql_inspect")
def tool_atelier_sql_inspect(
    sql: str | None = None, file_path: str | None = None
) -> dict[str, Any]:
    """Inspect SQL for schema hints, FK references, and migration signals."""
    rt = _core_runtime()
    import typing

    return typing.cast(dict[str, Any], rt.sql_inspect(sql=sql, file_path=file_path))


@mcp_tool(name="atelier_module_summary")
def tool_atelier_module_summary(path: str) -> dict[str, Any]:
    """Return a concise module-level summary: exports, symbols, imports, test files."""
    rt = _core_runtime()
    import typing

    return typing.cast(dict[str, Any], rt.module_summary(path))


@mcp_tool(name="atelier_symbol_search")
def tool_atelier_symbol_search(query: str, limit: int = 20) -> Any:
    """Search all cached files for symbols matching the query string."""
    rt = _core_runtime()
    results = rt.symbol_search(query, limit=limit)
    return {"results": results}


_SHELL_META = re.compile(r"[;|&`$<>\\!{}\[\]()'\"" + "\n\r]", re.ASCII)


@mcp_tool(name="cached_grep")
def tool_cached_grep(pattern: str, path: str = ".") -> Any:
    """Perform a grep search and record the result in the ledger."""
    import subprocess

    led = _get_ledger()
    if _SHELL_META.search(pattern):
        raise ValueError(
            f"Pattern contains shell metacharacters: {pattern!r}. "
            "Use a plain string or a safe regex."
        )
    proc = subprocess.run(
        ["grep", "-rn", "--", pattern, path], capture_output=True, text=True, check=False
    )
    led.record_command(f"grep {pattern}", ok=proc.returncode == 0, stdout=proc.stdout[:1000])
    return {"output": proc.stdout[:8000]}


# --------------------------------------------------------------------------- #
# Domain & Host tools                                                         #
# --------------------------------------------------------------------------- #


def _domain_manager() -> Any:
    from atelier.core.domains import DomainManager

    root = Path(os.environ.get("ATELIER_ROOT", ".atelier"))
    return DomainManager(root)


@mcp_tool(name="atelier_domain_list")
def tool_atelier_domain_list() -> Any:
    """List available Atelier domain bundles (built-in and user-defined)."""
    manager = _domain_manager()
    refs = manager.list_bundles()
    return {"bundles": [r.model_dump(mode="json") for r in refs]}


@mcp_tool(name="atelier_domain_info")
def tool_atelier_domain_info(bundle_id: str) -> Any:
    """Get detailed information for an Atelier domain bundle."""
    manager = _domain_manager()
    payload = manager.info(bundle_id)
    if payload is None:
        raise ValueError(f"domain bundle not found: {bundle_id}")
    return payload


def _host_registry() -> Any:
    from atelier.gateway.hosts import HostRegistry

    root = Path(os.environ.get("ATELIER_ROOT", ".atelier"))
    hosts_dir = root / "hosts"
    return HostRegistry(storage_dir=hosts_dir)


@mcp_tool(name="atelier_host_list")
def tool_atelier_host_list() -> Any:
    """List all registered Atelier hosts."""
    registry = _host_registry()
    hosts = registry.list_all()
    return {
        "hosts": [
            {
                "host_id": str(h.host_id),
                "label": h.metadata.get("label", str(h.host_id)[:8]),
                "status": h.metadata.get("status", "unknown"),
                "active_domains": h.metadata.get("active_domains", []),
                "mcp_tools_count": len(h.metadata.get("mcp_tools", [])),
                "atelier_version": h.atelier_version,
                "last_seen": h.last_seen.isoformat() if h.last_seen else None,
                "registered_at": h.registered_at.isoformat() if h.registered_at else None,
            }
            for h in hosts
        ]
    }


@mcp_tool(name="atelier_host_status")
def tool_atelier_host_status(host_id: str) -> Any:
    """Get status of a specific Atelier host."""
    registry = _host_registry()
    registration = registry.get(host_id)

    if registration is None:
        raise ValueError(f"host not found: {host_id}")

    return {
        "host_id": str(registration.host_id),
        "fingerprint": {
            "hostname": registration.fingerprint.hostname,
            "username": registration.fingerprint.username,
            "fingerprint_hash": registration.fingerprint.fingerprint_hash,
        },
        "atelier_version": registration.atelier_version,
        "registered_at": (
            registration.registered_at.isoformat() if registration.registered_at else None
        ),
        "last_seen": registration.last_seen.isoformat() if registration.last_seen else None,
        "active_domains": registration.metadata.get("active_domains", []),
        "mcp_tools": registration.metadata.get("mcp_tools", []),
        "metadata": registration.metadata,
    }


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

    if name == "get_reasoning_context":
        return typing.cast(dict[str, Any], client.get_reasoning_context(args))
    if name == "check_plan":
        return typing.cast(dict[str, Any], client.check_plan(args))
    if name == "rescue_failure":
        return typing.cast(dict[str, Any], client.rescue_failure(args))
    if name == "run_rubric_gate":
        return typing.cast(dict[str, Any], client.run_rubric_gate(args))
    if name == "record_trace":
        return typing.cast(dict[str, Any], client.record_trace(args))
    raise ValueError(f"tool not supported in remote mode: {name}")


# --------------------------------------------------------------------------- #
# MCP Protocol Handling                                                       #
# --------------------------------------------------------------------------- #


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
            if mcp_mode == "remote" and name in _REMOTE_TOOLS:
                result = _dispatch_remote(name, args)
            else:
                handler: Callable[[dict[str, Any]], dict[str, Any]] = spec["handler"]
                result = handler(args)
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
            return _err(rid, -32000, str(exc))

    return _err(rid, -32601, f"unknown method: {method}")


def _ok(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


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
