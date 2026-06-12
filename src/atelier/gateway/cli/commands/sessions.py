from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from atelier.core.capabilities.savings_summary import TranscriptSavingsBlock

from atelier.core.foundation.models import Trace, to_jsonable
from atelier.core.foundation.store import ContextStore
from atelier.gateway.cli.commands._shared import _emit, _load_store, _parse_duration
from atelier.gateway.hosts.session_parsers.registry import (
    SUPPORTED_SESSION_IMPORT_HOSTS,
)


@click.group("runs")
def runs_group() -> None:
    """Run record, list, and inspect commands."""


@runs_group.command("record")
@click.option(
    "--input",
    "input_path",
    type=click.Path(path_type=Path),
    default="-",
    show_default=True,
    help="Trace JSON file. Use '-' for stdin.",
)
@click.pass_context
def trace_record(ctx: click.Context, input_path: Path | str) -> None:
    """Record an observable trace."""
    import sys

    store = _load_store(ctx.obj["root"])
    raw = sys.stdin.read() if str(input_path) == "-" else Path(input_path).read_text("utf-8")
    data = json.loads(raw)
    if "id" not in data:
        data["id"] = Trace.make_id(data.get("task", "untitled"), data.get("agent", "agent"))
    trace = Trace.model_validate(data)
    store.record_trace(trace)
    click.echo(trace.id)


