"""Thin savings / external-report / optimize command surfaces (QBL-CLI-02).

This module hosts the ``savings``, ``savings-detail``, ``savings-reset``,
``external-status``, ``external-report`` commands and the ``optimize`` group
(with its ``shadow`` subgroup). Pure rendering lives in
``core.capabilities.reporting.dashboard``; these callbacks keep their original
Click wiring, option defaults, and output formatting verbatim. The data-fetch
helpers (``_advisor_result`` etc.) are command-layer glue that load the store
via ``ctx`` and stay module-private here.

Commands are defined as standalone Click objects (Pattern 1) so
``commands/__init__.py`` can ``add_command`` them onto the root ``cli`` group.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from shutil import which
from typing import Any

import click

from atelier.gateway.cli.commands._shared import (
    _emit,
    _ledger_dir,
    _load_smart_state,
    _load_store,
    _save_smart_state,
)
from atelier.gateway.hosts.session_parsers.registry import SUPPORTED_SESSION_IMPORT_HOSTS
from atelier.gateway.integrations.external_analytics import REPORTABLE_TOOL_IDS

logger = logging.getLogger(__name__)

# `--tool` choices for the external-report CLI. Built once from the source-of-
# truth `SPECS` tuple plus the special-case `codeburn:optimize` sub-report and
# the `all` aggregator. Adding a new analyzer to external_analytics.SPECS now
# flows here automatically - no second hardcoded list to keep in sync.
_EXTERNAL_REPORT_TOOL_CHOICES = ("all", *REPORTABLE_TOOL_IDS, "codeburn:optimize")
# Order matters for the human-readable `all` iteration: keep it focused on the
# core report trio and leave newer analyzers available via explicit --tool.
_EXTERNAL_REPORT_ALL_TOOLS = (
    *(t for t in REPORTABLE_TOOL_IDS if t in {"tokscale", "codeburn"}),
    "codeburn:optimize",
)


def _echo_vs_vanilla_block(root: str | Path, *, deep: bool = False) -> None:
    """Render the comparative \"vs vanilla Claude Code\" replay block.

    Sourced from aggregate_vanilla_baseline (lifetime window + cap). This is an
    estimate of roundtrips vanilla CC would have spent that Atelier avoided,
    priced at full-context resend — clearly labelled and kept separate from the
    measured savings figures above.
    """
    try:
        from atelier.core.capabilities.vanilla_baseline import aggregate_vanilla_baseline

        vs = aggregate_vanilla_baseline(root)
    except Exception as e:
        logger.debug("Failed to aggregate vanilla baseline: %s", e)
        return
    calls = int(vs.get("calls_saved", 0) or 0)
    if calls <= 0:
        return
    usd = float(vs.get("cost_saved_usd", 0.0) or 0.0)
    seconds = int((vs.get("time_saved_ms", 0) or 0) / 1000)
    click.echo("")
    click.echo(f"vs vanilla Claude Code: {calls} roundtrips avoided · ${usd:.2f} · ~{seconds}s faster (estimate)")
    if deep:
        by_detector = vs.get("by_detector") or {}
        if by_detector:
            click.echo("  by pattern (roundtrips avoided):")
            for label, hits in sorted(by_detector.items(), key=lambda kv: kv[1], reverse=True):
                click.echo(f"    {label}: {hits}")
        click.echo(
            f"  window: {int(vs.get('window_days', 0) or 0)}d · {int(vs.get('sessions', 0) or 0)} sessions"
            + ("  (lifetime cap hit)" if vs.get("capped") else "")
        )


def _render_savings_rich(payload: dict[str, Any], deep: bool = False) -> None:
    """Polished Rich table for savings breakdown (1D, 7D, 30D)."""
    from rich import box as rbox
    from rich.console import Console
    from rich.table import Table

    console = Console(highlight=False)
    breakdown = payload.get("summary_breakdown") or {}

    if breakdown:
        console.print()
        console.print("[bold bright_white]  Savings Breakdown[/]")
        console.print()

        table = Table(box=rbox.SIMPLE, show_header=True, header_style="dim cyan", padding=(0, 2))
        table.add_column("Window", style="bold")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Saved", justify="right", style="green")
        table.add_column("Spent", justify="right")

        for window in ["1D", "7D", "30D"]:
            w = breakdown.get(window, {})
            table.add_row(
                window,
                f"{w.get('calls', 0):,}",
                f"{_fmt_tok_compact(w.get('tokens', 0))}",
                f"${w.get('usd', 0.0):,.2f}",
                f"${w.get('spend', 0.0):,.2f}",
            )
        console.print(table)
        console.print()

    # High-level summary keys to show by default
    _DEFAULT_KEYS = {"subscription"}

    for k, v in payload.items():
        if k not in _DEFAULT_KEYS and not deep:
            continue
        if isinstance(v, dict):
            console.print(f"[bold]{k}:[/]")
            for k2, v2 in v.items():
                if isinstance(v2, dict) and not deep:
                    console.print(f"  [dim]{k2}: <dict, pass --deep for detail>[/]")
                elif isinstance(v2, list) and not deep:
                    console.print(f"  [dim]{k2}: <list of {len(v2)} items, pass --deep for detail>[/]")
                else:
                    console.print(f"  {k2}: {v2}")
        else:
            console.print(f"[bold]{k}:[/] {v}")

    if not deep:
        console.print()
        console.print(
            "[dim]Pass --deep to see AB calibration, optimization recommendations, and full session stats.[/]"
        )


def _fmt_tok_compact(n: int) -> str:
    """Format large token counts to K/M/B."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1_000_000_000:.1f}B"


