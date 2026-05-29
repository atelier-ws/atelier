"""Thin ``atelier benchmark`` and ``atelier bench`` command groups (QBL-CLI-02).

Suite-execution logic lives in ``infra/benchmarks/cli_runners.py``; these
callbacks are thin wrappers that format runner results. The optional SWE
benchmark group is attached via ``_register_swe_benchmark_group`` with the same
``ModuleNotFoundError`` resilience as the original ``app.py`` registration, so a
partial install (no ``benchmarks.swe``) never breaks CLI startup (T-25-09).

Groups are standalone Click objects (Pattern 1) so ``commands/__init__.py`` can
``add_command`` them onto the root ``cli`` group.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from atelier.gateway.cli.commands._shared import _core_runtime, _emit
from atelier.infra.benchmarks.cli_runners import (
    _run_benchmark_core,
    _run_benchmark_hosts,
    _run_benchmark_packs,
)


@click.group("benchmark")
def benchmark_group() -> None:
    """Run Atelier benchmark suites and reports."""


@benchmark_group.command("run")
@click.option(
    "--prompt",
    "prompts",
    multiple=True,
    help="Prompts to benchmark (repeat). Defaults to 5 built-in tasks.",
)
@click.option("--model", default="claude-sonnet-4.6", show_default=True)
@click.option("--rounds", default=3, show_default=True, help="How many rounds per prompt.")
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write report/export output to this path.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "markdown", "csv"]),
    default="json",
    show_default=True,
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def benchmark_run(
    ctx: click.Context,
    prompts: tuple[str, ...],
    model: str,
    rounds: int,
    output_path: Path | None,
    output_format: str,
    as_json: bool,
) -> None:
    """Run the core runtime benchmark and write the latest report."""
    from atelier.infra.runtime.benchmarking import (
        benchmark_report_path,
        export_runtime_report,
        render_runtime_report,
        run_runtime_benchmark,
    )

    report = run_runtime_benchmark(
        root=ctx.obj["root"],
        prompts=prompts,
        model=model,
        rounds=rounds,
    )
    if output_path is not None:
        export_runtime_report(report, output_path=output_path, output_format=output_format)
    if as_json:
        _emit(report, as_json=True)
        return
    click.echo(render_runtime_report(report))
    click.echo(f"saved report: {benchmark_report_path(ctx.obj['root'])}")


@benchmark_group.command("savings")
@click.option(
    "--prompt",
    "prompts",
    multiple=True,
    help="Prompts to benchmark (repeat). Defaults to replay prompts.",
)
@click.option("--model", default="claude-sonnet-4.6", show_default=True)
@click.option(
    "--baseline-command",
    required=True,
    help="Command template for baseline runs. Receives ATELIER_BENCH_PROMPT.",
)
@click.option(
    "--atelier-command",
    required=True,
    help="Command template for Atelier-enabled runs. Receives ATELIER_BENCH_PROMPT.",
)
@click.option(
    "--timeout",
    "timeout_s",
    default=600.0,
    show_default=True,
    type=float,
    help="Seconds per command.",
)
@click.option("--max-prompts", default=5, show_default=True, type=int, help="Default replay prompts to run.")
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def benchmark_savings(
    ctx: click.Context,
    prompts: tuple[str, ...],
    model: str,
    baseline_command: str,
    atelier_command: str,
    timeout_s: float,
    max_prompts: int,
    output_path: Path | None,
    as_json: bool,
) -> None:
    """Run paired baseline-vs-Atelier command savings benchmarks."""
    from benchmarks.swe.savings_replay import run_paired_command_benchmark

    tasks = [
        {"id": f"prompt-{idx}", "task_type": "ad_hoc", "task": prompt} for idx, prompt in enumerate(prompts, start=1)
    ]
    paired_report = run_paired_command_benchmark(
        root=ctx.obj["root"],
        baseline_command=baseline_command,
        atelier_command=atelier_command,
        tasks=tasks or None,
        model=model,
        timeout_s=timeout_s,
        max_prompts=max_prompts,
    )
    payload = paired_report.to_dict()
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo(
        f"savings benchmark complete: {payload['tokens_saved']} tokens, "
        f"{payload['reduction_pct']:.2f}% reduction, "
        f"${payload['cost_saved_usd']:.4f} saved"
    )
    click.echo(f"saved report: {ctx.obj['root'] / 'benchmarks' / 'savings' / 'latest.json'}")


@benchmark_group.command("savings-compact")
@click.option(
    "--corpus",
    "corpus_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory of claude-*.jsonl session exports. Defaults to exports/ in the repo root.",
)
@click.option(
    "--max-sessions",
    default=None,
    type=int,
    show_default=True,
    help="Maximum number of qualifying sessions to process.",
)
@click.option(
    "--min-context",
    "min_context_tokens",
    default=80_000,
    show_default=True,
    type=int,
    help="Skip sessions whose peak context is below this token threshold.",
)
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def benchmark_savings_compact(
    ctx: click.Context,
    corpus_dir: Path | None,
    max_sessions: int | None,
    min_context_tokens: int,
    output_path: Path | None,
    as_json: bool,
) -> None:
    """Measure additional context freed by Atelier compact vs native /compact.

    Reads real Claude Code session exports, detects native compaction events
    (context drops >= 40 %), and compares native output (measured) vs Atelier
    estimate. Reports the *delta* only - never pretends native doesn't compact.

    Output is written to <root>/benchmarks/savings/compact_latest.json.
    """
    from benchmarks.swe.compact_bench import run_compact_bench

    if corpus_dir is None:
        # Try to find exports/ relative to the project root
        corpus_dir = ctx.obj["root"].parent / "exports"
        if not corpus_dir.is_dir():
            raise click.ClickException("Could not locate exports/ directory. Pass --corpus PATH explicitly.")

    report = run_compact_bench(
        corpus_dir,
        max_sessions=max_sessions,
        min_context_tokens=min_context_tokens,
    )

    out_path = output_path or ctx.obj["root"] / "benchmarks" / "savings" / "compact_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if as_json:
        _emit(report, as_json=True)
        return

    n = report["sessions_benchmarked"]
    delta = report["avg_delta_tokens"]
    cost = report["total_cost_saved_usd"]
    pct = report.get("atelier_vs_native_delta_pct", 0.0)
    click.echo(
        f"savings-compact: {n} sessions | "
        f"avg delta {delta:+,} tokens ({pct:+.1f}% vs native) | "
        f"${cost:.4f} additional savings"
    )
    click.echo(f"saved report: {out_path}")


@benchmark_group.command("savings-routing")
@click.option(
    "--corpus",
    "corpus_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory of claude-*.jsonl session exports. Defaults to exports/ in the repo root.",
)
@click.option(
    "--max-sessions",
    default=None,
    type=int,
    show_default=True,
    help="Maximum number of sessions to process.",
)
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def benchmark_savings_routing(
    ctx: click.Context,
    corpus_dir: Path | None,
    max_sessions: int | None,
    output_path: Path | None,
    as_json: bool,
) -> None:
    """Measure cost savings from Atelier model routing vs actual session model.

    Reads real Claude Code session exports, runs ModelRouter per turn, and
    computes cost delta between actual model and recommended cheaper tier.
    Only positive deltas count - sessions already on an optimal model show $0.

    Output is written to <root>/benchmarks/savings/routing_latest.json.
    """
    from benchmarks.swe.routing_bench import run_routing_bench

    if corpus_dir is None:
        corpus_dir = ctx.obj["root"].parent / "exports"
        if not corpus_dir.is_dir():
            raise click.ClickException("Could not locate exports/ directory. Pass --corpus PATH explicitly.")

    report = run_routing_bench(corpus_dir, max_sessions=max_sessions)

    out_path = output_path or ctx.obj["root"] / "benchmarks" / "savings" / "routing_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    if as_json:
        _emit(report, as_json=True)
        return

    n = report["sessions_benchmarked"]
    turns = report["total_turns_analyzed"]
    down = report["total_downtiered_turns"]
    pct = report["downtiered_pct"]
    cost = report["total_cost_saved_usd"]
    by_tier = report.get("by_tier", {})
    click.echo(
        f"savings-routing: {n} sessions | "
        f"{turns:,} turns | "
        f"{down:,} downtiered ({pct:.1f}%) | "
        f"${cost:.4f} saved"
    )
    click.echo(
        f"  by tier: cheap={by_tier.get('cheap', 0):,}  medium={by_tier.get('medium', 0):,}  expensive={by_tier.get('expensive', 0):,}"
    )
    click.echo(f"saved report: {out_path}")


@benchmark_group.command("quality-routing")
@click.option(
    "--corpus",
    "corpus_dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory containing claude/*.jsonl session exports.",
)
@click.option("--max-sessions", default=None, type=int, help="Cap sessions processed.")
@click.pass_context
def benchmark_quality_routing(
    ctx: click.Context,
    corpus_dir: Path | None,
    max_sessions: int | None,
) -> None:
    """Routing QUALITY benchmark: how safe are downtiered recommendations?

    Classifies each downtiered turn as safe / moderate / risky using:
      - tool risk (Edit=1.0, Bash=0.4, Read=0.0)
      - output complexity (tokens as reasoning proxy)
      - immediate error (did the tool call fail right after?)
    """
    from benchmarks.swe.routing_quality_bench import run_routing_quality_bench

    root: Path = ctx.obj["root"]
    if corpus_dir is None:
        corpus_dir = root.parent / "exports"
    if not corpus_dir.exists():
        raise click.ClickException(f"corpus not found: {corpus_dir}")

    report = run_routing_quality_bench(corpus_dir, max_sessions=max_sessions)

    out_dir = root / "benchmarks" / "savings"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "routing_quality_latest.json"
    out_path.write_text(json.dumps(report, indent=2))

    n = report["sessions_benchmarked"]
    total_down = report["total_downtiered_turns"]
    safe_pct = report["safe_pct"]
    mod_pct = report["moderate_pct"]
    risky_pct = report["risky_pct"]
    env_pct = report["env_error_pct_on_downtiered"]
    model_pct = report["model_error_pct_on_downtiered"]
    retry_pct = report["retry_pct_on_downtiered"]
    quality = report["avg_quality_score"]
    click.echo(f"quality-routing: {n} sessions | {total_down:,} downtiered turns | " f"quality score {quality:.3f}")
    click.echo(f"  risk split: safe={safe_pct:.1f}%  moderate={mod_pct:.1f}%  risky={risky_pct:.1f}%")
    click.echo(f"  errors: env={env_pct:.1f}% (excluded)  model={model_pct:.1f}%  retries={retry_pct:.1f}%")
    click.echo(f"saved report: {out_path}")


@benchmark_group.command("quality-compact")
@click.option(
    "--corpus",
    "corpus_dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory containing claude/*.jsonl session exports.",
)
@click.option("--max-sessions", default=None, type=int, help="Cap sessions processed.")
@click.pass_context
def benchmark_quality_compact(
    ctx: click.Context,
    corpus_dir: Path | None,
    max_sessions: int | None,
) -> None:
    """Compact QUALITY benchmark: does context survive compaction intact?

    For each real compaction event measures:
      - error rate drift (pre vs post compact)
      - extra re-reads post compact (proxy for lost context)
      - session continuation rate
      - composite retention score (0-1)
    """
    from benchmarks.swe.compact_quality_bench import run_compact_quality_bench

    root: Path = ctx.obj["root"]
    if corpus_dir is None:
        corpus_dir = root.parent / "exports"
    if not corpus_dir.exists():
        raise click.ClickException(f"corpus not found: {corpus_dir}")

    report = run_compact_quality_bench(corpus_dir, max_sessions=max_sessions)

    out_dir = root / "benchmarks" / "savings"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "compact_quality_latest.json"
    out_path.write_text(json.dumps(report, indent=2))

    n = report["sessions_benchmarked"]
    n_events = report["total_compaction_events"]
    retention = report["avg_retention_score"]
    drift = report["avg_error_drift"]
    rr = report["avg_extra_read_rate"]
    cont = report["sessions_continued_pct"]
    click.echo(f"quality-compact: {n} sessions | {n_events} compaction events | " f"retention score {retention:.3f}")
    click.echo(f"  error drift: {drift:+.3f}  extra re-reads: {rr:.3f}  continuation: {cont:.1f}%")
    click.echo(f"saved report: {out_path}")


@benchmark_group.command("replay-routing")
@click.option(
    "--corpus",
    "corpus_dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory containing claude/*.jsonl session exports.",
)
@click.option(
    "--max-sessions",
    default=10,
    show_default=True,
    type=int,
    help="Max sessions to replay (cost control).",
)
@click.option(
    "--max-turns",
    default=5,
    show_default=True,
    type=int,
    help="Max haiku calls per session (cost control). 0 = unlimited.",
)
@click.option(
    "--context-lines",
    default=30,
    show_default=True,
    type=int,
    help="Recent context lines sent to haiku per call.",
)
@click.option(
    "--haiku-model",
    default="claude-haiku-4-5",
    show_default=True,
    help="Haiku model alias for --model flag.",
)
@click.option(
    "--delay",
    default=0.5,
    show_default=True,
    type=float,
    help="Seconds between CLI calls (rate limiting).",
)
@click.option("--verbose", is_flag=True, default=False, help="Print each turn result as it completes.")
@click.pass_context
def benchmark_replay_routing(
    ctx: click.Context,
    corpus_dir: Path | None,
    max_sessions: int,
    max_turns: int,
    context_lines: int,
    haiku_model: str,
    delay: float,
    verbose: bool,
) -> None:
    """Routing REPLAY benchmark: actually call haiku on downtiered turns.

    True counterfactual - uses the claude CLI (no API key required).
    Reconstructs session context as text, asks haiku what tool it would call
    next, and compares its choice to what sonnet actually did.

    Estimated cost: ~$0.01-0.03 per turn replayed (haiku via Claude Code auth).

    Quality labels per turn:
      match        - same tool, similar input (similarity >= 0.7)
      partial      - same tool, somewhat different input (0.3-0.7)
      diverge      - same tool, very different input (< 0.3)
      tool_mismatch - haiku chose a different tool entirely
      parse_error  - haiku responded but JSON could not be parsed
    """
    from benchmarks.swe.routing_replay_bench import run_routing_replay_bench

    root: Path = ctx.obj["root"]
    if corpus_dir is None:
        corpus_dir = root.parent / "exports"
    if not corpus_dir.exists():
        raise click.ClickException(f"corpus not found: {corpus_dir}")

    max_t = max_turns if max_turns > 0 else None
    click.echo(
        f"Replaying with {haiku_model} (via claude CLI) | "
        f"up to {max_sessions} sessions x {max_t or 'all'} turns each | "
        f"context={context_lines} lines"
    )

    report = run_routing_replay_bench(
        corpus_dir,
        max_sessions=max_sessions,
        max_turns_per_session=max_t,
        context_lines=context_lines,
        haiku_model=haiku_model,
        rate_limit_delay=delay,
        verbose=verbose,
    )

    out_dir = root / "benchmarks" / "savings"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "routing_replay_latest.json"
    out_path.write_text(json.dumps(report, indent=2))

    n = report["sessions_benchmarked"]
    total = report["total_turns_replayed"]
    match = report["tool_match_rate"]
    sim = report["avg_input_similarity"]
    ratio = report["avg_output_token_ratio"]
    cost = report["total_haiku_cost_usd"]
    labels = report["quality_label_counts"]
    parse_errs = sum(1 for r in report.get("sessions", []) for t in r.get("turns", []) if t.get("parse_error"))

    click.echo(f"replay-routing: {n} sessions | {total} turns replayed | " f"tool match {match:.1%} | cost ${cost:.4f}")
    click.echo(f"  avg input similarity (matched turns): {sim:.3f}")
    click.echo(f"  avg output token ratio: {ratio:.3f} (haiku/sonnet)")
    click.echo(f"  quality: {json.dumps(labels)}")
    if parse_errs:
        click.echo(f"  parse errors: {parse_errs}", err=True)
    click.echo(f"saved report: {out_path}")


@benchmark_group.command("compare")
@click.option(
    "--input",
    "inputs",
    multiple=True,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Benchmark report JSON input. Provide at least two.",
)
def benchmark_compare(inputs: tuple[Path, ...]) -> None:
    """Compare two or more runtime benchmark reports."""
    from atelier.infra.runtime.benchmarking import compare_runtime_reports

    if len(inputs) < 2:
        raise click.ClickException("benchmark compare requires at least two --input reports")
    comparison = compare_runtime_reports(list(inputs))
    _emit(comparison, as_json=True)


@benchmark_group.command("report")
@click.option(
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Benchmark report JSON input.",
)
@click.option("--json", "as_json", is_flag=True)
def benchmark_report(input_path: Path, as_json: bool) -> None:
    """Render one runtime benchmark report."""
    from atelier.infra.runtime.benchmarking import load_runtime_report, render_runtime_report

    report = load_runtime_report(input_path)
    if as_json:
        _emit(report, as_json=True)
        return
    click.echo(render_runtime_report(report))


@benchmark_group.command("export")
@click.option(
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Benchmark report JSON input.",
)
@click.option("--output", "output_path", required=True, type=click.Path(path_type=Path))
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "markdown", "csv"]),
    default="json",
    show_default=True,
)
def benchmark_export(input_path: Path, output_path: Path, output_format: str) -> None:
    """Export a runtime benchmark report."""
    from atelier.infra.runtime.benchmarking import export_runtime_report, load_runtime_report

    report = load_runtime_report(input_path)
    exported = export_runtime_report(report, output_path=output_path, output_format=output_format)
    _emit({"output": str(exported), "format": output_format}, as_json=True)


@benchmark_group.command("core")
@click.option(
    "--prompt",
    "prompts",
    multiple=True,
    help="Prompts to benchmark (repeat). Defaults to built-in runtime tasks.",
)
@click.option("--model", default="claude-sonnet-4.6", show_default=True)
@click.option("--rounds", default=3, show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def benchmark_core(
    ctx: click.Context,
    prompts: tuple[str, ...],
    model: str,
    rounds: int,
    as_json: bool,
) -> None:
    """Phase T3: benchmark core runtime behavior."""
    payload = _run_benchmark_core(root=ctx.obj["root"], prompts=prompts, model=model, rounds=rounds)
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo("core benchmark complete")
    click.echo(f"tasks: {len(payload['report'].get('tasks', []))}")


@benchmark_group.command("hosts")
@click.option("--workspace", default=None, help="Optional workspace path passed to verify scripts.")
@click.option("--json", "as_json", is_flag=True)
def benchmark_hosts(workspace: str | None, as_json: bool) -> None:
    """Phase T3: benchmark/verify host integration readiness."""
    payload = _run_benchmark_hosts(workspace=workspace)
    if as_json:
        _emit(payload, as_json=True)
    else:
        click.echo(payload["output"])
    if payload["exit_code"] != 0:
        raise click.ClickException("host benchmark/verification failed")


@benchmark_group.command("runtime")
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional JSON output path.",
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def bench_runtime(ctx: click.Context, output_path: Path | None, as_json: bool) -> None:
    """Emit runtime capability efficiency metrics."""
    rt = _core_runtime(ctx.obj["root"])
    payload = rt.benchmark_runtime_metrics()
    if output_path is not None:
        rt.export_benchmark_runtime(output_path)
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@benchmark_group.command("packs")
@click.option("--host", default="codex", show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def benchmark_packs(ctx: click.Context, host: str, as_json: bool) -> None:
    """Phase T3: benchmark official/installed packs."""
    payload = _run_benchmark_packs(root=ctx.obj["root"], host=host)
    if as_json:
        _emit(payload, as_json=True)
        return
    click.echo(f"domain benchmark complete: {payload['domains_benchmarked']}/{payload['domains_total']} domains")
    if payload["failures"]:
        click.echo("failures:")
        for item in payload["failures"]:
            click.echo(f"  - {item.get('bundle_id', item.get('pack_id', '?'))}: {item['error']}")


@benchmark_group.command("full")
@click.option(
    "--prompt",
    "prompts",
    multiple=True,
    help="Prompts to benchmark for the core suite (repeat).",
)
@click.option("--model", default="claude-sonnet-4.6", show_default=True)
@click.option("--rounds", default=3, show_default=True)
@click.option("--host", default="codex", show_default=True)
@click.option("--workspace", default=None, help="Optional workspace path passed to host verify scripts.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def benchmark_full(
    ctx: click.Context,
    prompts: tuple[str, ...],
    model: str,
    rounds: int,
    host: str,
    workspace: str | None,
    as_json: bool,
) -> None:
    """Phase T3: run core + hosts + packs benchmark suite."""
    core_payload = _run_benchmark_core(root=ctx.obj["root"], prompts=prompts, model=model, rounds=rounds)
    hosts_payload = _run_benchmark_hosts(workspace=workspace)
    packs_payload = _run_benchmark_packs(root=ctx.obj["root"], host=host)

    payload = {
        "suite": "full",
        "core": core_payload,
        "hosts": hosts_payload,
        "packs": packs_payload,
        "status": ("pass" if hosts_payload["exit_code"] == 0 and not packs_payload["failures"] else "warn"),
    }

    if as_json:
        _emit(payload, as_json=True)
    else:
        click.echo("full benchmark suite complete")
        click.echo(f"core tasks: {len(core_payload['report'].get('tasks', []))}")
        click.echo(f"host verification status: {hosts_payload['status']}")
        click.echo(f"domain coverage: {packs_payload['domains_benchmarked']}/{packs_payload['domains_total']}")

    if hosts_payload["exit_code"] != 0:
        raise click.ClickException("full benchmark failed in host verification")


@benchmark_group.command("publish")
@click.option(
    "--since",
    default="7d",
    show_default=True,
    help="Coverage window label included in the report (informational only).",
)
@click.option(
    "--output",
    "output_dir",
    default="reports",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Parent directory for published reports (reports/YYYY-Www/).",
)
@click.option(
    "--corpus",
    "corpus_arg",
    default="",
    help="Optional corpus label for the Methodology section.",
)
@click.option("--dry-run", "dry_run", is_flag=True, help="Print what would be written; do not write.")
@click.pass_context
def benchmark_publish(
    ctx: click.Context,
    since: str,
    output_dir: Path,
    corpus_arg: str,
    dry_run: bool,
) -> None:
    """Render latest benchmark results into a publishable weekly report.

    Reads cached JSON files from {root}/benchmarks/savings/ and writes
    reports/YYYY-Www/benchmark.{md,json}. Computes Δ vs the prior week's
    report if available.
    """
    from atelier.infra.benchmarks.publisher import publish

    root: Path = ctx.obj["root"]

    # Resolve output_dir relative to cwd (not ~/.atelier)
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir

    mode_label = " [dry-run]" if dry_run else ""
    click.echo(f"Building benchmark report{mode_label}…")

    report_dir = publish(
        root=root,
        output_dir=output_dir,
        since=since,
        corpus_arg=corpus_arg,
        dry_run=dry_run,
    )

    if dry_run:
        click.echo("Dry-run complete - no files written.")
    else:
        assert report_dir is not None
        click.echo(f"Report written -> {report_dir}")
        click.echo(f"  {report_dir / 'benchmark.md'}")
        click.echo(f"  {report_dir / 'benchmark.json'}")
        click.echo(f"  {output_dir / 'index.json'} (updated)")


def _register_swe_benchmark_group() -> None:
    try:
        from benchmarks.swe.run_swe_bench import swe as swe_benchmark_group
    except ModuleNotFoundError:
        # Keep CLI startup resilient when benchmark modules are not present
        # in the runtime environment (e.g. partial installs/services).
        return

    benchmark_group.add_command(swe_benchmark_group)


@click.group("bench")
def bench_group() -> None:
    """A/B benchmark suites: run, publish, and compare Atelier-on vs off."""


@bench_group.command("publish")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Output blog post directory (e.g. docs-site/blog/my-bench/).",
)
def bench_publish_cmd(run_dir: Path, out_dir: Path) -> None:
    """Assemble a Docusaurus blog post from an A/B run directory (PUB-01)."""
    from benchmarks.ab.publish import assemble_post

    assemble_post(run_dir, out_dir)


@bench_group.command("run")
@click.option("--suite", default="terminalbench", show_default=True, help="Benchmark suite name.")
@click.option("--quick", is_flag=True, help="Quick mode: 1 task, N=2 (CLI-01).")
@click.option("--full", is_flag=True, help="Full mode: 10 tasks, N=5 (CLI-02).")
@click.option("--n", "n_reps", default=3, show_default=True, help="Repetitions per cell.")
@click.option("--tasks", "n_tasks", default=5, show_default=True, help="Number of tasks.")
@click.option("--models", "model", default="claude-sonnet-4-5", show_default=True)
@click.option("--modes", default="on,off", show_default=True, help="Comma-separated bench modes.")
@click.option("--seed", default=42, show_default=True)
@click.option("--yes", "confirmed", is_flag=True, help="Skip cost confirmation (CLI-03).")
@click.option("--no-cost-cap", is_flag=True, help="Remove $50 hard-stop (CLI-03).")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=None)
@click.option("--pr", "pr_url", default=None, help="GitHub PR URL for replay benchmarks (PR-01).")
def bench_run_cmd(
    suite: str,
    quick: bool,
    full: bool,
    n_reps: int,
    n_tasks: int,
    model: str,
    modes: str,
    seed: int,
    confirmed: bool,
    no_cost_cap: bool,
    out_dir: Path | None,
    pr_url: str | None,
) -> None:
    """Run an A/B benchmark suite comparing Atelier-on vs off (CLI-01 through CLI-06).

    Results are stored under ~/.atelier/bench/<run-id>/ by default (CLI-05).
    Use --pr <github-url> to replay a GitHub PR and score diff quality (PR-01).
    """
    if pr_url:
        import datetime

        from benchmarks.ab.bench_run import default_run_dir
        from benchmarks.ab.pr_replay import run_pr_replay

        run_id = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        resolved_out = out_dir if out_dir is not None else default_run_dir(run_id)
        resolved_out.mkdir(parents=True, exist_ok=True)
        mode_list = [m.strip() for m in modes.split(",")]
        run_pr_replay(pr_url, resolved_out, modes=mode_list)
        return

    # Build a Click context and invoke
    import sys

    from benchmarks.ab.bench_run import main as _bench_run_main

    argv = [
        "run",
        "--suite",
        suite,
        "--n",
        str(n_reps),
        "--tasks",
        str(n_tasks),
        "--models",
        model,
        "--modes",
        modes,
        "--seed",
        str(seed),
    ]
    if quick:
        argv.append("--quick")
    if full:
        argv.append("--full")
    if confirmed:
        argv.append("--yes")
    if no_cost_cap:
        argv.append("--no-cost-cap")
    if out_dir is not None:
        argv += ["--out", str(out_dir)]

    sys.argv = argv
    _bench_run_main(standalone_mode=False)


# Attach the optional SWE benchmark group after ``benchmark_group`` is fully
# defined, mirroring the original module-bottom call in ``app.py`` so the SWE
# group is registered after benchmark_group and stays resilient to absence.
_register_swe_benchmark_group()
