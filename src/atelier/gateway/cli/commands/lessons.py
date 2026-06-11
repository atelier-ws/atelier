from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from atelier.core.foundation.models import to_jsonable
from atelier.gateway.cli.commands._shared import _emit, _ledger_dir, _ledger_path, _load_store


def _failure_state_path(root: Path) -> Path:
    return Path(root) / "failure_clusters.json"


def _load_failure_state(root: Path) -> dict[str, dict[str, Any]]:
    path = _failure_state_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_failure_state(root: Path, state: dict[str, dict[str, Any]]) -> None:
    path = _failure_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _lesson_promoter(root: Path) -> Any:
    from atelier.core.capabilities.lesson_promotion import LessonPromoterCapability

    store = _load_store(root)
    return LessonPromoterCapability(store)


def _lesson_pr_bot(root: Path) -> Any:
    from atelier.core.capabilities.lesson_promotion import LessonPrBot

    store = _load_store(root)
    return LessonPrBot(store=store, root=root)


def _emit_lesson_inbox(ctx: click.Context, domain: str | None, limit: int, as_json: bool) -> None:
    lessons = _lesson_promoter(ctx.obj["root"]).inbox(domain=domain, limit=limit)
    if as_json:
        _emit([item.model_dump(mode="json") for item in lessons], as_json=True)
        return
    if not lessons:
        click.echo("(no inbox lessons)")
        return
    for item in lessons:
        click.echo(f"{item.id}\t{item.domain}\t{item.kind}\t{item.confidence:.2f}\t{item.cluster_fingerprint[:48]}")


def _eval_dir(root: Path) -> Path:
    return Path(root) / "evals"


def _load_eval(root: Path, case_id: str) -> dict[str, Any] | None:
    p = _eval_dir(root) / f"{case_id}.json"
    if not p.exists():
        return None
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return data


def _save_eval(root: Path, case: dict[str, Any]) -> Path:
    d = _eval_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{case['id']}.json"
    p.write_text(json.dumps(case, indent=2), encoding="utf-8")
    return p


def _evaluate_eval_case(case: dict[str, Any]) -> dict[str, Any]:
    expected_status = str(case.get("expected_status", "pass"))
    actual_status = str(case.get("actual_status", expected_status))
    return {
        "case_id": str(case.get("id", "unknown")),
        "domain": str(case.get("domain", "unknown")),
        "description": str(case.get("description", "")),
        "expected_status": expected_status,
        "actual_status": actual_status,
        "passed": actual_status == expected_status,
    }


def _action_for_cluster(cluster: Any) -> dict[str, Any]:
    fingerprint = str(cluster.fingerprint or "")
    trace_count = len(cluster.trace_ids)
    priority = (
        "high" if trace_count >= 5 or str(cluster.severity) == "high" else "medium" if trace_count >= 2 else "low"
    )
    verification = "reproduce one source trace and confirm failure no longer occurs"
    suggested_fix = "add preconditions and explicit error handling for this failure class"

    if fingerprint.startswith("command_exit:"):
        parts = fingerprint.split(":")
        command = parts[1] if len(parts) > 1 else "unknown"
        suggested_fix = (
            f"stabilize command `{command}` path: validate preconditions, capture stderr, " "and prevent blind retries"
        )
        verification = f"run `{command}` path under same preconditions and verify non-zero exits are eliminated"
    elif fingerprint.startswith("tool_failure:"):
        tool_name = fingerprint.split(":", 2)[1] if ":" in fingerprint else "unknown_tool"
        suggested_fix = f"add resilient error handling and retries for tool `{tool_name}` with clear failure surfacing"
        verification = f"exercise `{tool_name}` on prior failing inputs and verify no tool failure signal is emitted"
    elif fingerprint.startswith("validation_failed:"):
        check_name = fingerprint.split(":", 2)[1] if ":" in fingerprint else "validation"
        suggested_fix = f"fix root cause behind failing validation `{check_name}` before merge"
        verification = f"run validation `{check_name}` and confirm pass"

    return {
        "id": f"action_from_{cluster.id}",
        "cluster_id": cluster.id,
        "fingerprint": fingerprint,
        "domain": cluster.domain,
        "severity": cluster.severity,
        "priority": priority,
        "trace_count": trace_count,
        "source_trace_ids": list(cluster.trace_ids),
        "why": f"recurs {trace_count} time(s): {fingerprint}",
        "suggested_fix": suggested_fix,
        "verification_command": verification,
    }


@click.group()
def ledger() -> None:
    """Manage run ledgers."""