@runs_group.command("list")
@click.option("--domain", default=None, help="Filter by domain.")
@click.option("--status", default=None, type=click.Choice(["success", "failed", "partial"]))
@click.option("--agent", default=None, help="Filter by agent name.")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def trace_list(
    ctx: click.Context,
    domain: str | None,
    status: str | None,
    agent: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """List recorded traces."""
    store = _load_store(ctx.obj["root"])
    traces = store.list_traces(domain=domain, status=status, agent=agent, limit=limit)
    if as_json:
        _emit([to_jsonable(t) for t in traces], as_json=True)
        return
    if not traces:
        click.echo("(no traces)")
        return
    for t in traces:
        click.echo(f"{t.id}\t{t.agent}\t{t.status}\t{t.domain}\t{t.task[:60]}")


@runs_group.command("show")
@click.argument("trace_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def trace_show(ctx: click.Context, trace_id: str, as_json: bool) -> None:
    """Show a single trace by ID."""
    store = _load_store(ctx.obj["root"])
    trace = store.get_trace(trace_id)
    if trace is None:
        raise click.ClickException(f"trace not found: {trace_id}")
    if as_json:
        _emit(to_jsonable(trace), as_json=True)
        return
    click.echo(f"id:     {trace.id}")
    click.echo(f"agent:  {trace.agent}")
    click.echo(f"status: {trace.status}")
    click.echo(f"domain: {trace.domain}")
    click.echo(f"task:   {trace.task}")


@click.group("outcomes")
def outcomes_group() -> None:
    """Inspect captured route and compact decision outcomes."""


@outcomes_group.command("show")
@click.argument("session_id")
@click.pass_context
def outcomes_show(ctx: click.Context, session_id: str) -> None:
    """Print JSON outcome data for SESSION_ID."""
    from atelier.infra.runtime.outcome_capture import load_outcomes_from_state

    root: Path = ctx.obj["root"]
    path = root / "runs" / f"{session_id}_outcomes.json"
    data = load_outcomes_from_state(path)
    click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


@outcomes_group.command("summary")
@click.option("--since", default="7d", show_default=True, help="Look-back window, e.g. 7d, 24h.")
@click.pass_context
def outcomes_summary(ctx: click.Context, since: str) -> None:
    """Aggregate outcome_scores by (kind, tool) and print averages."""

    from atelier.infra.runtime.outcome_capture import (
        load_outcomes_from_state,
        summarise_outcomes,
    )

    cutoff = datetime.now(UTC) - _parse_duration(since)
    root: Path = ctx.obj["root"]
    runs_dir = root / "runs"
    if not runs_dir.exists():
        click.echo(json.dumps([], indent=2))
        return

    combined: dict[str, list[dict[str, Any]]] = {
        "route_outcomes": [],
        "compact_outcomes": [],
    }
    for outcomes_file in runs_dir.glob("*_outcomes.json"):
        try:
            mtime = datetime.fromtimestamp(outcomes_file.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        data = load_outcomes_from_state(outcomes_file)
        combined["route_outcomes"].extend(data.get("route_outcomes") or [])
        combined["compact_outcomes"].extend(data.get("compact_outcomes") or [])

    summary = summarise_outcomes(combined)
    click.echo(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


@click.group("session")
def session_group() -> None:
    """Per-session cost and savings reports."""


@session_group.command("report")
@click.argument("session_id", required=False, default=None)
@click.option("--json", "as_json", is_flag=True, default=False, help="Output JSON.")
@click.option("--no-color", is_flag=True, default=False, help="Disable ANSI colours.")
@click.pass_context
def session_report_cmd(
    ctx: click.Context,
    session_id: str | None,
    as_json: bool,
    no_color: bool,
) -> None:
    """Show cost and savings breakdown for SESSION_ID (default: most recent)."""
    from atelier.infra.runtime.session_report import (
        list_run_files,
        load_report,
        render_json,
        render_text,
    )

    root: Path = ctx.obj["root"]

    if session_id is None:
        files = list_run_files(root)
        if not files:
            click.echo("No sessions found - run any AI command first.", err=True)
            raise SystemExit(1)
        session_id = files[0].stem

    report = load_report(session_id, root)
    if report is None:
        click.echo(f"Session '{session_id}' not found in {root / 'runs'}.", err=True)
        raise SystemExit(1)

    if as_json:
        click.echo(render_json(report))
    else:
        click.echo(render_text(report, no_color=no_color))


@session_group.command("list")
@click.option("--since", default=None, help="Look-back window, e.g. 7d, 24h.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output JSON.")
@click.pass_context
def session_list_cmd(ctx: click.Context, since: str | None, as_json: bool) -> None:
    """List recent sessions with costs and durations (newest first, max 20)."""
    from atelier.infra.runtime.session_report import (
        build_report,
        list_run_files,
    )

    root: Path = ctx.obj["root"]
    cutoff = datetime.now(UTC) - _parse_duration(since) if since else None
    files = list_run_files(root, since=cutoff)[:20]

    if not files:
        msg = "No sessions found"
        if since:
            msg += f" in the last {since}"
        click.echo(msg + ".", err=True)
        return

    rows = []
    for f in files:
        try:
            snapshot = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        try:
            report = build_report(snapshot, root)
        except Exception:
            logging.exception("session report build failed for %s", f)
            continue
        rows.append(report)

    if as_json:
        click.echo(
            json.dumps(
                [dataclasses.asdict(r) for r in rows],
                default=str,
                indent=2,
            )
        )
        return

    hdr = f"  {'Session':<10} {'Started':<22} {'Duration':<14} {'Turns':>6} {'Cost':>9} {'Saved':>9}"
    click.echo(hdr)
    click.echo("  " + "─" * (len(hdr) - 2))
    for r in rows:
        sid = r.session_id[:10]
        started = r.started_at.strftime("%Y-%m-%d %H:%M")
        from atelier.infra.runtime.session_report import (
            _fmt_cost,
            _fmt_duration,
        )

        dur = _fmt_duration(r.duration_seconds, r.is_running)
        click.echo(
            f"  {sid:<10} {started:<22} {dur:<14} {r.total_turns:>6}"
            f" {_fmt_cost(r.total_cost_usd):>9} {_fmt_cost(r.total_atelier_savings_usd):>9}"
        )


# Claude Code launches subagents via "Agent" (formerly "Task").
_SUBAGENT_TOOL_NAMES = {"agent", "task"}


def _tool_call_total(trace: Trace) -> int:
    total = 0
    for call in trace.tools_called:
        total += int(call.count or 0)
    return total


def _subagent_total(trace: Trace) -> int:
    total = 0
    for call in trace.tools_called:
        if str(call.name or "").strip().lower() in _SUBAGENT_TOOL_NAMES:
            total += int(call.count or 0)
    return total


def _trace_cost_usd(trace: Trace) -> float:
    total = 0.0
    for entry in trace.usage_entries:
        total += float(entry.cost_usd or 0.0)
    return round(total, 6)


def _estimated_trace_cost_usd(trace: Trace) -> float:
    from atelier.core.capabilities.pricing import usage_cost_usd
    from atelier.core.capabilities.savings_summary import resolve_model_id

    estimated = 0.0
    if trace.model_usages:
        for usage in trace.model_usages:
            model = resolve_model_id(usage.model or trace.model or "claude-sonnet-4-5")
            estimated += usage_cost_usd(
                model,
                input_tokens=int(usage.input_tokens or 0),
                output_tokens=int(usage.output_tokens or 0),
                cache_read_tokens=int(usage.cached_input_tokens or 0),
                cache_write_tokens=int(usage.cache_creation_input_tokens or 0),
                thinking_tokens=int(usage.thinking_tokens or 0),
            )
        return round(estimated, 6)

    model = resolve_model_id(trace.model or "claude-sonnet-4-5")
    estimated = usage_cost_usd(
        model,
        input_tokens=int(trace.input_tokens or 0),
        output_tokens=int(trace.output_tokens or 0),
        cache_read_tokens=int(trace.cached_input_tokens or 0),
        cache_write_tokens=int(trace.cache_creation_input_tokens or 0),
        thinking_tokens=int(trace.thinking_tokens or 0),
    )
    return round(float(estimated), 6)


def _estimated_trace_cost_breakdown(trace: Trace) -> dict[str, float]:
    from atelier.core.capabilities.pricing import usage_cost_breakdown_usd
    from atelier.core.capabilities.savings_summary import resolve_model_id

    breakdown = {"input": 0.0, "cache_read": 0.0, "cache_write": 0.0, "output": 0.0}
    if trace.model_usages:
        for usage in trace.model_usages:
            model = resolve_model_id(usage.model or trace.model or "claude-sonnet-4-5")
            part = usage_cost_breakdown_usd(
                model,
                input_tokens=int(usage.input_tokens or 0),
                output_tokens=int(usage.output_tokens or 0),
                cache_read_tokens=int(usage.cached_input_tokens or 0),
                cache_write_tokens=int(usage.cache_creation_input_tokens or 0),
                thinking_tokens=int(usage.thinking_tokens or 0),
            )
            breakdown["input"] += float(part.get("input") or 0.0)
            breakdown["cache_read"] += float(part.get("cache_read") or 0.0)
            breakdown["cache_write"] += float(part.get("cache_write") or 0.0)
            breakdown["output"] += float(part.get("output") or 0.0)
    else:
        model = resolve_model_id(trace.model or "claude-sonnet-4-5")
        part = usage_cost_breakdown_usd(
            model,
            input_tokens=int(trace.input_tokens or 0),
            output_tokens=int(trace.output_tokens or 0),
            cache_read_tokens=int(trace.cached_input_tokens or 0),
            cache_write_tokens=int(trace.cache_creation_input_tokens or 0),
            thinking_tokens=int(trace.thinking_tokens or 0),
        )
        breakdown["input"] = float(part.get("input") or 0.0)
        breakdown["cache_read"] = float(part.get("cache_read") or 0.0)
        breakdown["cache_write"] = float(part.get("cache_write") or 0.0)
        breakdown["output"] = float(part.get("output") or 0.0)
    return {k: round(v, 6) for k, v in breakdown.items()}


def _best_trace_cost(trace: Trace) -> tuple[float, float, float]:
    reported = _trace_cost_usd(trace)
    estimated = _estimated_trace_cost_usd(trace)
    chosen = estimated if estimated > 0 else reported
    if chosen <= 0:
        chosen = reported
    return round(chosen, 6), reported, estimated


def _claude_subagent_count(session_id: str) -> int:
    if not session_id:
        return 0
    try:
        from atelier.core.capabilities.savings_summary import claude_transcript_candidates

        for candidate in claude_transcript_candidates(session_id):
            if candidate.stem != session_id:
                continue
            subagent_dir = candidate.parent / session_id / "subagents"
            if subagent_dir.is_dir():
                return len(list(subagent_dir.glob("*.jsonl")))
    except Exception:
        logging.exception("failed to count claude subagents for session=%s", session_id)
    return 0


def _claude_subagent_cost_usd(session_id: str) -> float:
    if not session_id:
        return 0.0
    try:
        from atelier.core.capabilities.savings_summary import claude_transcript_candidates, read_transcript_stats

        for candidate in claude_transcript_candidates(session_id):
            if candidate.stem != session_id:
                continue
            subagent_dir = candidate.parent / session_id / "subagents"
            if not subagent_dir.is_dir():
                return 0.0
            total = 0.0
            for subagent_file in subagent_dir.glob("*.jsonl"):
                stats = read_transcript_stats(subagent_file)
                if stats is not None:
                    total += float(stats.est_cost_usd or 0.0)
            return round(total, 6)
    except Exception:
        logging.exception("failed to compute claude subagent cost for session=%s", session_id)
    return 0.0


def _subagent_cost_from_trace(trace: Trace) -> float:
    total = 0.0
    for entry in trace.usage_entries:
        source_type = str(entry.source_type or "").lower()
        source_id = str(entry.source_id or "").lower()
        tool_name = str(entry.tool_name or "").lower()
        if "subagent" in source_type or "subagent" in source_id or tool_name in _SUBAGENT_TOOL_NAMES:
            total += float(entry.cost_usd or 0.0)
    return round(total, 6)


def _artifact_subagent_count(store: ContextStore, trace: Trace) -> int:
    count = 0
    for artifact_id in trace.raw_artifact_ids:
        artifact = store.get_raw_artifact(artifact_id)
        if artifact is None:
            continue
        rel = str(artifact.relative_path or "").lower()
        if "subagent" in rel or "/subagents/" in rel or "\\subagents\\" in rel:
            count += 1
    return count


def _host_subagent_count(store: ContextStore, host_name: str, session_id: str, trace: Trace) -> int:
    count = _subagent_total(trace)
    count = max(count, _artifact_subagent_count(store, trace))
    if host_name == "claude" and session_id:
        count = max(count, _claude_subagent_count(session_id))
    return count


def _host_subagent_cost_usd(host_name: str, session_id: str, trace: Trace) -> float:
    heuristic = _subagent_cost_from_trace(trace)
    if host_name == "claude":
        return max(heuristic, _claude_subagent_cost_usd(session_id))
    return heuristic


def _claude_transcript_block(session_id: str) -> TranscriptSavingsBlock | None:
    """Savings recovered from the session's own transcript file.

    The stop hook embeds its summary (est. cost / savings / context carry) in
    the conversation, so the numbers live inside the host session file itself
    — the only source that exists when analyzing someone else's sessions.
    """
    if not session_id:
        return None
    try:
        from atelier.core.capabilities.savings_summary import (
            claude_transcript_candidates,
            read_transcript_savings_block,
        )

        for candidate in claude_transcript_candidates(session_id):
            if candidate.stem != session_id:
                continue
            return read_transcript_savings_block(candidate)
    except Exception:
        logging.exception("failed to read transcript savings for session=%s", session_id)
    return None


def _cache_read_rate(model: str, breakdown: dict[str, float], cache_read_tokens: int) -> float:
    """Per-token cache-read USD rate: model rate card first, observed fallback."""
    try:
        from atelier.core.capabilities.pricing import get_model_pricing
        from atelier.core.capabilities.savings_summary import resolve_model_id

        pricing = get_model_pricing(resolve_model_id(model))
        if pricing is not None and pricing.known and pricing.cache_read > 0:
            return float(pricing.cache_read) / 1_000_000
    except Exception:
        logging.exception("failed to resolve cache-read rate for model=%s", model)
    if cache_read_tokens > 0 and breakdown["cache_read"] > 0:
        return breakdown["cache_read"] / cache_read_tokens
    return 0.0


def _term_width() -> int:
    return shutil.get_terminal_size(fallback=(120, 24)).columns


def _wrap_csv_items(items: list[str], *, width: int | None = None) -> list[str]:
    max_width = (width or _term_width()) - 16  # 16 = label indent
    if not items:
        return ["(none)"]
    lines: list[str] = []
    current = ""
    for item in items:
        chunk = item if not current else f", {item}"
        if current and len(current) + len(chunk) > max_width:
            lines.append(current)
            current = item
        else:
            current += chunk
    if current:
        lines.append(current)
    return lines


def _fmt_tok_compact(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _emit_kv(label: str, value: str) -> None:
    click.echo(click.style(f"    {label:<11}", fg="cyan") + value)


def _emit_tree_rows(rows: list[tuple[str, str]]) -> None:
    """Emit a list of (label, value) pairs with ├─ / └─ connectors.

    An empty label signals a continuation line (tool-list wrap, etc.);
    those are indented under the previous connector.
    """
    for i, (label, value) in enumerate(rows):
        last = i == len(rows) - 1
        connector = "└─" if last else "├─"
        if label:
            click.echo(click.style(f"  {connector} {label:<10}", fg="cyan") + value)
        else:
            # continuation: align under the value column
            prefix = "   " if last else "  │"
            click.echo(f"{prefix}  {' ' * 10} {value}")


def _is_atelier_tool_name(name: str) -> bool:
    lowered = (name or "").strip().lower()
    return lowered.startswith("mcp__atelier__") or lowered.startswith("mcp__plugin_atelier_atelier__")


# Builtin tools whose repeated calls Atelier batches/dedupes into fewer calls.
# Read-like builtin tools whose repeated calls Atelier dedupes/batches.
# Deliberately excludes bash/shell/edit: repeated commands and edits are
# usually distinct work, not redundant re-reads.
_POTENTIAL_BATCHABLE = ("read", "grep", "glob", "search")

# Fallback context-window cap when the model's rate card has no threshold.
_DEFAULT_CONTEXT_CAP = 200_000


def _context_window_cap(model: str) -> int:
    """Per-request context ceiling for sanity-capping avg context per call."""
    try:
        from atelier.core.capabilities.pricing import get_model_pricing
        from atelier.core.capabilities.savings_summary import resolve_model_id

        pricing = get_model_pricing(resolve_model_id(model))
        if pricing is not None and pricing.known:
            threshold = pricing.long_context_threshold()
            if threshold > 0:
                return int(threshold)
    except Exception:
        logging.exception("failed to resolve context window for model=%s", model)
    return _DEFAULT_CONTEXT_CAP


def _builtin_potential(
    trace: Trace,
    input_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    context_cap: int = _DEFAULT_CONTEXT_CAP,
) -> dict[str, Any]:
    """Estimate what Atelier would have saved, with the same credit model as
    real savings: avoidable duplicate read-like calls skip a context re-read
    (saved), and their outputs stay out of context on later turns (carry).

    Token estimates here are raw; the caller bounds the priced total by the
    session's actual cache spend — you cannot save more than was spent.
    """
    by_tool: dict[str, int] = {}
    out_by_tool: dict[str, int] = {}
    atelier_calls = 0
    builtin_calls = 0
    for tool in trace.tools_called:
        name = str(tool.name or "").strip()
        count = int(tool.count or 0)
        if count <= 0:
            continue
        key = name.lower()
        by_tool[key] = by_tool.get(key, 0) + count
        out_by_tool[key] = out_by_tool.get(key, 0) + int(tool.output_tokens or 0)
        if _is_atelier_tool_name(name):
            atelier_calls += count
        else:
            builtin_calls += count

    potential_calls_saved = 0
    dup_output_tokens = 0
    for key in _POTENTIAL_BATCHABLE:
        count = by_tool.get(key, 0)
        if count > 1:
            potential_calls_saved += count - 1
            # Output share of the duplicate calls — results Atelier dedup
            # would have kept out of context.
            dup_output_tokens += out_by_tool.get(key, 0) * (count - 1) // count

    # Average context re-sent per call, capped at the model's per-request
    # window: totals divided by an undercounted call tally must never imply
    # an impossible context size.
    total_context_tokens = max(0, int(input_tokens) + int(cache_read_tokens) + int(cache_write_tokens))
    avg_per_call = total_context_tokens // max(1, _tool_call_total(trace))
    avg_per_call = min(avg_per_call, max(1, int(context_cap)))
    potential_tokens_saved = int(max(0, potential_calls_saved * avg_per_call))

    # Carry: deduped outputs are not re-read on later turns. Average position
    # of a call leaves ~half the session's turns after it.
    turns = len(trace.usage_entries)
    potential_carry_tokens = int(max(0, dup_output_tokens) * (turns // 2))

    return {
        "builtin_calls": builtin_calls,
        "atelier_calls": atelier_calls,
        "calls_saved": int(max(0, potential_calls_saved)),
        "tokens_saved": potential_tokens_saved,
        "carry_tokens": potential_carry_tokens,
    }


def _trace_model(trace: Trace) -> str:
    if trace.model:
        return trace.model
    if trace.model_usages:
        first = trace.model_usages[0]
        if first.model:
            return first.model
    return "-"


def _build_session_row(trace: Trace, store: ContextStore, host_name: str) -> dict[str, Any]:
    """Build a display row dict from a single imported trace."""
    sid = (trace.session_id or trace.id or "").strip()
    input_tokens = int(trace.input_tokens or 0)
    cache_read_tokens = int(trace.cached_input_tokens or 0)
    cache_write_tokens = int(trace.cache_creation_input_tokens or 0)
    output_tokens = int(trace.output_tokens or 0)
    total_cost_usd, reported_cost_usd, estimated_cost_usd = _best_trace_cost(trace)
    model = _trace_model(trace)
    pricing_model = model if model != "-" else ""  # "-" is a display sentinel; don't warn on it
    breakdown = _estimated_trace_cost_breakdown(trace)
    subagents = _host_subagent_count(store, host_name, sid, trace)
    subagent_cost_usd = _host_subagent_cost_usd(host_name, sid, trace)
    potential = _builtin_potential(
        trace,
        input_tokens=input_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        context_cap=_context_window_cap(pricing_model),
    )
    saved_usd = 0.0
    carry_usd = 0.0
    carry_tokens = 0
    saved_tokens = 0
    calls_avoided = 0
    block_tool_calls = 0
    if host_name == "claude":
        block = _claude_transcript_block(sid)
        if block is not None:
            saved_usd = float(block.saved_usd)
            saved_tokens = int(block.saved_tokens)
            calls_avoided = int(block.calls_avoided)
            carry_usd = float(block.carry_usd)
            carry_tokens = int(block.carry_tokens)
            block_tool_calls = int(block.tool_calls)
            if block.est_cost_usd > 0:
                total_cost_usd = block.est_cost_usd
                estimated_cost_usd = block.est_cost_usd
                bucket_sum = sum(breakdown.values())
                if bucket_sum > 0:
                    ratio = block.est_cost_usd / bucket_sum
                    breakdown = {k: v * ratio for k, v in breakdown.items()}
    cr_rate = _cache_read_rate(pricing_model, breakdown, cache_read_tokens)
    potential_saved_usd = float(potential["tokens_saved"]) * cr_rate
    potential_carry_usd = float(potential["carry_tokens"]) * cr_rate
    potential_tokens_saved = int(potential["tokens_saved"])
    potential_carry_tokens = int(potential["carry_tokens"])
    total_calls = int(potential["builtin_calls"]) + int(potential["atelier_calls"])
    builtin_share = int(potential["builtin_calls"]) / max(1, total_calls)
    potential_cap_usd = (breakdown["cache_read"] + breakdown["cache_write"]) * builtin_share
    potential_total_usd = potential_saved_usd + potential_carry_usd
    if potential_total_usd > potential_cap_usd:
        scale = (potential_cap_usd / potential_total_usd) if potential_total_usd > 0 else 0.0
        potential_saved_usd *= scale
        potential_carry_usd *= scale
        potential_tokens_saved = int(potential_tokens_saved * scale)
        potential_carry_tokens = int(potential_carry_tokens * scale)
    return {
        "host": host_name,
        "session_id": sid,
        "trace_id": trace.id,
        "created_at": trace.created_at.isoformat() if trace.created_at else "",
        "task": trace.task,
        "model": model,
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(total_cost_usd, 6),
        "reported_cost_usd": round(reported_cost_usd, 6),
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "cost_input_usd": round(breakdown["input"], 6),
        "cost_cache_read_usd": round(breakdown["cache_read"], 6),
        "cost_cache_write_usd": round(breakdown["cache_write"], 6),
        "cost_output_usd": round(breakdown["output"], 6),
        "saved_usd": round(saved_usd, 6),
        "saved_tokens": int(saved_tokens),
        "calls_avoided": int(calls_avoided),
        "carry_usd": round(carry_usd, 6),
        "carry_tokens": int(carry_tokens),
        "tool_calls": _tool_call_total(trace),
        "subagents": subagents,
        "subagent_cost_usd": round(subagent_cost_usd, 6),
        "builtin_calls": int(potential["builtin_calls"]),
        "atelier_calls": int(potential["atelier_calls"]),
        "potential_calls_saved": int(potential["calls_saved"]),
        "potential_tokens_saved": potential_tokens_saved,
        "potential_saved_usd": round(potential_saved_usd, 6),
        "potential_carry_tokens": potential_carry_tokens,
        "potential_carry_usd": round(potential_carry_usd, 6),
        "block_tool_calls": block_tool_calls,
        "first_user": str(trace.task or "").strip(),
        "commands": [
            c if isinstance(c, str) else str(c.command)
            for c in trace.commands_run
            if isinstance(c, str) or hasattr(c, "command")
        ],
        "tools": [{"name": t.name, "count": int(t.count or 0)} for t in trace.tools_called],
        "subagent_names": dict(trace.telemetry.get("subagent_names", {})) if trace.telemetry else {},
        "source": "host_sessions",
    }


def _print_session_row(row: dict[str, Any], verbose: bool) -> None:
    """Print a single session row using tree-style connectors."""
    created = str(row["created_at"])[:19].replace("T", " ") if row["created_at"] else "-"
    sid = str(row["session_id"]) if row["session_id"] else "-"
    model = str(row["model"] or "-")[:32]
    click.echo("")
    click.secho(f"  {created}  {sid}  {model}", bold=True)

    detail: list[tuple[str, str]] = []

    # tokens
    detail.append((
        "tokens",
        f"in={_fmt_tok_compact(int(row['input_tokens']))}"
        f"  cR={_fmt_tok_compact(int(row['cache_read_tokens']))}"
        f"  cW={_fmt_tok_compact(int(row['cache_write_tokens']))}"
        f"  out={_fmt_tok_compact(int(row['output_tokens']))}",
    ))

    # cost
    detail.append((
        "cost",
        f"${float(row['cost_usd']):.4f}  "
        + click.style(
            f"(in ${float(row['cost_input_usd']):.4f} · cR ${float(row['cost_cache_read_usd']):.4f}"
            f" · cW ${float(row['cost_cache_write_usd']):.4f} · out ${float(row['cost_output_usd']):.4f})",
            dim=True,
        ),
    ))

    if row.get("source") == "trace_fallback":
        est = float(row["estimated_cost_usd"])
        rep = float(row["reported_cost_usd"])
        if est > 0 and rep > 0 and abs(est - rep) / max(est, rep) > 0.25:
            detail.append(("cost-check", click.style(f"estimated ${est:.4f} vs host-reported ${rep:.4f}", fg="yellow")))

    # subagents
    if int(row["subagents"]) > 0:
        sub_cost = float(row["subagent_cost_usd"])
        cost_detail = f" · ≈${sub_cost:.4f} (included in cost)" if sub_cost > 0 else ""
        subagent_names: dict[str, int] = row.get("subagent_names") or {}
        if subagent_names:
            name_parts = [f"{n}x{c}" for n, c in sorted(subagent_names.items(), key=lambda x: -x[1])]
            wrapped_sub = _wrap_csv_items(name_parts)
            detail.append(("subagents", wrapped_sub[0] + cost_detail))
            for extra_line in wrapped_sub[1:]:
                detail.append(("", extra_line))
        else:
            detail.append(("subagents", f"{int(row['subagents'])}{cost_detail}"))

    # savings: merge saved + carry + baseline into one row
    saved = float(row["saved_usd"])
    carry = float(row["carry_usd"])
    row_cost = float(row["cost_usd"])
    savings_parts: list[str] = []
    if saved > 0 or int(row["saved_tokens"]) > 0 or int(row["calls_avoided"]) > 0:
        sp = [click.style(f"${saved:.4f}", fg="green")]
        if int(row["saved_tokens"]) > 0:
            sp.append(click.style(f"{_fmt_tok_compact(int(row['saved_tokens']))} tok saved", fg="green"))
        if int(row["calls_avoided"]) > 0:
            sp.append(click.style(f"{int(row['calls_avoided'])} calls avoided", fg="green"))
        savings_parts.append(" · ".join(sp))
    if carry > 0:
        savings_parts.append(
            click.style(
                f"carry ${carry:.4f} · {_fmt_tok_compact(int(row['carry_tokens']))} tok",
                fg="magenta",
            )
        )
    if row_cost > 0 and (saved + carry) > 0:
        baseline = row_cost + saved + carry
        savings_parts.append(
            click.style(
                f"baseline ≈${baseline:.4f} (-{100 * (saved + carry) / baseline:.1f}%)",
                dim=True,
            )
        )
    if savings_parts:
        detail.append(("savings", "  ·  ".join(savings_parts)))

    # calls
    detail.append((
        "calls",
        f"{int(row['tool_calls'])} total · {int(row['atelier_calls'])} atelier"
        f" · {int(row['builtin_calls'])} builtin",
    ))

    trace_calls = int(row["tool_calls"])
    block_calls = int(row.get("block_tool_calls") or 0)
    if block_calls > 0 and trace_calls > 0 and trace_calls / block_calls < 0.5:
        detail.append((
            "calls-check",
            click.style(
                f"trace import counted {trace_calls} but session file recorded {block_calls}"
                f" — trace parser may have missed some calls",
                fg="red",
            ),
        ))

    # potential
    if int(row["potential_calls_saved"]) > 0:
        pot = f"≈{int(row['potential_calls_saved'])} avoidable · " + click.style(
            f"saved ${float(row['potential_saved_usd']):.4f} ({_fmt_tok_compact(int(row['potential_tokens_saved']))} tok)",
            fg="yellow",
        )
        if float(row["potential_carry_usd"]) > 0:
            pot += " + " + click.style(
                f"carry ${float(row['potential_carry_usd']):.4f}"
                f" ({_fmt_tok_compact(int(row['potential_carry_tokens']))} tok)",
                fg="magenta",
            )
        detail.append(("potential", pot + click.style("  via Atelier", dim=True)))

    # tools (may wrap)
    tool_items = [f"{t['name']}x{t['count']}" for t in (row["tools"] or [])]
    wrapped_tools = _wrap_csv_items(tool_items)
    detail.append(("tools", wrapped_tools[0]))
    for extra_line in wrapped_tools[1:]:
        detail.append(("", extra_line))

    # prompt
    first_user = str(row["first_user"] or "").replace("\n", " ").strip()
    max_prompt = max(40, _term_width() - 16)
    if len(first_user) > max_prompt:
        first_user = first_user[: max_prompt - 3] + "..."
    detail.append(("prompt", first_user or "(none)"))

    if verbose:
        for cmd in (row["commands"] or [])[:8]:
            detail.append(("cmd", cmd))

    _emit_tree_rows(detail)


def _sync_hosts_from_source(
    *,
    store_root: Path,
    selected_hosts: list[str],
    force: bool,
    path: Path | None,
) -> dict[str, int]:
    from atelier.gateway.cli.commands.hosts import _ensure_import_progress_logging
    from atelier.gateway.hosts.session_parsers.registry import iter_importer_classes

    _ensure_import_progress_logging()
    store = _load_store(store_root)
    store.init()
    counts: dict[str, int] = {}
    host_set = set(selected_hosts)
    for host_name, importer_cls in iter_importer_classes():
        if host_set and host_name not in host_set:
            continue
        try:
            importer = importer_cls(store)
            ids = importer.import_all(path, force=force) if path is not None else importer.import_all(force=force)
            counts[host_name] = len(ids)
        except Exception:
            logging.exception("session hosts sync failed for host=%s", host_name)
            counts[host_name] = 0
    return counts


def _path_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def _pick_live_sessions(
    items: list[Any],
    *,
    path_of: Callable[[Any], Path],
    limit: int,
    scan: int,
    session_filter: str = "",
    cutoff: datetime | None = None,
) -> list[Any]:
    """Newest-first lazy selection of session files for a live scan.

    Sorts candidates by file mtime (newest first), applies the cheap
    pre-import filters (--id substring against the filename stem, --since
    against mtime), and returns only as many sessions as the display can
    show — importing hundreds of files to render a handful of rows is
    wasted work. ``scan`` stays as the hard upper bound on candidates
    considered.
    """
    if limit <= 0 or scan <= 0:
        return []
    newest = sorted(items, key=lambda item: _path_mtime(path_of(item)), reverse=True)[:scan]
    picked: list[Any] = []
    for item in newest:
        p = path_of(item)
        if cutoff is not None and datetime.fromtimestamp(_path_mtime(p), tz=UTC) < cutoff:
            break  # newest-first: everything after this is older still
        if session_filter and session_filter not in p.stem.lower():
            continue
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def _scan_hosts_live(
    *,
    selected_hosts: list[str],
    force: bool,
    path: Path | None,
    max_per_host: int,
    limit: int,
    session_filter: str = "",
    cutoff: datetime | None = None,
) -> tuple[dict[str, int], ContextStore, tempfile.TemporaryDirectory[str]]:
    from atelier.gateway.hosts.session_parsers.claude import (
        ClaudeImporter,
        find_claude_sessions,
    )
    from atelier.gateway.hosts.session_parsers.codex import (
        CodexImporter,
        find_codex_sessions,
    )
    from atelier.gateway.hosts.session_parsers.gemini import (
        GeminiImporter,
        find_gemini_sessions,
    )
    from atelier.gateway.hosts.session_parsers.registry import iter_importer_classes

    tmp = tempfile.TemporaryDirectory(prefix="atelier-session-hosts-")
    tmp_root = Path(tmp.name)
    store = ContextStore(tmp_root)
    store.init()

    counts: dict[str, int] = {}
    host_set = set(selected_hosts)
    for host_name, importer_cls in iter_importer_classes():
        if host_set and host_name not in host_set:
            continue
        try:
            # Lazy fast-path: pick only the newest sessions the display can
            # actually show (limit rows, pre-filtered), never the full scan.
            if host_name == "codex":
                codex_importer = CodexImporter(store)
                imported = 0
                picked_paths = _pick_live_sessions(
                    list(find_codex_sessions(path)),
                    path_of=lambda p: p,
                    limit=limit,
                    scan=max_per_host,
                    session_filter=session_filter,
                    cutoff=cutoff,
                )
                for session_path in picked_paths:
                    if codex_importer.import_session(session_path, force=force):
                        imported += 1
                counts[host_name] = imported
                continue
            if host_name == "gemini":
                gemini_importer = GeminiImporter(store)
                imported = 0
                picked_paths = _pick_live_sessions(
                    list(find_gemini_sessions(path)),
                    path_of=lambda p: p,
                    limit=limit,
                    scan=max_per_host,
                    session_filter=session_filter,
                    cutoff=cutoff,
                )
                for session_path in picked_paths:
                    if gemini_importer.import_session(session_path, force=force):
                        imported += 1
                counts[host_name] = imported
                continue
            if host_name == "claude":
                claude_importer = ClaudeImporter(store)
                imported = 0
                claude_root = path if path is not None else None
                picked_sessions = _pick_live_sessions(
                    list(find_claude_sessions(claude_root)),
                    path_of=lambda item: item[1],
                    limit=limit,
                    scan=max_per_host,
                    session_filter=session_filter,
                    cutoff=cutoff,
                )
                for workspace_slug, session_path in picked_sessions:
                    if claude_importer.import_session(workspace_slug, session_path, force=force):
                        imported += 1
                counts[host_name] = imported
                continue

            generic_importer: Any = importer_cls(store)
            imported_ids = list(
                generic_importer.import_all(path, force=force, limit=limit)
                if path is not None
                else generic_importer.import_all(force=force, limit=limit)
            )
            counts[host_name] = len(imported_ids)
        except Exception:
            logging.exception("session hosts live scan failed for host=%s", host_name)
            counts[host_name] = 0
    return counts, store, tmp


def _stream_hosts_live(
    *,
    selected_hosts: list[str],
    force: bool,
    path: Path | None,
    max_per_host: int,
    limit: int,
    session_filter: str = "",
    cutoff: datetime | None = None,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Scan host session files and stream-display each session as it's imported.

    For claude/codex/gemini/copilot/opencode: per-session streaming (each session
    appears immediately after it's parsed).
    For other generic importers: per-host streaming (sessions appear together after
    import_all completes for that host).
    """
    from atelier.gateway.hosts.session_parsers.claude import ClaudeImporter, find_claude_sessions
    from atelier.gateway.hosts.session_parsers.codex import CodexImporter, find_codex_sessions
    from atelier.gateway.hosts.session_parsers.copilot import CopilotImporter, find_copilot_sessions
    from atelier.gateway.hosts.session_parsers.gemini import GeminiImporter, find_gemini_sessions
    from atelier.gateway.hosts.session_parsers.opencode import (  # type: ignore[attr-defined]
        OpenCodeImporter,
        find_opencode_sessions,
    )
    from atelier.gateway.hosts.session_parsers.opencode import (
        _ms_to_dt as _oc_ms_to_dt,
    )
    from atelier.gateway.hosts.session_parsers.registry import iter_importer_classes

    tmp = tempfile.TemporaryDirectory(prefix="atelier-session-hosts-")
    tmp_root = Path(tmp.name)
    store = ContextStore(tmp_root)
    store.init()

    host_set = set(selected_hosts)
    any_found = False
    collected_rows: list[dict[str, Any]] = []

    for host_name, importer_cls in iter_importer_classes():
        if host_set and host_name not in host_set:
            continue
        try:
            if host_name == "codex":
                importer_c = CodexImporter(store)
                picked = _pick_live_sessions(
                    list(find_codex_sessions(path)),
                    path_of=lambda p: p,
                    limit=limit,
                    scan=max_per_host,
                    session_filter=session_filter,
                    cutoff=cutoff,
                )
                if not picked:
                    continue
                any_found = True
                click.echo("")
                click.secho(host_name, fg="magenta", bold=True)
                click.echo(f"  scanned this run: {len(picked)}")
                for session_path in picked:
                    tid = importer_c.import_session(session_path, force=force)
                    if tid:
                        trace = store.get_trace(tid)
                        if trace:
                            row = _build_session_row(trace, store, host_name)
                            collected_rows.append(row)
                            _print_session_row(row, verbose)
                continue

            if host_name == "gemini":
                importer_g = GeminiImporter(store)
                picked_g = _pick_live_sessions(
                    list(find_gemini_sessions(path)),
                    path_of=lambda p: p,
                    limit=limit,
                    scan=max_per_host,
                    session_filter=session_filter,
                    cutoff=cutoff,
                )
                if not picked_g:
                    continue
                any_found = True
                click.echo("")
                click.secho(host_name, fg="magenta", bold=True)
                click.echo(f"  scanned this run: {len(picked_g)}")
                for session_path in picked_g:
                    tid = importer_g.import_session(session_path, force=force)
                    if tid:
                        trace = store.get_trace(tid)
                        if trace:
                            row = _build_session_row(trace, store, host_name)
                            collected_rows.append(row)
                            _print_session_row(row, verbose)
                continue

            if host_name == "claude":
                claude_imp = ClaudeImporter(store)
                claude_root = path if path is not None else None
                picked_cl = _pick_live_sessions(
                    list(find_claude_sessions(claude_root)),
                    path_of=lambda item: item[1],
                    limit=limit,
                    scan=max_per_host,
                    session_filter=session_filter,
                    cutoff=cutoff,
                )
                if not picked_cl:
                    continue
                any_found = True
                click.echo("")
                click.secho(host_name, fg="magenta", bold=True)
                click.echo(f"  scanned this run: {len(picked_cl)}")
                for workspace_slug, session_path in picked_cl:
                    tid = claude_imp.import_session(workspace_slug, session_path, force=force)
                    if tid:
                        trace = store.get_trace(tid)
                        if trace:
                            row = _build_session_row(trace, store, host_name)
                            collected_rows.append(row)
                            _print_session_row(row, verbose)
                continue

            if host_name == "copilot":
                importer_cop = CopilotImporter(store)
                picked_cop = _pick_live_sessions(
                    list(find_copilot_sessions(path)),
                    path_of=lambda p: p,
                    limit=limit,
                    scan=max_per_host,
                    session_filter=session_filter,
                    cutoff=cutoff,
                )
                if not picked_cop:
                    continue
                any_found = True
                click.echo("")
                click.secho(host_name, fg="magenta", bold=True)
                click.echo(f"  scanned this run: {len(picked_cop)}")
                for session_dir in picked_cop:
                    tid = importer_cop.import_session(session_dir, force=force)
                    if tid:
                        trace = store.get_trace(tid)
                        if trace:
                            row = _build_session_row(trace, store, host_name)
                            collected_rows.append(row)
                            _print_session_row(row, verbose)
                continue

            if host_name == "opencode":
                importer_oc = OpenCodeImporter(store)
                oc_db = path or (Path.home() / ".local/share/opencode/opencode.db")
                if oc_db.exists():
                    all_oc = find_opencode_sessions(oc_db)
                    if cutoff is not None:
                        all_oc = [r for r in all_oc if _oc_ms_to_dt(r.get("time_created")) >= cutoff]
                    picked_oc = all_oc[:limit]
                    if picked_oc:
                        any_found = True
                        click.echo("")
                        click.secho(host_name, fg="magenta", bold=True)
                        click.echo(f"  scanned this run: {len(picked_oc)}")
                        for session_row in picked_oc:
                            tid = importer_oc.import_session(session_row, oc_db, force=force)
                            if tid:
                                trace = store.get_trace(tid)
                                if trace:
                                    row = _build_session_row(trace, store, host_name)
                                    collected_rows.append(row)
                                    _print_session_row(row, verbose)
                continue

            # Generic importer: batch import_all then stream display
            generic_importer: Any = importer_cls(store)
            imported_ids = list(
                generic_importer.import_all(path, force=force, limit=limit)
                if path is not None
                else generic_importer.import_all(force=force, limit=limit)
            )
            if not imported_ids:
                continue
            any_found = True
            click.echo("")
            click.secho(host_name, fg="magenta", bold=True)
            click.echo(f"  scanned this run: {len(imported_ids)}")
            displayed = 0
            for sid in imported_ids:
                trace = store.get_trace(sid)
                if trace is None:
                    continue
                row = _build_session_row(trace, store, host_name)
                if session_filter and session_filter not in (row.get("session_id") or "").lower():
                    continue
                _print_session_row(row, verbose)
                collected_rows.append(row)
                displayed += 1
                if displayed >= limit:
                    break
        except Exception:
            logging.exception("session hosts live scan failed for host=%s", host_name)

    tmp.cleanup()

    if not any_found:
        click.echo("No host sessions found for the selected filters.")

    return collected_rows


@session_group.command("hosts")
@click.option(
    "--host",
    "hosts",
    multiple=True,
    type=click.Choice(list(SUPPORTED_SESSION_IMPORT_HOSTS)),
    help="Filter to one or more hosts. Repeat option to include multiple hosts.",
)
@click.option("--limit", default=5, show_default=True, type=click.IntRange(min=1), help="Rows per host.")
@click.option(
    "--scan",
    default=500,
    show_default=True,
    type=click.IntRange(min=1),
    help="Upper bound on live pre-scan per host; effective live import cap is min(--scan, --limit).",
)
@click.option("--since", default=None, help="Look-back window, e.g. 7d, 24h.")
@click.option("--id", "session_id_filter", default=None, help="Filter by session-id substring.")
@click.option("--verbose", is_flag=True, default=False, help="Show per-session tool and command details.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output JSON.")
@click.option(
    "--source",
    "source_mode",
    type=click.Choice(["live", "store"]),
    default="live",
    show_default=True,
    help="live=read directly from host session directories via a temporary store (no persistent import), store=read existing Atelier store only.",
)
@click.option("--force", is_flag=True, default=False, help="Force host re-import while syncing.")
@click.option(
    "--path",
    type=click.Path(path_type=Path),
    default=None,
    help="Override source path for the selected host (requires exactly one --host).",
)
@click.pass_context
def session_hosts_cmd(
    ctx: click.Context,
    hosts: tuple[str, ...],
    limit: int,
    scan: int,
    since: str | None,
    session_id_filter: str | None,
    verbose: bool,
    as_json: bool,
    source_mode: str,
    force: bool,
    path: Path | None,
) -> None:
    """List host sessions derived from host session files."""
    root: Path = ctx.obj["root"]
    selected_hosts = list(hosts) if hosts else list(SUPPORTED_SESSION_IMPORT_HOSTS)

    if path is not None and len(selected_hosts) != 1:
        raise click.ClickException("--path requires exactly one --host")

    cutoff = datetime.now(UTC) - _parse_duration(since) if since else None
    session_filter = (session_id_filter or "").strip().lower()

    if as_json:
        # Batch mode for JSON output: scan all hosts, collect rows, then dump.
        sync_counts: dict[str, int] = {}
        temp_handle: tempfile.TemporaryDirectory[str] | None = None
        if source_mode == "live":
            sync_counts, store, temp_handle = _scan_hosts_live(
                selected_hosts=selected_hosts,
                force=force,
                path=path,
                max_per_host=scan,
                limit=limit,
                session_filter=session_filter,
                cutoff=cutoff,
            )
        else:
            store = _load_store(root)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for host_name in selected_hosts:
            traces = store.list_traces(host=host_name, since=cutoff, limit=scan)
            rows: list[dict[str, Any]] = []
            for trace in traces:
                sid = (trace.session_id or trace.id or "").strip()
                if session_filter and session_filter not in sid.lower():
                    continue
                rows.append(_build_session_row(trace, store, host_name))
                if len(rows) >= limit:
                    break
            if rows:
                grouped[host_name] = rows

        if temp_handle is not None:
            temp_handle.cleanup()

        click.echo(
            json.dumps(
                {"source": source_mode, "scan_counts": sync_counts, "hosts": grouped},
                indent=2,
                default=str,
            )
        )
        return

    # Text display: stream per-host so each host's sessions appear immediately.
    if source_mode == "store":
        store = _load_store(root)
        any_found = False
        all_store_rows: list[dict[str, Any]] = []
        for host_name in sorted(selected_hosts):
            traces = store.list_traces(host=host_name, since=cutoff, limit=scan)
            rows_store: list[dict[str, Any]] = []
            for trace in traces:
                sid = (trace.session_id or trace.id or "").strip()
                if session_filter and session_filter not in sid.lower():
                    continue
                rows_store.append(_build_session_row(trace, store, host_name))
                if len(rows_store) >= limit:
                    break
            if rows_store:
                any_found = True
                click.echo("")
                click.secho(host_name, fg="magenta", bold=True)
                for row in rows_store:
                    _print_session_row(row, verbose)
                all_store_rows.extend(rows_store)
        if not any_found:
            click.echo("No host sessions found for the selected filters.")
        elif all_store_rows:
            click.echo("")
            click.secho("─" * min(60, _term_width()), dim=True)
            _print_stats(all_store_rows, since or f"{limit} sessions", top=0, show_header=False)
        return

    # live mode + text: stream each host as it's scanned
    displayed_rows = _stream_hosts_live(
        selected_hosts=selected_hosts,
        force=force,
        path=path,
        max_per_host=scan,
        limit=limit,
        session_filter=session_filter,
        cutoff=cutoff,
        verbose=verbose,
    )
    active_rows = [r for r in displayed_rows if int(r["tool_calls"]) > 0 or int(r["input_tokens"]) > 0]
    if active_rows:
        click.echo("")
        click.secho("─" * min(60, _term_width()), dim=True)
        _print_stats(active_rows, since or f"{limit} sessions", top=0, show_header=False)



# ---------------------------------------------------------------------------
# session stats
# ---------------------------------------------------------------------------

def _print_stats(
    rows: list[dict[str, Any]],
    since_label: str,
    top: int,
    show_header: bool = True,
) -> None:
    """Print aggregate usage statistics from a list of session rows."""
    if not rows:
        click.echo("No sessions found.")
        return

    # --- aggregate totals ---
    n = len(rows)
    n_atelier = sum(1 for r in rows if int(r["atelier_calls"]) > 0)
    total_cost = sum(float(r["cost_usd"]) for r in rows)
    total_saved = sum(float(r["saved_usd"]) for r in rows)
    total_carry = sum(float(r["carry_usd"]) for r in rows)
    total_in = sum(int(r["input_tokens"]) for r in rows)
    total_cr = sum(int(r["cache_read_tokens"]) for r in rows)
    total_cw = sum(int(r["cache_write_tokens"]) for r in rows)
    total_out = sum(int(r["output_tokens"]) for r in rows)
    total_calls = sum(int(r["tool_calls"]) for r in rows)
    total_atelier = sum(int(r["atelier_calls"]) for r in rows)
    total_builtin = sum(int(r["builtin_calls"]) for r in rows)
    total_subagents = sum(int(r["subagents"]) for r in rows)
    total_sub_cost = sum(float(r["subagent_cost_usd"]) for r in rows)
    total_pot_calls = sum(int(r["potential_calls_saved"]) for r in rows)
    total_pot_usd = sum(float(r["potential_saved_usd"]) for r in rows)
    total_pot_carry = sum(float(r["potential_carry_usd"]) for r in rows)

    # per-host aggregation
    host_agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        hn = str(r.get("host") or r.get("source") or "unknown")
        if hn not in host_agg:
            host_agg[hn] = {
                "sessions": 0, "cost": 0.0, "saved": 0.0, "carry": 0.0, "calls": 0,
                "atelier": 0, "builtin": 0, "pot_usd": 0.0,
            }
        ha = host_agg[hn]
        ha["sessions"] += 1
        ha["cost"] += float(r["cost_usd"])
        ha["saved"] += float(r["saved_usd"])
        ha["carry"] += float(r["carry_usd"])
        ha["calls"] += int(r["tool_calls"])
        ha["atelier"] += int(r["atelier_calls"])
        ha["builtin"] += int(r["builtin_calls"])
        ha["pot_usd"] += float(r["potential_saved_usd"]) + float(r["potential_carry_usd"])

    hosts_sorted = sorted(host_agg.items(), key=lambda x: -x[1]["cost"])

    # header
    hosts_label = ", ".join(h for h, _ in hosts_sorted if host_agg[h]["sessions"] > 0)
    if show_header:
        click.secho(f"Last {since_label}  ·  {n} sessions  ·  {hosts_label}", bold=True)
        if n_atelier > 0:
            click.echo(f"  {n_atelier} of {n} sessions used Atelier tools")

    # total section
    click.echo("")
    click.secho("  Total", bold=True)
    total_rows: list[tuple[str, str]] = []

    cost_str = click.style(f"${total_cost:.4f}", bold=True)
    if total_saved + total_carry > 0:
        baseline = total_cost + total_saved + total_carry
        pct = 100 * (total_saved + total_carry) / baseline
        savings_str = (
            click.style(f"  saved ${total_saved:.4f}", fg="green")
            + click.style(f" + carry ${total_carry:.4f}", fg="magenta")
            + click.style(f" via Atelier  (-{pct:.1f}% vs baseline ≈${baseline:.4f})", dim=True)
        )
        total_rows.append(("cost", cost_str + savings_str))
    else:
        total_rows.append(("cost", cost_str))

    total_rows.append((
        "tokens",
        f"in={_fmt_tok_compact(total_in)}"
        f"  cR={_fmt_tok_compact(total_cr)}"
        f"  cW={_fmt_tok_compact(total_cw)}"
        f"  out={_fmt_tok_compact(total_out)}",
    ))

    if total_calls > 0:
        atelier_pct = 100 * total_atelier / total_calls
        calls_str = (
            f"{total_calls:,} total · "
            + click.style(f"{total_atelier:,} atelier ({atelier_pct:.0f}%)", fg="cyan")
            + f" · {total_builtin:,} builtin"
        )
        total_rows.append(("calls", calls_str))

    if total_subagents > 0:
        sub_pct = 100 * total_sub_cost / total_cost if total_cost > 0 else 0.0
        total_rows.append(("subagents", f"{total_subagents} total · ≈${total_sub_cost:.4f} ({sub_pct:.1f}% of cost)"))

    if total_pot_calls > 0:
        total_rows.append((
            "potential",
            click.style(
                f"≈{total_pot_calls} avoidable · ≈${total_pot_usd + total_pot_carry:.4f} more savings via Atelier",
                fg="yellow",
            ),
        ))

    _emit_tree_rows(total_rows)

    # by host section
    if len(host_agg) > 1:
        click.echo("")
        click.secho("  By host", bold=True)
        host_rows: list[tuple[str, str]] = []
        for hn, ha in hosts_sorted:
            if ha["sessions"] == 0:
                continue
            atelier_pct = 100 * ha["atelier"] / ha["calls"] if ha["calls"] > 0 else 0.0
            parts = [
                click.style(f"${ha['cost']:.4f}", bold=True),
                f"{ha['sessions']} session{'s' if ha['sessions'] != 1 else ''}",
                f"{ha['calls']:,} calls ({atelier_pct:.0f}% atelier)",
            ]
            if ha["saved"] > 0 or ha["carry"] > 0:
                savings_parts = []
                if ha["saved"] > 0:
                    savings_parts.append(click.style(f"saved ${ha['saved']:.4f}", fg="green"))
                if ha["carry"] > 0:
                    savings_parts.append(click.style(f"carry ${ha['carry']:.4f}", fg="magenta"))
                parts.append(" + ".join(savings_parts))
            if ha["pot_usd"] > 0 and ha["atelier"] == 0:
                parts.append(click.style(f"potential ≈${ha['pot_usd']:.4f}", fg="yellow"))
            host_rows.append((hn, "  ·  ".join(parts)))
        _emit_tree_rows(host_rows)

    # top sessions section
    if top > 0:
        sorted_rows = sorted(rows, key=lambda r: -float(r["cost_usd"]))
        top_rows = [r for r in sorted_rows if float(r["cost_usd"]) > 0][:top]
        if top_rows:
            click.echo("")
            click.secho(f"  Top {len(top_rows)} sessions by cost", bold=True)
            session_rows: list[tuple[str, str]] = []
            for r in top_rows:
                date = str(r["created_at"])[:10] if r["created_at"] else "-"
                sid_short = str(r["session_id"] or "")[:8] if r["session_id"] else "-"
                model_short = str(r["model"] or "-")[:14]
                host_name_r = str(r.get("host") or "")
                prompt = str(r["first_user"] or "").replace("\n", " ").strip()[:60]
                cost = click.style(f"${float(r['cost_usd']):.4f}", bold=True)
                session_rows.append((
                    f"{date}  {sid_short}",
                    f"{cost}  {host_name_r:<8}  {model_short:<14}  {prompt}",
                ))
            _emit_tree_rows(session_rows)


@session_group.command("stats")
@click.option("--since", "since_str", default=None, help="Time window, e.g. 1d, 7d, 30d. Default: 7d.")
@click.option("--limit", default=None, type=int, help="Most-recent N sessions (alternative to --since).")
@click.option("--host", "hosts_filter", multiple=True, help="Filter by host (can repeat).")
@click.option("--source", type=click.Choice(["live", "store"]), default="live", show_default=True)
@click.option("--top", default=5, show_default=True, type=int, help="Top sessions by cost to list.")
@click.option("--path", "data_path", type=click.Path(path_type=Path), default=None)
@click.pass_context
def session_stats_cmd(
    ctx: click.Context,
    since_str: str | None,
    limit: int | None,
    hosts_filter: tuple[str, ...],
    source: str,
    top: int,
    data_path: Path | None,
) -> None:
    """Aggregate usage statistics. Use --since for a time window or --limit for the last N sessions."""
    if since_str and limit:
        raise click.UsageError("--since and --limit are mutually exclusive.")

    root = Path(ctx.obj["root"])
    selected_hosts = list(hosts_filter) if hosts_filter else list(SUPPORTED_SESSION_IMPORT_HOSTS)

    if limit:
        cutoff: datetime | None = None
        scan_cap = limit
        label = f"{limit} sessions"
    else:
        since_str = since_str or "7d"
        cutoff = datetime.now(UTC) - _parse_duration(since_str)
        scan_cap = 15  # practical limit per host; active large sessions can be slow to parse
        label = since_str

    all_rows: list[dict[str, Any]] = []

    if source == "store":
        store = _load_store(root)
        for hn in selected_hosts:
            for trace in store.list_traces(host=hn, since=cutoff, limit=scan_cap):
                all_rows.append(_build_session_row(trace, store, hn))
    else:
        click.echo(f"Scanning last {label} across {len(selected_hosts)} host(s)…", err=True)
        _sync_counts, store, tmp_handle = _scan_hosts_live(
            selected_hosts=selected_hosts,
            force=False,
            path=data_path,
            max_per_host=scan_cap,
            limit=scan_cap,
            cutoff=cutoff,
        )
        try:
            for hn in selected_hosts:
                for trace in store.list_traces(host=hn, since=cutoff, limit=scan_cap):
                    all_rows.append(_build_session_row(trace, store, hn))
        finally:
            tmp_handle.cleanup()

    all_rows = [r for r in all_rows if int(r["tool_calls"]) > 0 or int(r["input_tokens"]) > 0]

    if not all_rows:
        click.echo(f"No sessions found in the last {label}.")
        return

    _print_stats(all_rows, label, top)


__all__ = ["outcomes_group", "runs_group", "session_group"]
