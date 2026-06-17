from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from atelier.gateway.cli.commands._shared import _emit, _ledger_dir, _ledger_path, _load_store


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


@click.group(name="eval")
def eval_() -> None:
    """Evaluation case management."""


eval_.name = "eval"


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
    type=click.Choice(["atelier", "atelier-bedrock", "atelier-claude-code"]),
    show_default=True,
    help="Agent arm: direct API, Bedrock, or Claude Code CLI + Atelier plugin.",
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
        "atelier-claude-code": "benchmarks.harbor.atelier_agent:AtelierClaudeCodeHarborAgent",
    }
    agent_import_path = _agent_import_paths[agent_arm]

    out_dir = output or str(ctx.obj.get("root", ".") / "evals" / "harbor")

    # Load the pre-registered task list to select the first N
    import shutil
    import subprocess
    from pathlib import Path as _Path

    tasks_yaml = _Path(__file__).parents[5] / "benchmarks" / "harbor" / "tasks.yaml"
    selected_tasks: list[str] = []
    # tasks.yaml is pinned for terminal-bench-core only; for other datasets
    # (TB2.0, TB2.1, etc.) use -l to let harbor pick the first N tasks.
    core_dataset = "terminal-bench-core" in dataset
    if tasks_yaml.exists() and core_dataset:
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

    # Ensure the repo root is on PYTHONPATH so harbor can import
    # benchmarks.harbor.atelier_agent regardless of working directory.
    import os as _os

    repo_root = str(_Path(__file__).parents[5])
    existing_pythonpath = _os.environ.get("PYTHONPATH", "")
    pythonpath = f"{repo_root}:{existing_pythonpath}" if existing_pythonpath else repo_root
    harbor_env = {**_os.environ, "PYTHONPATH": pythonpath}

    def _read_token_from_env_files(key: str) -> str:
        """Read a token from shell env or .env files in known locations."""
        val = _os.environ.get(key, "")
        if val:
            return val
        for env_file in (
            _Path(repo_root) / ".env",
            _Path(repo_root) / "benchmarks" / ".env",
            _Path(repo_root) / "benchmarks" / "codebench" / ".env",
        ):
            if not env_file.is_file():
                continue
            for line in env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip().lstrip("export ").strip()
                if stripped.startswith("#") or "=" not in stripped:
                    continue
                k, _, v = stripped.partition("=")
                if k.strip() == key:
                    return v.strip().strip("'\"")
        return ""

    import json as _json

    base_cmd = [
        harbor_bin,
        "run",
        "--dataset",
        dataset,
        "--agent-import-path",
        agent_import_path,
        "--jobs-dir",
        out_dir,
        # Mount the repo into the container so atelier can be installed from
        # source (it is not published to PyPI).
        "--mounts",
        _json.dumps([{"type": "bind", "source": repo_root, "target": "/atelier"}]),
        # Collect the claude CLI output log for debugging.
        "--artifact",
        "/logs/claude-run.json",
    ]
    if model:
        base_cmd += ["--model", model]
    if parallel > 1:
        base_cmd += ["--n-concurrent", str(parallel)]
    # Forward CLAUDE_CODE_OAUTH_TOKEN for the claude-code arm
    if agent_arm == "atelier-claude-code":
        token = _read_token_from_env_files("CLAUDE_CODE_OAUTH_TOKEN")
        if token:
            base_cmd += ["--ae", f"CLAUDE_CODE_OAUTH_TOKEN={token}"]
        else:
            click.echo(
                "WARNING: CLAUDE_CODE_OAUTH_TOKEN not set. " "Set it in your shell or in benchmarks/codebench/.env.",
                err=True,
            )

    if selected_tasks:
        # terminal-bench-core: use -i filters (task names match exactly)
        cmd = [*base_cmd]
        for task_id in selected_tasks:
            cmd += ["--include-task-name", task_id]
    else:
        # All other datasets: use -l to cap tasks, let harbor pick the first N
        cmd = [*base_cmd, "--n-tasks", str(limit)]
    click.echo(f"  Command: {' '.join(cmd)}\n")
    ret = subprocess.call(cmd, env=harbor_env)
    if ret != 0:
        raise click.ClickException(f"harbor run exited with code {ret}")

    click.echo(f"\n✓ Harbor eval complete. Results in: {out_dir}")


__all__ = [
    "_emit_lesson_inbox",
    "_ledger_dir",
    "_ledger_path",
    "checkpoint",
    "eval_",
    "ledger",
    "lesson",
]