@click.group("savings", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True)
@click.option("--line", is_flag=True, help="Pipe-delimited one-liner for statusline.sh (legacy).")
@click.option("--segment", is_flag=True, help="Pre-formatted rotating segment for statusline.sh.")
@click.option("--deep", is_flag=True, help="Add a per-pattern vs-vanilla breakdown (which workflows save most).")
@click.pass_context
def savings_cmd(ctx: click.Context, as_json: bool, line: bool, segment: bool, deep: bool) -> None:
    """Aggregate savings: cache + reasoning-library + cost-delta vs. baseline."""
    if ctx.invoked_subcommand is not None:
        return
    if segment:
        from atelier.core.capabilities.savings_summary import savings_segment

        session_id = os.environ.get("ATELIER_STATUS_SESSION_ID", "")
        live_cost = float(os.environ.get("ATELIER_STATUSLINE_COST_USD") or 0)
        live_in = int(os.environ.get("ATELIER_STATUSLINE_LIVE_IN_TOK") or 0)
        live_cache = int(os.environ.get("ATELIER_STATUSLINE_LIVE_CACHE_TOK") or 0)
        live_out = int(os.environ.get("ATELIER_STATUSLINE_LIVE_OUT_TOK") or 0)
        no_color = bool(os.environ.get("ATELIER_STATUSLINE_NO_COLOR") or os.environ.get("ATELIER_NO_COLOR"))
        # Write directly — click.echo strips ANSI when stdout is not a TTY
        # (which is always the case when captured via $() in statusline.sh).
        import sys

        sys.stdout.write(
            savings_segment(
                session_id,
                live_cost_usd=live_cost,
                live_in_tok=live_in,
                live_cache_tok=live_cache,
                live_out_tok=live_out,
                no_color=no_color,
            )
        )
        sys.stdout.flush()

        # Bridge: persist live token counts so the Codex stop hook can report
        # real usage instead of $0.0000.  The statusline gets token data from
        # Codex's native footer; the stop hook reads stats.json or the latest
        # workspace-scoped statusline snapshot. Without this write those two
        # data flows never meet.
        # Only for Codex (Claude Code has its own transcript-based path).
        # context_window.current_usage is the overwrite path in
        # update_session_stats — correct here because the statusline value is
        # always a cumulative session snapshot, not a per-turn delta.
        if os.environ.get("ATELIER_STATUS_HOST", "").strip().lower() == "codex" and (live_in > 0 or live_cache > 0):
            import contextlib

            with contextlib.suppress(Exception):
                from atelier.core.capabilities.plugin_runtime import record_codex_statusline_snapshot

                root_val = (
                    os.environ.get("ATELIER_ROOT")
                    or os.environ.get("ATELIER_STORE_ROOT")
                    or str(Path.home() / ".atelier")
                )
                model_val = (
                    os.environ.get("ATELIER_STATUS_MODEL") or os.environ.get("ATELIER_STATUS_MODEL_DISPLAY") or ""
                )
                workspace_val = os.environ.get("CODEX_WORKSPACE_ROOT") or os.environ.get("CLAUDE_WORKSPACE_ROOT") or ""
                snapshot: dict[str, Any] = {
                    "hook_event_name": "StatuslineUpdate",
                    "session_id": session_id,
                    # Cumulative snapshot — update_session_stats overwrites
                    # state["usage"] when this key is present.
                    "context_window": {
                        "current_usage": {
                            "input_tokens": live_in,
                            "cache_read_input_tokens": live_cache,
                            "output_tokens": live_out,
                        }
                    },
                }
                if model_val:
                    snapshot["model"] = model_val
                if workspace_val:
                    snapshot["cwd"] = workspace_val
                record_codex_statusline_snapshot(root_val, snapshot)

        return
    if line:
        from atelier.core.capabilities.savings_summary import savings_line

        session_id = os.environ.get("ATELIER_STATUS_SESSION_ID", "")
        if os.environ.get("ATELIER_STATUS_HOST", "").strip().lower() == "codex":
            from atelier.core.capabilities.plugin_runtime import build_codex_savings_line

            click.echo(build_codex_savings_line(ctx.obj["root"], session_id))
            return
        click.echo(
            savings_line(
                session_id,
                workspace=os.environ.get("CLAUDE_WORKSPACE_ROOT", "") or None,
            )
        )
        return
    from atelier.core.capabilities.plugin_runtime import build_savings_report
    from atelier.core.capabilities.session_optimizer import build_trace_optimization_report

    runs = _ledger_dir(ctx.obj["root"])
    rescue_events = 0
    rubric_failures = 0
    if runs.is_dir():
        for p in runs.glob("*/run.json"):
            try:
                snap = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for ev in snap.get("events", []):
                kind = ev.get("kind")
                if kind == "watchdog_alert":
                    sev = (ev.get("payload") or {}).get("severity")
                    if sev == "high":
                        rescue_events += 1
                if kind == "rubric_run" and (ev.get("payload") or {}).get("status") == "blocked":
                    rubric_failures += 1
    payload = build_savings_report(ctx.obj["root"])
    store = _load_store(ctx.obj["root"])
    payload["optimization"] = build_trace_optimization_report(store.list_traces(limit=5000), days=7)
    payload["rescue_events"] = rescue_events
    payload["rubric_failures_caught"] = rubric_failures
    if as_json:
        _emit(payload, as_json=True)
    else:
        _render_savings_rich(payload, deep=deep)
        if deep:
            _echo_vs_vanilla_block(ctx.obj["root"], deep=deep)