@ledger.command("show")
@click.option("--session-id", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def ledger_show(ctx: click.Context, session_id: str | None, as_json: bool) -> None:
    path = _ledger_path(ctx.obj["root"], session_id)
    snap = json.loads(path.read_text(encoding="utf-8"))
    if as_json:
        _emit(snap, as_json=True)
        return
    click.echo(f"session_id: {snap.get('session_id')}")
    click.echo(f"status: {snap.get('status')}")
    click.echo(f"task: {snap.get('task', '')}")
    click.echo(f"domain: {snap.get('domain', '')}")
    click.echo(f"events: {len(snap.get('events', []))}")
    click.echo(f"errors_seen: {len(snap.get('errors_seen', []))}")
    click.echo(f"current_blockers: {snap.get('current_blockers', [])}")


@ledger.command("reset")
@click.option("--session-id", default=None)
@click.confirmation_option(prompt="Delete this ledger snapshot?")
@click.pass_context
def ledger_reset(ctx: click.Context, session_id: str | None) -> None:
    path = _ledger_path(ctx.obj["root"], session_id)
    path.unlink(missing_ok=True)
    click.echo(f"removed {path}")


@ledger.command("update")
@click.option("--session-id", default=None)
@click.option("--field", "field_name", required=True)
@click.option("--value", required=True, help="Value (use JSON literal for lists/dicts).")
@click.pass_context
def ledger_update(ctx: click.Context, session_id: str | None, field_name: str, value: str) -> None:
    path = _ledger_path(ctx.obj["root"], session_id)
    snap = json.loads(path.read_text(encoding="utf-8"))
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        parsed = value
    snap[field_name] = parsed
    path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    click.echo(f"updated {field_name}")


@ledger.command("summarize")
@click.option("--session-id", default=None)
@click.pass_context
def ledger_summarize(ctx: click.Context, session_id: str | None) -> None:
    from atelier.infra.runtime.context_compressor import ContextCompressor
    from atelier.infra.runtime.run_ledger import RunLedger

    path = _ledger_path(ctx.obj["root"], session_id)
    led = RunLedger.load(path)
    state = ContextCompressor().compress(led)
    click.echo(state.to_prompt_block())


@click.group()
def checkpoint() -> None:
    """Manage idempotent agent checkpoints for resumable execution."""


@checkpoint.command("create")
@click.option("--session-id", default=None, help="Session ID (defaults to latest ledger).")
@click.option("--tool", "tool_name", default="manual", show_default=True)
@click.option("--model-route", default="cheap_llm", show_default=True)
@click.option("--note", default="", help="Optional note stored as compact_state.")
@click.pass_context
def checkpoint_create(
    ctx: click.Context,
    session_id: str | None,
    tool_name: str,
    model_route: str,
    note: str,
) -> None:
    """Create a checkpoint at the current ledger step."""
    from atelier.infra.runtime.checkpoint import Checkpoint, CheckpointStore
    from atelier.infra.runtime.run_ledger import RunLedger

    root = ctx.obj["root"]
    path = _ledger_path(root, session_id)
    led = RunLedger.load(path)
    store = CheckpointStore(root)
    step_id = len(store.list_checkpoints(led.session_id))
    ckpt = Checkpoint.create(
        session_id=led.session_id,
        step_id=step_id,
        tool_name=tool_name,
        model_route=model_route,
        input_data=note,
        output_data=led.status,
        compact_state=note,
        cost_so_far_usd=led.cost_tracker.snapshot().get("total_cost_usd", 0.0) if led.cost_tracker else 0.0,
    )
    saved_path = store.save(ckpt)
    click.echo(f"checkpoint created: session={ckpt.session_id} step={ckpt.step_id} txn={ckpt.transaction_id}")
    click.echo(f"  saved to: {saved_path}")


@checkpoint.command("list")
@click.option("--session-id", default=None, help="Filter to a specific session.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def checkpoint_list(ctx: click.Context, session_id: str | None, as_json: bool) -> None:
    """List available checkpoints."""
    from atelier.infra.runtime.checkpoint import CheckpointStore

    root = ctx.obj["root"]
    store = CheckpointStore(root)
    sessions = [session_id] if session_id else store.list_sessions()
    if not sessions:
        click.echo("no checkpoints found.")
        return
    rows = []
    for sid in sessions:
        for ckpt in store.list_checkpoints(sid):
            rows.append(ckpt.to_dict())
    if as_json:
        _emit(rows, as_json=True)
        return
    for row in rows:
        click.echo(
            f"  {row['session_id'][:12]}  step={row['step_id']:3d}"
            f"  tool={row['tool_name']:<18s}  route={row['model_route']:<14s}"
            f"  cost=${row['cost_so_far_usd']:.4f}  txn={row['transaction_id']}"
        )


@checkpoint.command("resume")
@click.argument("session_id")
@click.option(
    "--from-step",
    "from_step",
    type=int,
    default=None,
    help="Resume from this step (default: last).",
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def checkpoint_resume(
    ctx: click.Context,
    session_id: str,
    from_step: int | None,
    as_json: bool,
) -> None:
    """Resume execution context from a saved checkpoint.

    Prints the compact_state from the checkpoint so the agent can restore
    context and continue from step N instead of restarting the full loop.
    """
    from atelier.infra.runtime.checkpoint import CheckpointStore

    root = ctx.obj["root"]
    store = CheckpointStore(root)

    if from_step is not None:
        ckpt = store.load(session_id, from_step)
        if ckpt is None:
            raise click.ClickException(f"no checkpoint found for session={session_id} step={from_step}")
    else:
        ckpt = store.latest_checkpoint(session_id)
        if ckpt is None:
            raise click.ClickException(f"no checkpoints found for session={session_id}")

    if as_json:
        _emit(ckpt.to_dict(), as_json=True)
        return

    click.echo(f"resuming from: session={ckpt.session_id}  step={ckpt.step_id}  txn={ckpt.transaction_id}")
    click.echo(f"  tool_name:    {ckpt.tool_name}")
    click.echo(f"  model_route:  {ckpt.model_route}")
    click.echo(f"  cost_so_far:  ${ckpt.cost_so_far_usd:.4f}")
    click.echo(f"  input_hash:   {ckpt.input_hash}")
    click.echo(f"  output_hash:  {ckpt.output_hash}")
    if ckpt.compact_state:
        click.echo("\ncompact_state:")
        click.echo(ckpt.compact_state)


@checkpoint.command("delete")
@click.argument("session_id")
@click.confirmation_option(prompt="Delete all checkpoints for this session?")
@click.pass_context
def checkpoint_delete(ctx: click.Context, session_id: str) -> None:
    """Delete all checkpoints for a session."""
    from atelier.infra.runtime.checkpoint import CheckpointStore

    root = ctx.obj["root"]
    store = CheckpointStore(root)
    count = store.delete_session(session_id)
    click.echo(f"deleted {count} checkpoint(s) for session={session_id}")


@click.group()
def failure() -> None:
    """Failure cluster management."""


@failure.command("list")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def failure_list(ctx: click.Context, as_json: bool) -> None:
    from atelier.core.improvement.failure_analyzer import FailureAnalyzer

    runs = _ledger_dir(ctx.obj["root"])
    clusters = FailureAnalyzer(runs).analyze()
    state = _load_failure_state(ctx.obj["root"])
    if as_json:
        _emit(
            [{**to_jsonable(c), "status": state.get(c.id, {}).get("status", "open")} for c in clusters],
            as_json=True,
        )
        return
    if not clusters:
        click.echo("(no failure clusters)")
        return
    for c in clusters:
        st = state.get(c.id, {}).get("status", "open")
        click.echo(f"{c.id}\t{st}\t{c.severity}\t{c.domain}\t{c.fingerprint[:60]}")


@failure.command("show")
@click.argument("cluster_id")
@click.pass_context
def failure_show(ctx: click.Context, cluster_id: str) -> None:
    from atelier.core.improvement.failure_analyzer import FailureAnalyzer

    clusters = {c.id: c for c in FailureAnalyzer(_ledger_dir(ctx.obj["root"])).analyze()}
    if cluster_id not in clusters:
        raise click.ClickException(f"cluster not found: {cluster_id}")
    state = _load_failure_state(ctx.obj["root"])
    payload = to_jsonable(clusters[cluster_id])
    payload["status"] = state.get(cluster_id, {}).get("status", "open")
    _emit(payload, as_json=True)


@failure.command("accept")
@click.argument("cluster_id")
@click.pass_context
def failure_accept(ctx: click.Context, cluster_id: str) -> None:
    state = _load_failure_state(ctx.obj["root"])
    state.setdefault(cluster_id, {})["status"] = "accepted"
    _save_failure_state(ctx.obj["root"], state)
    click.echo(f"accepted {cluster_id}")


@failure.command("reject")
@click.argument("cluster_id")
@click.pass_context
def failure_reject(ctx: click.Context, cluster_id: str) -> None:
    state = _load_failure_state(ctx.obj["root"])
    state.setdefault(cluster_id, {})["status"] = "rejected"
    _save_failure_state(ctx.obj["root"], state)
    click.echo(f"rejected {cluster_id}")


@click.group()
def lesson() -> None:
    """Lesson candidate review workflow."""


@lesson.command("list")
@click.option("--domain", default=None)
@click.option("--limit", default=25, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_list(ctx: click.Context, domain: str | None, limit: int, as_json: bool) -> None:
    _emit_lesson_inbox(ctx, domain, limit, as_json)


@lesson.command("inbox")
@click.option("--domain", default=None)
@click.option("--limit", default=25, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_inbox(ctx: click.Context, domain: str | None, limit: int, as_json: bool) -> None:
    """List lesson candidates currently waiting in the inbox."""
    _emit_lesson_inbox(ctx, domain, limit, as_json)


@lesson.command("approve")
@click.argument("lesson_id")
@click.option("--reviewer", required=True)
@click.option("--reason", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_approve(
    ctx: click.Context,
    lesson_id: str,
    reviewer: str,
    reason: str,
    as_json: bool,
) -> None:
    payload = _lesson_promoter(ctx.obj["root"]).decide(
        lesson_id=lesson_id,
        decision="approve",
        reviewer=reviewer,
        reason=reason,
    )
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo(f"approved {lesson_id}")


@lesson.command("reject")
@click.argument("lesson_id")
@click.option("--reviewer", required=True)
@click.option("--reason", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_reject(
    ctx: click.Context,
    lesson_id: str,
    reviewer: str,
    reason: str,
    as_json: bool,
) -> None:
    payload = _lesson_promoter(ctx.obj["root"]).decide(
        lesson_id=lesson_id,
        decision="reject",
        reviewer=reviewer,
        reason=reason,
    )
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo(f"rejected {lesson_id}")


@lesson.command("decide")
@click.argument("lesson_id")
@click.argument("decision", type=click.Choice(["approve", "reject"]))
@click.option("--reviewer", required=True)
@click.option("--reason", required=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_decide(
    ctx: click.Context,
    lesson_id: str,
    decision: str,
    reviewer: str,
    reason: str,
    as_json: bool,
) -> None:
    """Approve or reject a lesson candidate."""
    payload = _lesson_promoter(ctx.obj["root"]).decide(
        lesson_id=lesson_id,
        decision=decision,
        reviewer=reviewer,
        reason=reason,
    )
    if as_json:
        _emit(payload, as_json=True)
        return
    verb = "approved" if decision == "approve" else "rejected"
    click.echo(f"{verb} {lesson_id}")


@lesson.group("active")
def lesson_active_group() -> None:
    """Inspect and manage active typed lessons."""


@lesson_active_group.command("list")
@click.option("--include-inactive", is_flag=True, default=False)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_active_list(ctx: click.Context, include_inactive: bool, as_json: bool) -> None:
    from atelier.core.capabilities.lesson_promotion.store import TypedLessonStore

    lessons = TypedLessonStore(ctx.obj["root"], create=False).list_lessons()
    if not include_inactive:
        lessons = [lesson for lesson in lessons if lesson.enabled]
    if as_json:
        _emit([lesson.model_dump(mode="json") for lesson in lessons], as_json=True)
        return
    if not lessons:
        click.echo("(no active lessons)")
        return
    for lesson in lessons:
        last_applied = lesson.last_applied_at.isoformat() if lesson.last_applied_at else "-"
        click.echo(
            f"{lesson.id}\t{lesson.kind}\t{lesson.scope}\t{lesson.effective_confidence_at():.2f}\t"
            f"{'enabled' if lesson.enabled else 'disabled'}\t{last_applied}"
        )


@lesson_active_group.command("show")
@click.argument("lesson_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_active_show(ctx: click.Context, lesson_id: str, as_json: bool) -> None:
    from atelier.core.capabilities.lesson_promotion.store import TypedLessonStore

    lesson = TypedLessonStore(ctx.obj["root"], create=False).get_lesson(lesson_id)
    if lesson is None:
        raise click.ClickException(f"typed lesson not found: {lesson_id}")
    if as_json:
        _emit(lesson.model_dump(mode="json"), as_json=True)
        return
    click.echo(json.dumps(lesson.model_dump(mode="json"), indent=2, ensure_ascii=False, default=str))


@lesson_active_group.command("disable")
@click.argument("lesson_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_active_disable(ctx: click.Context, lesson_id: str, as_json: bool) -> None:
    from atelier.core.capabilities.lesson_promotion.store import TypedLessonStore

    lesson = TypedLessonStore(ctx.obj["root"]).set_enabled(lesson_id, False)
    if as_json:
        _emit(lesson.model_dump(mode="json"), as_json=True)
        return
    click.echo(f"disabled {lesson_id}")


@lesson_active_group.command("enable")
@click.argument("lesson_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_active_enable(ctx: click.Context, lesson_id: str, as_json: bool) -> None:
    from atelier.core.capabilities.lesson_promotion.store import TypedLessonStore

    lesson = TypedLessonStore(ctx.obj["root"]).set_enabled(lesson_id, True)
    if as_json:
        _emit(lesson.model_dump(mode="json"), as_json=True)
        return
    click.echo(f"enabled {lesson_id}")


@lesson.command("sync-pr")
@click.argument("lesson_id")
@click.option("--dry-run", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def lesson_sync_pr(ctx: click.Context, lesson_id: str, dry_run: bool, as_json: bool) -> None:
    payload = _lesson_pr_bot(ctx.obj["root"]).sync_pr(lesson_id=lesson_id, dry_run=dry_run)
    if as_json:
        _emit(payload, as_json=True)
        return
    if payload.get("skipped"):
        click.echo(f"skipped: {payload.get('reason', 'unknown')}")
        return
    if dry_run:
        click.echo(payload.get("diff", ""))
        return
    click.echo(f"created {payload.get('pr_url', '').strip()}")


@click.command("analyze-failures")
@click.option("--since", default=None, help="ISO timestamp or shorthand like '7d' (filter by mtime).")
@click.option("--trace", "trace_id", default=None, help="Single ledger run id to analyze.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def analyze_failures_cmd(ctx: click.Context, since: str | None, trace_id: str | None, as_json: bool) -> None:
    from atelier.core.improvement.failure_analyzer import FailureAnalyzer, analyze_failures

    runs = _ledger_dir(ctx.obj["root"])
    fa = FailureAnalyzer(runs)
    snaps = fa.load_snapshots()

    if trace_id:
        snaps = [s for s in snaps if s.get("session_id") == trace_id]

    if since:
        from datetime import UTC, datetime, timedelta

        cutoff: datetime | None = None
        if since.endswith("d") and since[:-1].isdigit():
            cutoff = datetime.now(UTC) - timedelta(days=int(since[:-1]))
        else:
            try:
                cutoff = datetime.fromisoformat(since)
            except ValueError:
                cutoff = None
        if cutoff is not None:
            kept = []
            for s in snaps:
                ts = s.get("updated_at") or s.get("created_at")
                if not ts:
                    continue
                try:
                    if datetime.fromisoformat(ts) >= cutoff:
                        kept.append(s)
                except ValueError:
                    continue
            snaps = kept

    clusters = analyze_failures(snaps)
    session_id = ctx.obj.get("_telemetry_session_id") if isinstance(ctx.obj, dict) else None
    if isinstance(session_id, str):
        from atelier.core.service.telemetry import emit_product
        from atelier.core.service.telemetry.schema import hash_identifier

        for cluster in clusters:
            emit_product(
                "failure_cluster_matched",
                cluster_id_hash=hash_identifier(cluster.id),
                domain=cluster.domain,
                session_id=session_id,
            )
    if as_json:
        _emit([to_jsonable(c) for c in clusters], as_json=True)
        return
    for c in clusters:
        click.echo(f"{c.id}\t{c.severity}\t{c.domain}\t{c.fingerprint[:60]}")


@click.group(name="eval")
def eval_() -> None:
    """Evaluation case management."""


eval_.name = "eval"


@eval_.group("cycle")
def eval_cycle_group() -> None:
    """Unified failure->case->run workflow namespace."""


@eval_.command("list", hidden=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def eval_list(ctx: click.Context, as_json: bool) -> None:
    d = _eval_dir(ctx.obj["root"])
    cases = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            cases.append(json.loads(p.read_text(encoding="utf-8")))
    if as_json:
        _emit(cases, as_json=True)
        return
    for c in cases:
        click.echo(f"{c.get('id')}\t{c.get('status', 'draft')}\t{c.get('domain', '')}\t{c.get('description', '')[:60]}")


@eval_.command("show", hidden=True)
@click.argument("case_id")
@click.pass_context
def eval_show(ctx: click.Context, case_id: str) -> None:
    case = _load_eval(ctx.obj["root"], case_id)
    if case is None:
        raise click.ClickException(f"eval case not found: {case_id}")
    _emit(case, as_json=True)


@eval_.command("promote", hidden=True)
@click.argument("case_id")
@click.pass_context
def eval_promote(ctx: click.Context, case_id: str) -> None:
    case = _load_eval(ctx.obj["root"], case_id)
    if case is None:
        raise click.ClickException(f"eval case not found: {case_id}")
    case["status"] = "active"
    _save_eval(ctx.obj["root"], case)
    click.echo(f"promoted {case_id}")


@eval_.command("deprecate", hidden=True)
@click.argument("case_id")
@click.pass_context
def eval_deprecate(ctx: click.Context, case_id: str) -> None:
    case = _load_eval(ctx.obj["root"], case_id)
    if case is None:
        raise click.ClickException(f"eval case not found: {case_id}")
    case["status"] = "deprecated"
    _save_eval(ctx.obj["root"], case)
    click.echo(f"deprecated {case_id}")


@eval_.command("run", hidden=True)
@click.option("--domain", default=None)
@click.option("--case", "case_id", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def eval_run(ctx: click.Context, domain: str | None, case_id: str | None, as_json: bool) -> None:
    """Run deterministic eval cases (legacy alias: use `eval cycle run`)."""
    d = _eval_dir(ctx.obj["root"])
    cases: list[dict[str, Any]] = []
    if case_id:
        c = _load_eval(ctx.obj["root"], case_id)
        if c is None:
            raise click.ClickException(f"eval case not found: {case_id}")
        cases = [c]
    elif d.is_dir():
        for p in sorted(d.glob("*.json")):
            cases.append(json.loads(p.read_text(encoding="utf-8")))
    if domain:
        cases = [c for c in cases if c.get("domain") == domain]
    results = [_evaluate_eval_case(case) for case in cases]

    if as_json:
        _emit(results, as_json=True)
    else:
        for result in results:
            click.echo(
                f"{result['case_id']}\t{result['domain']}\t{result['expected_status']}"
                f"\t{result['actual_status']}\t{'pass' if result['passed'] else 'fail'}"
            )


@eval_.command("mini")
@click.option("--dry-run", "dry_run", is_flag=True, help="Validate cases, print plan, no API calls.")
@click.option("--limit", default=5, show_default=True, type=int, help="Max cases to run.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON report to stdout.")
@click.option("--output", default=None, help="Path to write JSON report (default: .atelier/evals/mini-report.json)")
@click.option("--cases", "cases_path", default=None, help="Path to cases YAML (default: benchmarks/mini/cases.yaml)")
@click.pass_context
def eval_mini(
    ctx: click.Context,
    dry_run: bool,
    limit: int,
    as_json: bool,
    output: str | None,
    cases_path: str | None,
) -> None:
    """Run the Atelier mini eval suite (5-10 tasks, cost-quality proof).

    \b
    Usage:
      atelier eval mini --dry-run --json       # Offline validation, no API keys needed
      atelier eval mini --limit 5 --json        # Run 5 cases, write JSON report
    """
    from atelier.core.capabilities.eval_mini import (
        load_cases,
        render_markdown,
        repo_root,
        run_suite,
        save_report,
    )

    root: Path = ctx.obj["root"]
    git_repo = repo_root()

    try:
        cases = load_cases(cases_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    report = run_suite(cases, root=root, git_repo=git_repo, dry_run=dry_run, limit=limit)

    if output:
        json_path = Path(output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        md_path = json_path.with_suffix(".md")
        md_path.write_text(render_markdown(report), encoding="utf-8")
    else:
        json_path, _md_path = save_report(report, Path(root) / "evals")

    if as_json:
        _emit(report.model_dump(mode="json"), as_json=True)
        return

    status_str = {"pass": "PASS", "fail": "FAIL", "dry_run": "DRY RUN"}.get(report.status, report.status)
    click.echo(f"eval mini status={status_str} suite={report.suite}")
    click.echo(f"tasks={report.total_tasks} accepted={report.accepted_tasks} failed={report.failed_tasks}")
    click.echo(f"accepted_patch_rate={report.accepted_patch_rate:.2f}")
    click.echo(f"total_cost_usd=${report.total_cost_usd:.4f}")
    click.echo(f"cost_per_accepted_patch=${report.cost_per_accepted_patch:.4f}")
    click.echo(f"cheap_success_rate={report.cheap_success_rate:.2f}")
    click.echo(f"trace_coverage_pct={report.trace_coverage_pct:.0f}%")
    click.echo(f"routing_regression_rate={report.routing_regression_rate:.4f}")
    click.echo(f"report: {json_path}")


@eval_.command("harbor")
@click.option(
    "--dataset",
    "-d",
    default="terminal-bench/terminal-bench-2",
    show_default=True,
    help="Harbor dataset to run against.",
)
@click.option("--limit", default=5, show_default=True, type=int, help="Max tasks to run.")
@click.option(
    "--agent",
    "agent_arm",
    default="atelier",
    type=click.Choice(["atelier", "atelier-bedrock"]),
    show_default=True,
    help="Agent arm: direct API or via Bedrock.",
)
@click.option("--model", default=None, help="Model to use inside the container.")
@click.option("--parallel", default=1, show_default=True, type=int, help="Number of parallel trials.")
@click.option("--output", default=None, help="Output directory for results.")
@click.pass_context
def eval_harbor(
    ctx: click.Context,
    dataset: str,
    limit: int,
    agent_arm: str,
    model: str | None,
    parallel: int,
    output: str | None,
) -> None:
    """Run Atelier on a Harbor benchmark dataset.

    \b
    Requires: pip install harbor  (or: uv add harbor in benchmarks/)
    Requires: Docker (for container execution)

    \b
    Examples:
      atelier eval harbor --limit 5
      atelier eval harbor --agent atelier-bedrock --limit 10
      atelier eval harbor -d "terminal-bench/terminal-bench-core@0.1.1" --limit 3

    \b
    To run A/B comparison, run with --agent atelier and then --agent atelier-baseline.
    """
    try:
        import harbor  # noqa: F401
    except ImportError as exc:
        raise click.ClickException(
            "harbor package not found.\n"
            "Install it with:\n"
            "  pip install harbor\n"
            "or add it to your benchmarks project:\n"
            "  uv add harbor --project benchmarks"
        ) from exc

    # Resolve the agent import path from the agent arm
    _agent_import_paths = {
        "atelier": "benchmarks.harbor.atelier_agent:AtelierHarborAgent",
        "atelier-bedrock": "benchmarks.harbor.atelier_agent:AtelierBedrockHarborAgent",
    }
    agent_import_path = _agent_import_paths[agent_arm]

    out_dir = output or str(ctx.obj.get("root", ".") / "evals" / "harbor")

    # Load the pre-registered task list to select the first N
    import shutil
    import subprocess
    from pathlib import Path as _Path

    tasks_yaml = _Path(__file__).parents[5] / "benchmarks" / "terminalbench" / "tasks.yaml"
    selected_tasks: list[str] = []
    if tasks_yaml.exists():
        import yaml as _yaml  # type: ignore[import-untyped]

        raw = _yaml.safe_load(tasks_yaml.read_text()) or {}
        all_tasks: list[str] = raw.get("tasks", [])
        selected_tasks = all_tasks[:limit]

    click.echo(f"◆ Running Harbor eval: dataset={dataset}")
    click.echo(
        f"  agent={agent_arm}  model={model or 'default'}  tasks={len(selected_tasks) or limit}  parallel={parallel}"
    )
    click.echo(f"  output={out_dir}")
    if selected_tasks:
        click.echo(f"  tasks: {', '.join(selected_tasks)}")
    click.echo("")

    harbor_bin = shutil.which("harbor")
    if harbor_bin is None:
        raise click.ClickException(
            "harbor CLI not found on PATH.\n"
            "Install it: pip install harbor\n"
            "Make sure the harbor binary is on your PATH after install."
        )

    base_cmd = [
        harbor_bin,
        "run",
        "--dataset",
        dataset,
        "--agent-import-path",
        agent_import_path,
        "--jobs-dir",
        out_dir,
    ]
    if model:
        base_cmd += ["--model", model]
    if parallel > 1:
        base_cmd += ["--n-concurrent", str(parallel)]

    if selected_tasks:
        # Run each selected task individually (-t task_id per invocation)
        failed = 0
        for task_id in selected_tasks:
            cmd = [*base_cmd, "--task", task_id]
            click.echo(f"  → {task_id}")
            ret = subprocess.call(cmd)
            if ret != 0:
                click.echo(f"  ✗ {task_id} failed (exit {ret})", err=True)
                failed += 1
        if failed:
            raise click.ClickException(f"{failed}/{len(selected_tasks)} tasks failed")
    else:
        # No pre-registered task list; run full dataset
        cmd = [*base_cmd, "--n-concurrent", str(parallel or 1)]
        click.echo(f"  Command: {' '.join(cmd)}\n")
        ret = subprocess.call(cmd)
        if ret != 0:
            raise click.ClickException(f"harbor run exited with code {ret}")

    click.echo(f"\n✓ Harbor eval complete. Results in: {out_dir}")


@eval_cycle_group.command("run")
@click.option("--limit", type=int, default=25, show_default=True, help="Maximum clusters/cases to process.")
@click.option(
    "--run/--no-run", "do_run", default=True, show_default=True, help="Run deterministic eval checks after generation."
)
@click.option(
    "--accept-open/--only-accepted",
    default=True,
    show_default=True,
    help="Auto-accept open clusters before generating cases.",
)
@click.option("--domain", default=None, help="Run mode: filter existing eval cases by domain.")
@click.option("--case", "case_id", default=None, help="Run mode: execute one existing eval case id.")
@click.option("--provenance-output", default=None, help="Path to write case provenance JSON report.")
@click.option("--explain-output", default=None, help="Path to write human-readable explain report.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON summary.")
@click.pass_context
def eval_cycle_run(
    ctx: click.Context,
    limit: int,
    do_run: bool,
    accept_open: bool,
    domain: str | None,
    case_id: str | None,
    provenance_output: str | None,
    explain_output: str | None,
    as_json: bool,
) -> None:
    """One-command failure->case->run loop.

    Reads real session run ledgers, clusters failures, generates/updates eval cases,
    optionally runs deterministic checks, and prints a concise summary.
    """
    from atelier.core.improvement.failure_analyzer import FailureAnalyzer, analyze_failures

    root = ctx.obj["root"]
    if case_id or domain:
        ctx.invoke(eval_run, domain=domain, case_id=case_id, as_json=as_json)
        return

    store = _load_store(root)

    all_traces: list[Any] = []
    offset = 0
    page_size = 1000
    max_scan = 50000
    while offset < max_scan:
        page = store.list_traces(limit=page_size, offset=offset)
        if not page:
            break
        all_traces.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    snapshots: list[dict[str, Any]]
    source_mode = "trace_store"
    if all_traces:
        snapshots = [t.model_dump(mode="json") for t in all_traces]
    else:
        # Fallback for minimal/dev stores with run ledgers but no traces.
        analyzer = FailureAnalyzer(_ledger_dir(root))
        snapshots = analyzer.load_snapshots()
        source_mode = "runs_ledger_fallback"

    host_counts: Counter[str] = Counter()
    raw_command_signal_counts: Counter[str] = Counter()
    for snap in snapshots:
        host = str(snap.get("host") or "unknown")
        host_counts[host] += 1
        for cmd in snap.get("commands_run", []) or []:
            if isinstance(cmd, dict) and cmd.get("exit_code") not in (None, 0):
                command_text = str(cmd.get("command", "")).strip()
                raw = command_text.split()[0] if command_text else "unknown_command"
                raw_command_signal_counts[f"command_exit:{raw}:exit_{cmd.get('exit_code')}"] += 1
                break

    clusters = analyze_failures(snapshots)
    state = _load_failure_state(root)
    snapshot_index: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        sid = str(snap.get("session_id", "")).strip()
        if not sid:
            continue
        snapshot_index[sid] = {
            "session_id": sid,
            "agent": snap.get("agent"),
            "environment_id": snap.get("environment_id"),
            "status": snap.get("status"),
            "created_at": snap.get("created_at"),
            "updated_at": snap.get("updated_at"),
        }

    selected: list[Any] = []
    accepted_now = 0
    selected_cluster_details: list[dict[str, Any]] = []

    for c in clusters:
        st = state.get(c.id, {}).get("status", "open")
        if st == "rejected":
            continue
        original_status = st
        if st == "open" and accept_open:
            state.setdefault(c.id, {})["status"] = "accepted"
            st = "accepted"
            accepted_now += 1
        if st == "accepted":
            selected.append(c)
            selected_cluster_details.append(
                {
                    "cluster_id": c.id,
                    "status_before": original_status,
                    "status_after": st,
                    "fingerprint": c.fingerprint,
                    "trace_count": len(c.trace_ids),
                    "domain": c.domain,
                }
            )
        if len(selected) >= limit:
            break

    _save_failure_state(root, state)

    actions: list[dict[str, Any]] = [_action_for_cluster(c) for c in selected]
    actions_path = _eval_dir(root) / "cycle-actions.json"
    actions_path.parent.mkdir(parents=True, exist_ok=True)
    actions_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "root": str(root),
                "source_mode": source_mode,
                "actions": actions,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    generated_cases: list[dict[str, Any]] = []

    results: list[dict[str, Any]] = []
    if do_run:
        results = [_evaluate_eval_case(case) for case in generated_cases]

    clustered_session_ids: set[str] = set()
    for c in clusters:
        clustered_session_ids.update(str(sid) for sid in c.trace_ids if sid)

    eval_dir = _eval_dir(root)
    provenance_path = Path(provenance_output) if provenance_output else eval_dir / "cycle-provenance.json"
    explain_path = Path(explain_output) if explain_output else eval_dir / "cycle-explain.md"

    provenance_payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "sessions_read": len(snapshots),
        "clustered_sessions": len(clustered_session_ids),
        "cases_written": len(generated_cases),
        "cases": [
            {
                "case_id": case["id"],
                "source_cluster_id": case.get("source_cluster_id"),
                "source_trace_ids": list(case.get("source_trace_ids", [])),
                "source_sessions": [
                    snapshot_index[sid] for sid in case.get("source_trace_ids", []) if sid in snapshot_index
                ],
            }
            for case in generated_cases
        ],
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(provenance_payload, indent=2), encoding="utf-8")

    explain_lines = [
        "# Atelier eval cycle explain report",
        "",
        f"- generated_at: {provenance_payload['generated_at']}",
        f"- root: {root}",
        f"- ledger_dir: {_ledger_dir(root)}",
        f"- sessions_read: {len(snapshots)}",
        f"- clustered_sessions: {len(clustered_session_ids)}",
        f"- unclustered_sessions: {max(0, len(snapshots) - len(clustered_session_ids))}",
        f"- clusters_total: {len(clusters)}",
        f"- clusters_selected: {len(selected)}",
        f"- cases_written: {len(generated_cases)}",
        f"- ran_checks: {do_run}",
        "",
        "## Selected clusters",
    ]
    if selected_cluster_details:
        for item in selected_cluster_details:
            explain_lines.append(
                f"- {item['cluster_id']} ({item['domain']}): trace_count={item['trace_count']} fingerprint={item['fingerprint']}"
            )
    else:
        explain_lines.append("- (none)")
    explain_lines.extend(["", "## Cases written"])
    if generated_cases:
        for case in generated_cases:
            explain_lines.append(
                f"- {case['id']}: cluster={case.get('source_cluster_id')} traces={len(case.get('source_trace_ids', []))}"
            )
    else:
        explain_lines.append("- (none)")
    explain_path.parent.mkdir(parents=True, exist_ok=True)
    explain_path.write_text("\n".join(explain_lines) + "\n", encoding="utf-8")

    passed = sum(1 for r in results if r.get("passed")) if results else 0
    payload: dict[str, Any] = {
        "root": str(root),
        "source_mode": source_mode,
        "ledger_dir": str(_ledger_dir(root)),
        "failure_state_path": str(_failure_state_path(root)),
        "eval_dir": str(_eval_dir(root)),
        "sessions_read": len(snapshots),
        "host_counts": dict(sorted(host_counts.items())),
        "clustered_sessions": len(clustered_session_ids),
        "unclustered_sessions": max(0, len(snapshots) - len(clustered_session_ids)),
        "clusters_total": len(clusters),
        "top_raw_command_signals": [
            {"signal": signal, "count": count} for signal, count in raw_command_signal_counts.most_common(20)
        ],
        "top_cluster_candidates": [
            {
                "cluster_id": c.id,
                "fingerprint": c.fingerprint,
                "domain": c.domain,
                "trace_count": len(c.trace_ids),
                "severity": c.severity,
            }
            for c in clusters[:10]
        ],
        "clusters_selected": len(selected),
        "clusters_auto_accepted": accepted_now,
        "selected_clusters": selected_cluster_details,
        "actions_written": len(actions),
        "actions_path": str(actions_path),
        "cases_written": len(generated_cases),
        "provenance_path": str(provenance_path),
        "explain_path": str(explain_path),
        "ran": do_run,
        "results_total": len(results),
        "results_passed": passed,
        "results_failed": max(0, len(results) - passed),
        "case_ids": [c["id"] for c in generated_cases],
    }

    if as_json:
        _emit(payload, as_json=True)
        return

    click.echo(f"root: {payload['root']}")
    click.echo(f"source: {payload['source_mode']}")
    if payload["source_mode"] == "trace_store":
        click.echo(f"read: sessions={payload['sessions_read']} from trace store")
    else:
        click.echo(f"read: sessions={payload['sessions_read']} from {payload['ledger_dir']}")
    click.echo(f"hosts: {payload['host_counts']}")
    click.echo(f"clusterable: {payload['clustered_sessions']} (unclustered={payload['unclustered_sessions']})")
    click.echo(
        f"clusters: total={payload['clusters_total']} selected={payload['clusters_selected']} auto_accepted={payload['clusters_auto_accepted']}"
    )
    if payload["top_cluster_candidates"]:
        click.echo("top_signals:")
        for item in payload["top_cluster_candidates"][:5]:
            click.echo(f"- {item['trace_count']}x {item['fingerprint'][:120]}")
    if payload["top_raw_command_signals"]:
        click.echo("top_raw_signals:")
        for item in payload["top_raw_command_signals"][:5]:
            click.echo(f"- {item['count']}x {item['signal'][:120]}")
    click.echo(f"state: {payload['failure_state_path']}")
    click.echo(f"cases_dir: {payload['eval_dir']}")
    click.echo(f"actions: written={payload['actions_written']} path={payload['actions_path']}")
    click.echo(f"provenance: {payload['provenance_path']}")
    click.echo(f"explain: {payload['explain_path']}")
    click.echo(f"cases: written={payload['cases_written']}")
    if do_run:
        click.echo(f"run: passed={payload['results_passed']} failed={payload['results_failed']}")
    if payload["case_ids"]:
        click.echo("cases:")
        for cid in payload["case_ids"]:
            click.echo(f"- {cid}")


@eval_.command("from-cluster", hidden=True)
@click.argument("cluster_id")
@click.pass_context
def eval_from_cluster(ctx: click.Context, cluster_id: str) -> None:
    """Generate a draft eval from an accepted FailureCluster."""
    from atelier.core.improvement.failure_analyzer import FailureAnalyzer

    state = _load_failure_state(ctx.obj["root"])
    if state.get(cluster_id, {}).get("status") != "accepted":
        raise click.ClickException(f"cluster not accepted: {cluster_id}")
    clusters = {c.id: c for c in FailureAnalyzer(_ledger_dir(ctx.obj["root"])).analyze()}
    if cluster_id not in clusters:
        raise click.ClickException(f"cluster not found: {cluster_id}")
    c = clusters[cluster_id]
    case = {
        "id": f"eval_from_{cluster_id}",
        "domain": c.domain,
        "description": f"Replay of {c.fingerprint[:60]}",
        "task": f"Replay failure cluster {cluster_id}",
        "plan": [c.suggested_rubric_check or "no-op"],
        "expected_status": "blocked",
        "expected_warnings_contain": [],
        "expected_dead_ends": [],
        "status": "draft",
        "source_trace_ids": list(c.trace_ids),
    }
    p = _save_eval(ctx.obj["root"], case)
    click.echo(f"saved draft eval at {p}")


@eval_cycle_group.command("list")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def eval_cycle_list(ctx: click.Context, as_json: bool) -> None:
    """List eval cases."""
    ctx.invoke(eval_list, as_json=as_json)


@eval_cycle_group.command("show")
@click.argument("case_id")
@click.pass_context
def eval_cycle_show(ctx: click.Context, case_id: str) -> None:
    """Show one eval case."""
    ctx.invoke(eval_show, case_id=case_id)


@eval_cycle_group.command("promote")
@click.argument("case_id")
@click.pass_context
def eval_cycle_promote(ctx: click.Context, case_id: str) -> None:
    """Mark one eval case active."""
    ctx.invoke(eval_promote, case_id=case_id)


@eval_cycle_group.command("deprecate")
@click.argument("case_id")
@click.pass_context
def eval_cycle_deprecate(ctx: click.Context, case_id: str) -> None:
    """Mark one eval case deprecated."""
    ctx.invoke(eval_deprecate, case_id=case_id)


@eval_cycle_group.command("from-cluster")
@click.argument("cluster_id")
@click.pass_context
def eval_cycle_from_cluster(ctx: click.Context, cluster_id: str) -> None:
    """Generate one draft case from an accepted cluster."""
    ctx.invoke(eval_from_cluster, cluster_id=cluster_id)


# Remove legacy top-level eval case commands; cycle namespace is the supported UX.
for _legacy_eval_cmd in ("list", "show", "promote", "deprecate", "run", "from-cluster"):
    eval_.commands.pop(_legacy_eval_cmd, None)


failure.add_command(analyze_failures_cmd, name="analyze")


__all__ = [
    "_emit_lesson_inbox",
    "_eval_dir",
    "_evaluate_eval_case",
    "_ledger_dir",
    "_ledger_path",
    "_load_eval",
    "_load_failure_state",
    "_save_eval",
    "_save_failure_state",
    "analyze_failures_cmd",
    "checkpoint",
    "eval_",
    "eval_from_cluster",
    "failure",
    "ledger",
    "lesson",
]