@savings_cmd.command("wire")
@click.argument("captures", nargs=-1, required=False)
@click.option(
    "--input-price",
    type=float,
    default=3.0,
    show_default=True,
    help="Input token price per 1M tokens.",
)
@click.option(
    "--output-price",
    type=float,
    default=15.0,
    show_default=True,
    help="Output token price per 1M tokens.",
)
@click.option(
    "--cache-read",
    type=float,
    default=0.30,
    show_default=True,
    help="Cache-read token price per 1M tokens.",
)
@click.option(
    "--cache-write",
    type=float,
    default=3.75,
    show_default=True,
    help="Cache-write token price per 1M tokens.",
)
@click.option("--out", type=click.Path(path_type=Path, file_okay=False), default=None)
def savings_wire_cmd(
    captures: tuple[str, ...],
    input_price: float,
    output_price: float,
    cache_read: float,
    cache_write: float,
    out: Path | None,
) -> None:
    """Compare provider-billed usage from mitmproxy .flow captures."""
    if not captures:
        raise click.ClickException(
            "Provide captures as LABEL=PATH. Example: atelier savings wire baseline=off.flow atelier=on.flow"
        )
    repo_root = Path.cwd().resolve()
    run_dir = _wire_report_dir(out)
    report_path = run_dir / "report.txt"
    report = _run_capture(
        [
            *_python_cmd(repo_root),
            "-m",
            "benchmarks.wire_savings.report",
            *captures,
            "--in",
            str(input_price),
            "--out",
            str(output_price),
            "--cache-read",
            str(cache_read),
            "--cache-write",
            str(cache_write),
        ],
        cwd=repo_root,
        label="wire savings report",
    )
    report_path.write_text(report, encoding="utf-8")
    click.echo(f"Report: {report_path}")


def _wire_report_dir(out: Path | None) -> Path:
    if out is not None:
        path = out.resolve()
    else:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = Path.cwd().resolve() / "reports" / "savings" / "wire" / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _python_cmd(repo_root: Path) -> list[str]:
    if which("uv") and (repo_root / "pyproject.toml").is_file():
        return ["uv", "run", "--project", str(repo_root), "python"]
    return [sys.executable]


def _run_capture(cmd: list[str], *, cwd: Path, label: str) -> str:
    click.echo("Running: " + " ".join(cmd))
    completed = subprocess.run(
        cmd,
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        click.echo(completed.stdout.rstrip())
    if completed.stderr:
        click.echo(completed.stderr.rstrip(), err=True)
    if completed.returncode != 0:
        raise click.ClickException(f"{label} failed with exit {completed.returncode}")
    return completed.stdout


def _legacy_optimize_report(ctx: click.Context, host: str | None, days: int, limit: int) -> dict[str, Any]:
    from atelier.core.capabilities.session_optimizer import build_trace_optimization_report

    store = _load_store(ctx.obj["root"])
    return build_trace_optimization_report(store.list_traces(limit=5000), days=days, host=host, limit=limit)


def _run_external_optimize(ctx: click.Context, days: int) -> dict[str, Any] | None:
    from atelier.gateway.integrations.external_analytics import (
        persist_external_reports,
        run_external_reports,
    )

    period = "week" if days <= 7 else "30days"
    try:
        external_batch = run_external_reports(
            tool="codeburn:optimize", period=period, cwd=Path.cwd(), include_optimize=True
        )
        store = _load_store(ctx.obj["root"])
        persist_external_reports(store, external_batch, source="cli_optimize")
        return external_batch["reports"][0] if external_batch["reports"] else None
    except Exception as exc:
        logging.exception("Recovered from broad exception handler")
        logger.debug("External optimization report failed: %s", exc)
        return None


def _advisor_result(ctx: click.Context, host: str | None, days: int) -> Any:
    from atelier.core.capabilities.optimization import load_current_policy, optimize_from_traces

    store = _load_store(ctx.obj["root"])
    current_policy = load_current_policy(ctx.obj["root"])
    return optimize_from_traces(store.list_traces(limit=5000), current_policy=current_policy, days=days, host=host)


def _benchmark_evidence_from_options(
    *,
    runs_path: Path | None,
    baseline_cost_usd: float | None,
    candidate_cost_usd: float | None,
    margin: float,
    confidence: float,
) -> Any:
    from atelier.core.capabilities.optimization import BenchmarkEvidence

    provided = [runs_path is not None, baseline_cost_usd is not None, candidate_cost_usd is not None]
    if not any(provided):
        return None
    if not all(provided):
        raise click.ClickException("--runs, --baseline-cost-usd, and --candidate-cost-usd must be provided together")
    return BenchmarkEvidence(
        runs_path=str(runs_path),
        baseline_cost_usd=baseline_cost_usd,
        candidate_cost_usd=candidate_cost_usd,
        margin=margin,
        confidence=confidence,
    )


@click.group("optimize", invoke_without_command=True)
@click.option(
    "--host",
    type=click.Choice(list(SUPPORTED_SESSION_IMPORT_HOSTS)),
    default=None,
)
@click.option("--days", default=7, show_default=True, type=int)
@click.option("--limit", default=6, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_group(ctx: click.Context, host: str | None, days: int, limit: int, as_json: bool) -> None:
    """Show and apply Optimization Advisor recommendations."""
    if ctx.invoked_subcommand is not None:
        return

    from atelier.core.capabilities.optimization import append_history
    from atelier.core.capabilities.reporting.dashboard import _render_optimization_summary

    report = _legacy_optimize_report(ctx, host, days, limit)
    result = _advisor_result(ctx, host, days)
    append_history(ctx.obj["root"], result)
    report["advisor"] = result.to_dict()
    report["external"] = _run_external_optimize(ctx, days)
    if as_json:
        _emit(report, as_json=True)
        return
    _render_optimization_summary(result)
    click.echo("")
    click.echo(
        f"Legacy trace recommendations: {report['estimated_tokens_saved']} tokens, ${report['estimated_usd_saved']:.4f}"
    )
    if not report["recommendations"]:
        click.echo("No legacy trace recommendations found for this window.")
        return
    for index, recommendation in enumerate(report["recommendations"], start=1):
        click.echo("")
        click.echo(f"{index}. {recommendation['title']}  {recommendation['severity']}")
        click.echo(f"   Sessions: {recommendation['session_count']}")
        click.echo(
            f"   Savings: {recommendation['estimated_tokens_saved']} tokens, ${recommendation['estimated_usd_saved']:.4f}"
        )
        click.echo(f"   Action: {recommendation['action']}")


@optimize_group.command("details")
@click.option("--host", type=click.Choice(list(SUPPORTED_SESSION_IMPORT_HOSTS)), default=None)
@click.option("--days", default=7, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_details(ctx: click.Context, host: str | None, days: int, as_json: bool) -> None:
    """Show Pareto frontier, compaction, and routing breakdowns."""
    from atelier.core.capabilities.reporting.dashboard import _render_optimization_details

    result = _advisor_result(ctx, host, days)
    if as_json:
        _emit(result.to_dict(), as_json=True)
        return
    _render_optimization_details(result)


@optimize_group.command("apply")
@click.option("--preset", type=click.Choice(["conservative", "balanced", "economy"]), default=None)
@click.option("--recommended", is_flag=True)
@click.option("--custom", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_apply(
    ctx: click.Context,
    preset: str | None,
    recommended: bool,
    custom: Path | None,
    as_json: bool,
) -> None:
    """Apply a preset, the latest recommendation, or a custom policy YAML."""
    from atelier.core.capabilities.optimization.policy import (
        policy_from_config,
        preset_policy,
        save_policy,
    )

    selected = sum(1 for value in (preset, custom) if value is not None) + (1 if recommended else 0)
    if selected != 1:
        raise click.ClickException("choose exactly one of --preset, --recommended, or --custom")

    if preset is not None:
        policy = preset_policy(preset)
    elif custom is not None:
        import yaml as _yaml

        try:
            raw = _yaml.safe_load(custom.read_text(encoding="utf-8"))
        except _yaml.YAMLError as exc:
            raise click.ClickException(f"invalid custom policy YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise click.ClickException("custom policy YAML must be a mapping")
        policy = policy_from_config(raw)
    else:
        result = _advisor_result(ctx, None, 7)
        if not result.has_recommendation:
            raise click.ClickException(result.message)
        policy = result.recommended_policy

    path = save_policy(ctx.obj["root"], policy)
    payload = {"applied": policy.to_dict(), "path": str(path)}
    if as_json:
        _emit(payload, as_json=True)
    else:
        click.echo(f"Applied optimization policy: {policy.name} ({policy.preset})")
        click.echo(f"Saved: {path}")


@optimize_group.command("run")
@click.option("--host", type=click.Choice(list(SUPPORTED_SESSION_IMPORT_HOSTS)), default=None)
@click.option("--days", default=7, show_default=True, type=int)
@click.option(
    "--runs",
    "runs_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="TerminalBench runs.jsonl file or a directory that contains it.",
)
@click.option("--baseline-cost-usd", type=float, default=None)
@click.option("--candidate-cost-usd", type=float, default=None)
@click.option("--margin", default=0.05, show_default=True, type=float)
@click.option("--confidence", default=0.95, show_default=True, type=float)
@click.option(
    "--proposal-tokens-threshold",
    type=int,
    default=None,
    help="Minimum projected token savings required before writing a proposal artifact.",
)
@click.option("--open-pr", is_flag=True, help="Open a draft PR after the proposal artifact is written.")
@click.option("--dry-run", is_flag=True, help="Preview PR preparation without git or GitHub side effects.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_run(
    ctx: click.Context,
    host: str | None,
    days: int,
    runs_path: Path | None,
    baseline_cost_usd: float | None,
    candidate_cost_usd: float | None,
    margin: float,
    confidence: float,
    proposal_tokens_threshold: int | None,
    open_pr: bool,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Run the optimization advisor intentionally and evaluate proposal readiness."""
    from atelier.core.capabilities.optimization import run_optimization_cycle

    evidence = _benchmark_evidence_from_options(
        runs_path=runs_path,
        baseline_cost_usd=baseline_cost_usd,
        candidate_cost_usd=candidate_cost_usd,
        margin=margin,
        confidence=confidence,
    )
    try:
        payload = run_optimization_cycle(
            store_root=ctx.obj["root"],
            host=host,
            days=max(1, days),
            source="cli",
            open_pr=open_pr,
            dry_run=dry_run,
            proposal_tokens_threshold=proposal_tokens_threshold,
            benchmark_evidence=evidence,
            store=_load_store(ctx.obj["root"]),
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc

    action = str(payload.get("proposal", {}).get("action", ""))
    if open_pr and action not in {"pr_opened", "pr_dry_run"}:
        raise click.ClickException(f"open-pr blocked: {action}")

    if as_json:
        _emit(payload, as_json=True)
        return

    advisor = payload["advisor"]
    current_policy = advisor.get("current_policy") or {}
    click.echo(f"Repo root: {payload['repo_root']}")
    click.echo(f"Current preset: {current_policy.get('preset', '-')}")
    click.echo(
        f"Estimated weekly savings: ${float(advisor.get('weekly_savings_usd', 0.0) or 0.0):.2f}  "
        f"confidence={advisor.get('confidence', '-')}"
    )
    click.echo(f"Proposal action: {action}")
    artifact_path = payload.get("proposal", {}).get("artifact_path")
    if artifact_path:
        click.echo(f"Proposal artifact: {artifact_path}")
    pr_info = payload.get("proposal", {}).get("open_pr")
    if isinstance(pr_info, dict) and pr_info:
        click.echo(f"PR branch: {pr_info.get('branch', '-')}")
        if pr_info.get("url"):
            click.echo(f"PR URL: {pr_info['url']}")


@optimize_group.group("auto")
def optimize_auto() -> None:
    """Inspect or persist autonomous optimization automation settings."""


@optimize_auto.command("status")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_auto_status(ctx: click.Context, as_json: bool) -> None:
    """Show the persisted optimize automation configuration."""
    from atelier.core.capabilities.optimization import load_automation_config
    from atelier.core.capabilities.optimization.policy import optimization_config_path

    automation = load_automation_config(ctx.obj["root"]).to_dict()
    payload = {
        "automation": automation,
        "path": str(optimization_config_path(ctx.obj["root"])),
    }
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo(f"Auto optimize: {'enabled' if automation['enabled'] else 'disabled'}")
    click.echo(f"Config: {payload['path']}")


@optimize_auto.command("enable")
@click.option(
    "--runs",
    "runs_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Optional TerminalBench runs.jsonl file or directory for NI gating.",
)
@click.option("--baseline-cost-usd", type=float, default=None)
@click.option("--candidate-cost-usd", type=float, default=None)
@click.option("--margin", default=0.05, show_default=True, type=float)
@click.option("--confidence", default=0.95, show_default=True, type=float)
@click.option("--proposal-tokens-threshold", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_auto_enable(
    ctx: click.Context,
    runs_path: Path | None,
    baseline_cost_usd: float | None,
    candidate_cost_usd: float | None,
    margin: float,
    confidence: float,
    proposal_tokens_threshold: int | None,
    as_json: bool,
) -> None:
    """Enable periodic optimize jobs using the shared persisted config."""
    from atelier.core.capabilities.optimization import (
        AutomationConfig,
        load_automation_config,
        save_automation_config,
    )
    from atelier.core.capabilities.optimization.policy import optimization_config_path

    evidence = _benchmark_evidence_from_options(
        runs_path=runs_path,
        baseline_cost_usd=baseline_cost_usd,
        candidate_cost_usd=candidate_cost_usd,
        margin=margin,
        confidence=confidence,
    )
    current = load_automation_config(ctx.obj["root"])
    updated = AutomationConfig(
        enabled=True,
        minimum_projected_tokens_saved=(
            current.minimum_projected_tokens_saved
            if proposal_tokens_threshold is None
            else max(0, proposal_tokens_threshold)
        ),
        benchmark_evidence=evidence or current.benchmark_evidence,
        last_proposal_fingerprint=current.last_proposal_fingerprint,
        last_proposal_at=current.last_proposal_at,
    )
    path = save_automation_config(ctx.obj["root"], updated)
    payload = {"automation": updated.to_dict(), "path": str(path or optimization_config_path(ctx.obj["root"]))}
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo("Auto optimize enabled.")
    click.echo(f"Saved: {payload['path']}")


@optimize_auto.command("disable")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_auto_disable(ctx: click.Context, as_json: bool) -> None:
    """Disable periodic optimize jobs without discarding saved evidence."""
    from atelier.core.capabilities.optimization import (
        AutomationConfig,
        load_automation_config,
        save_automation_config,
    )

    current = load_automation_config(ctx.obj["root"])
    updated = AutomationConfig(
        enabled=False,
        minimum_projected_tokens_saved=current.minimum_projected_tokens_saved,
        benchmark_evidence=current.benchmark_evidence,
        last_proposal_fingerprint=current.last_proposal_fingerprint,
        last_proposal_at=current.last_proposal_at,
    )
    path = save_automation_config(ctx.obj["root"], updated)
    payload = {"automation": updated.to_dict(), "path": str(path)}
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo("Auto optimize disabled.")
    click.echo(f"Saved: {payload['path']}")


@optimize_group.group("shadow", invoke_without_command=True)
@click.option("--policy", "policy_name", default="recommended", show_default=True)
@click.option("--days", default=7, show_default=True, type=int)
@click.option("--max-daily-spend-usd", type=float, default=None)
@click.option("--i-understand-this-costs-money", is_flag=True)
@click.option("--yes", is_flag=True, help="Accept the pre-run shadow cost estimate.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_shadow(
    ctx: click.Context,
    policy_name: str,
    days: int,
    max_daily_spend_usd: float | None,
    i_understand_this_costs_money: bool,
    yes: bool,
    as_json: bool,
) -> None:
    """Shadow-run a policy in parallel without changing live behavior."""
    if ctx.invoked_subcommand is not None:
        return

    from atelier.core.capabilities.optimization.policy import (
        record_shadow_consent,
        shadow_consent_at,
    )
    from atelier.core.capabilities.optimization.shadow import build_shadow_state, save_shadow_state

    if shadow_consent_at(ctx.obj["root"]) is None:
        if not i_understand_this_costs_money:
            raise click.ClickException(
                "First shadow run requires --i-understand-this-costs-money because it may spend real money."
            )
        record_shadow_consent(ctx.obj["root"])

    result = _advisor_result(ctx, None, max(1, days))
    try:
        state = build_shadow_state(
            policy=policy_name,
            days=days,
            baseline_weekly_cost_usd=result.baseline_weekly_cost_usd,
            max_daily_spend_usd=max_daily_spend_usd,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json and not yes:
        _emit(
            {
                "status": "confirmation_required",
                "message": "Shadow run not started. Re-run with --yes to accept the pre-run cost estimate.",
                "estimate": state.to_dict(),
            },
            as_json=True,
        )
        return
    if not as_json and not yes:
        click.echo(
            f"Shadow will spend approximately ${state.estimated_weekly_spend_usd:.2f} this week "
            f"against your ${state.baseline_weekly_cost_usd:.2f} baseline."
        )
        if not click.confirm("Continue?", default=False):
            click.echo("Shadow run cancelled.")
            return

    save_shadow_state(ctx.obj["root"], state)
    if as_json:
        _emit(state.to_dict(), as_json=True)
    else:
        click.echo(f"Shadow run started for policy {policy_name}.")


@optimize_shadow.command("status")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_shadow_status(ctx: click.Context, as_json: bool) -> None:
    """Show live shadow spend versus cap."""
    from atelier.core.capabilities.optimization.shadow import load_shadow_state

    state = load_shadow_state(ctx.obj["root"]) or {"status": "not_running"}
    if as_json:
        _emit(state, as_json=True)
        return
    click.echo(f"Shadow status: {state.get('status', 'not_running')}")
    if state.get("status") != "not_running":
        click.echo(
            f"Shadow spend (this run only): ${float(state.get('spend_usd', 0.0)):.2f} / "
            f"${float(state.get('max_daily_spend_usd', 0.0)):.2f} daily cap"
        )


@optimize_shadow.command("stop")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_shadow_stop(ctx: click.Context, as_json: bool) -> None:
    """Halt the active shadow run immediately."""
    from atelier.core.capabilities.optimization.shadow import stop_shadow

    state = stop_shadow(ctx.obj["root"])
    if as_json:
        _emit(state, as_json=True)
    else:
        click.echo(f"Shadow status: {state.get('status')}")


@optimize_shadow.command("forget-consent")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_shadow_forget_consent(ctx: click.Context, as_json: bool) -> None:
    """Revoke persistent shadow-run cost consent."""
    from atelier.core.capabilities.optimization.policy import forget_shadow_consent

    revoked = forget_shadow_consent(ctx.obj["root"])
    payload = {"revoked": revoked}
    if as_json:
        _emit(payload, as_json=True)
    else:
        click.echo("Shadow consent revoked." if revoked else "No shadow consent was recorded.")


@optimize_group.command("compare")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_compare(ctx: click.Context, as_json: bool) -> None:
    """Compare current policy with the active or latest shadow run."""
    from atelier.core.capabilities.optimization.shadow import load_shadow_state

    result = _advisor_result(ctx, None, 7)
    state = load_shadow_state(ctx.obj["root"]) or {"status": "not_running", "spend_usd": 0.0}
    payload = {"advisor": result.to_dict(), "shadow": state}
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo(f"Current weekly cost: ${result.baseline_weekly_cost_usd:.2f}")
    if result.has_recommendation:
        click.echo(f"Recommended weekly savings: ${result.weekly_savings_usd:.2f}")
    click.echo(f"Shadow spend (this run only): ${float(state.get('spend_usd', 0.0)):.2f}")


@optimize_group.command("history")
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def optimize_history(ctx: click.Context, limit: int, as_json: bool) -> None:
    """Show past optimization recommendations and outcomes."""
    from atelier.core.capabilities.optimization import load_history

    history = load_history(ctx.obj["root"], limit=limit)
    if as_json:
        _emit(history, as_json=True)
        return
    if not history:
        click.echo("No optimization history recorded yet.")
        return
    for item in reversed(history):
        recorded_at = item.get("recorded_at", "-")
        confidence = item.get("confidence", "-")
        savings = float(item.get("weekly_savings_usd", 0.0) or 0.0)
        click.echo(f"{recorded_at}  confidence={confidence}  weekly_savings=${savings:.2f}")


@optimize_group.command("gate")
@click.option(
    "--runs",
    "runs_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="TerminalBench runs.jsonl file or a directory that contains it.",
)
@click.option("--baseline-cost-usd", required=True, type=float)
@click.option("--candidate-cost-usd", required=True, type=float)
@click.option("--margin", default=0.05, show_default=True, type=float)
@click.option("--confidence", default=0.95, show_default=True, type=float)
@click.option("--json", "as_json", is_flag=True)
def optimize_gate(
    runs_path: Path,
    baseline_cost_usd: float,
    candidate_cost_usd: float,
    margin: float,
    confidence: float,
    as_json: bool,
) -> None:
    """Evaluate the TerminalBench + cost non-inferiority gate."""
    from atelier.core.capabilities.optimization import evaluate_non_inferiority_from_runs

    try:
        verdict = evaluate_non_inferiority_from_runs(
            runs_path,
            baseline_cost_usd=baseline_cost_usd,
            candidate_cost_usd=candidate_cost_usd,
            margin=margin,
            confidence=confidence,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc

    payload = verdict.to_dict()
    if as_json:
        _emit(payload, as_json=True)
        return

    click.echo(f"Non-inferiority gate: {'PASS' if verdict.passed else 'FAIL'}")
    click.echo(
        f"Pass-rate delta (on-off): {verdict.pass_rate_delta:+.4f}  "
        f"CI lower bound: {verdict.delta_lower_bound:+.4f}  "
        f"margin: -{verdict.margin:.4f}"
    )
    click.echo(
        f"Estimated cost delta (candidate-baseline): ${verdict.estimated_cost_delta_usd:+.4f}  "
        f"savings: ${verdict.estimated_cost_savings_usd:.4f}"
    )
    if verdict.reasons:
        click.echo("Reasons:")
        for reason in verdict.reasons:
            click.echo(f"- {reason}")


@click.command("external-status")
@click.option("--json", "as_json", is_flag=True)
def external_status_cmd(as_json: bool) -> None:
    """Show optional upstream analyzer availability and integration posture."""
    from atelier.gateway.integrations.external_analytics import external_status

    payload = {"tools": external_status(cwd=Path.cwd())}
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo("External analyzers")
    click.echo("")
    for item in payload["tools"]:
        state = "available" if item["available"] else "missing"
        click.echo(f"- {item['display_name']} [{state}]")
        click.echo(f"  license: {item['license']}")
        click.echo(f"  mode: {item['execution_mode']}")
        if item.get("path"):
            click.echo(f"  path: {item['path']}")
        click.echo(f"  update: {item['update_strategy']}")
        for note in item.get("notes", []):
            click.echo(f"  note: {note}")
        warning = item.get("warning")
        if warning:
            click.echo(f"  warning: {warning}")
        click.echo(f"  install: {item['install_hint']}")
        click.echo("")


@click.command("external-report")
@click.option(
    "--tool",
    type=click.Choice(_EXTERNAL_REPORT_TOOL_CHOICES),
    default="all",
    show_default=True,
)
@click.option(
    "--period",
    type=click.Choice(["today", "week", "month", "30days", "all"]),
    default="week",
    show_default=True,
)
@click.option(
    "--persist",
    is_flag=True,
    default=False,
    help="Store the collected report snapshots for the API/UI.",
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def external_report_cmd(ctx: click.Context, tool: str, period: str, persist: bool, as_json: bool) -> None:
    """Run upstream JSON reports from supported external analyzers."""
    from atelier.gateway.integrations.external_analytics import (
        persist_external_reports,
        run_external_report,
        run_external_reports,
    )

    if as_json:
        try:
            payload = run_external_reports(tool=tool, period=period, cwd=Path.cwd(), include_optimize=True)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        if persist:
            store = _load_store(ctx.obj["root"])
            payload["persisted"] = persist_external_reports(store, payload, source="cli")
        _emit(payload, as_json=True)
        return

    selected_tools = list(_EXTERNAL_REPORT_ALL_TOOLS) if tool == "all" else [tool]
    store = _load_store(ctx.obj["root"]) if persist else None

    click.echo(f"External reports  period={period}")
    click.echo("")

    total_persisted = 0
    for selected_tool in selected_tools:
        click.echo(f"[external-report] running {selected_tool} period={period}...")
        sys.stdout.flush()
        try:
            report = run_external_report(selected_tool, period=period, cwd=Path.cwd())
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        persisted: list[dict[str, Any]] = []
        if store is not None:
            batch = {
                "generated_at": datetime.now(UTC).isoformat(),
                "tool": selected_tool,
                "period": period,
                "reports": [report],
            }
            persisted = persist_external_reports(store, batch, source="cli")
            total_persisted += len(persisted)

        status = "ok" if report.get("ok") else "failed"
        persisted_suffix = f" persisted={len(persisted)}" if persist else ""
        click.echo(f"[external-report] done {selected_tool} status={status}{persisted_suffix}")

        click.echo(f"- {report['tool']}")
        click.echo(f"  cmd: {report.get('command_display') or '-'}")
        if report["ok"]:
            click.echo("  status: ok")
        else:
            click.echo(f"  status: failed ({report.get('error') or report.get('returncode')})")
            message = report.get("message")
            if message:
                click.echo(f"  detail: {message}")
            stderr = report.get("stderr")
            if stderr:
                click.echo(f"  stderr: {stderr[:240]}")
            parse_error = report.get("parse_error")
            if parse_error:
                click.echo(f"  parse: {parse_error}")
            continue

        body = report.get("payload")
        if isinstance(body, dict):
            if report["tool"] == "codeburn":
                overview = body.get("overview") or {}
                click.echo(
                    "  summary: "
                    f"cost={overview.get('cost', '-')} calls={overview.get('calls', '-')} sessions={overview.get('sessions', '-')}"
                )
            elif report["tool"] == "codeburn:optimize":
                overview = body.get("overview") or {}
                click.echo(
                    "  summary: "
                    f"waste={overview.get('estimated_usd_saved', '-')} grade={overview.get('health_grade', '-')} score={overview.get('health_score', '-')}"
                )
            elif report["tool"] == "tokscale":
                click.echo(f"  summary: keys={', '.join(sorted(body.keys())[:6])}")
        click.echo("")

    if persist:
        click.echo(f"persisted {total_persisted} snapshots")

    _echo_vs_vanilla_block(ctx.obj["root"])


@click.command("savings-detail")
@click.option("--json", "as_json", is_flag=True)
@click.option("--limit", default=20, show_default=True, help="Top N operations.")
@click.pass_context
def savings_detail(ctx: click.Context, as_json: bool, limit: int) -> None:
    """Per-operation cost-delta breakdown (last_cost - new_cost, baseline %)."""
    from atelier.infra.runtime.cost_tracker import CostTracker

    tracker = CostTracker(ctx.obj["root"])
    summary = tracker.total_savings()
    rows = summary["per_operation"][:limit]
    if as_json:
        _emit(
            {
                "summary": {k: v for k, v in summary.items() if k != "per_operation"},
                "operations": rows,
            },
            as_json=True,
        )
        return
    click.echo(
        f"Tracked operations: {summary['operations_tracked']}  "
        f"calls={summary['total_calls']}  "
        f"saved=${summary['saved_usd']:.4f} ({summary['saved_pct']}%)"
    )
    click.echo("-" * 92)
    click.echo(
        f"{'op_key':18} {'calls':>5} {'baseline$':>10} "
        f"{'last$':>10} {'now$':>10} {'d_last$':>10} {'d_base$':>10} {'%down':>6}  domain"
    )
    click.echo("-" * 92)
    for r in rows:
        click.echo(
            f"{r['op_key']:18} {r['calls_count']:>5} "
            f"{r['baseline_cost_usd']:>10.4f} {r['last_cost_usd']:>10.4f} "
            f"{r['current_cost_usd']:>10.4f} {r['delta_vs_last_usd']:>10.4f} "
            f"{r['delta_vs_base_usd']:>10.4f} {r['pct_vs_base']:>6.1f}  "
            f"{r.get('domain', '-')}"
        )


@click.command("savings-reset")
@click.pass_context
def savings_reset(ctx: click.Context) -> None:
    s = _load_smart_state(ctx.obj["root"])
    s["savings"] = {"calls_avoided": 0, "tokens_saved": 0}
    _save_smart_state(ctx.obj["root"], s)
    from atelier.infra.runtime.cost_tracker import save_cost_history

    save_cost_history(ctx.obj["root"], {"operations": {}})
    click.echo("savings reset (cache + cost history)")


external_group = click.Group("external", help="Run supported external analyzer reports.")
external_group.add_command(external_status_cmd, name="status")
external_group.add_command(external_report_cmd, name="report")
savings_cmd.add_command(external_group)
savings_cmd.add_command(savings_detail, name="detail")
savings_cmd.add_command(savings_reset, name="reset")
