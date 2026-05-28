"""atelier bench run — user-facing A/B benchmark CLI (CLI-01 through CLI-06).

Usage:
    atelier bench run --suite terminalbench --quick          # CLI-01
    atelier bench run --suite terminalbench --full           # CLI-02
    atelier bench run --suite terminalbench --n 3 --yes      # skip cost gate
    atelier bench run --suite terminalbench --no-cost-cap    # remove $50 hard-stop
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import Any

import click

# --------------------------------------------------------------------------- #
# Cost estimation (CLI-03)                                                     #
# --------------------------------------------------------------------------- #

# Rough per-token price in USD (input, output) for supported models
_MODEL_PRICE: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-sonnet-4.6": (3.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-haiku-3-5": (0.25 / 1_000_000, 1.25 / 1_000_000),
}
_DEFAULT_PRICE = (3.0 / 1_000_000, 15.0 / 1_000_000)

# Estimated tokens per trial (pessimistic upper bound for TerminalBench)
_EST_INPUT_TOKENS = 12_000
_EST_OUTPUT_TOKENS = 2_000

HARD_STOP_USD = 50.0


def estimate_cost(n_trials: int, model: str) -> float:
    """Estimate total USD cost for n_trials using the given model (CLI-03)."""
    in_price, out_price = _MODEL_PRICE.get(model, _DEFAULT_PRICE)
    return n_trials * (_EST_INPUT_TOKENS * in_price + _EST_OUTPUT_TOKENS * out_price)


# --------------------------------------------------------------------------- #
# Run-dir resolution (CLI-05)                                                  #
# --------------------------------------------------------------------------- #


def default_run_dir(run_id: str) -> Path:
    """Resolve the canonical run directory: ~/.atelier/bench/<run-id>/ (CLI-05)."""
    atelier_root = Path(os.environ.get("ATELIER_ROOT", Path.home() / ".atelier"))
    return atelier_root / "bench" / run_id


# --------------------------------------------------------------------------- #
# Rich progress printer (CLI-04)                                               #
# --------------------------------------------------------------------------- #


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401

        return True
    except ImportError:
        return False


def run_with_progress(
    schedule: list[tuple[str, str, int]],
    run_cell_fn: Any,
) -> None:
    """Execute schedule with Rich progress display (CLI-04)."""
    if _rich_available():
        from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("Running trials", total=len(schedule))
            for task_id, mode, rep in schedule:
                progress.update(task, description=f"[cyan]{task_id}[/] [{mode}] rep{rep}")
                run_cell_fn(task_id, mode, rep)
                progress.advance(task)
    else:
        # Fallback: plain stdout (no Rich)
        for i, (task_id, mode, rep) in enumerate(schedule, 1):
            click.echo(f"[{i}/{len(schedule)}] {task_id} [{mode}] rep{rep}", err=True)
            run_cell_fn(task_id, mode, rep)


# --------------------------------------------------------------------------- #
# Comparison table (CLI-04)                                                    #
# --------------------------------------------------------------------------- #


def print_comparison_table(summary: dict[str, Any]) -> None:
    """Print a terminal comparison table from summary.json (CLI-04)."""
    cells = summary.get("cells", {})
    if not cells:
        click.echo("No results to display.")
        return

    if _rich_available():
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="A/B Comparison: Atelier-on vs off", show_lines=True)
        table.add_column("Task", style="bold")
        table.add_column("Mode", style="cyan")
        table.add_column("Pass Rate", justify="right")
        table.add_column("Cost (USD)", justify="right")
        table.add_column("Latency (ms)", justify="right")

        for cell_key, cell in cells.items():
            task_id, mode = cell_key.rsplit("__", 1)
            pass_rate = f"{cell.get('pass_rate', 0):.1%}" if "pass_rate" in cell else "n/a"
            cost = f"${cell.get('cost_usd_mean', 0):.4f}" if "cost_usd_mean" in cell else "n/a"
            latency = f"{cell.get('latency_ms_mean', 0):.0f}" if "latency_ms_mean" in cell else "n/a"
            table.add_row(task_id, mode, pass_rate, cost, latency)

        console.print(table)
    else:
        # Fallback plain table
        click.echo("\n=== A/B Results ===")
        click.echo(f"{'Task':<30} {'Mode':<6} {'Pass':>8} {'Cost $':>10} {'Latency':>12}")
        click.echo("-" * 70)
        for cell_key, cell in cells.items():
            task_id, mode = cell_key.rsplit("__", 1)
            pass_rate = f"{cell.get('pass_rate', 0):.1%}" if "pass_rate" in cell else "n/a"
            cost = f"${cell.get('cost_usd_mean', 0):.4f}" if "cost_usd_mean" in cell else "n/a"
            latency = f"{cell.get('latency_ms_mean', 0):.0f}" if "latency_ms_mean" in cell else "n/a"
            click.echo(f"{task_id:<30} {mode:<6} {pass_rate:>8} {cost:>10} {latency:>12}")


# --------------------------------------------------------------------------- #
# CLI entry point (CLI-01 through CLI-06)                                      #
# --------------------------------------------------------------------------- #


@click.command("run")
@click.option("--suite", default="terminalbench", show_default=True, help="Benchmark suite name.")
@click.option("--quick", is_flag=True, help="Quick mode: 1 task, N=2, both modes (CLI-01).")
@click.option("--full", is_flag=True, help="Full mode: 10 tasks, N=5, both modes (CLI-02).")
@click.option("--n", "n_reps", default=3, show_default=True, help="Repetitions per cell.")
@click.option("--tasks", "n_tasks", default=5, show_default=True, help="Number of tasks from suite.")
@click.option(
    "--models",
    "model",
    default="claude-sonnet-4-5",
    show_default=True,
    help="Claude model slug.",
)
@click.option("--modes", default="on,off", show_default=True, help="Comma-separated bench modes.")
@click.option("--seed", default=42, show_default=True, help="Random seed.")
@click.option("--yes", "confirmed", is_flag=True, help="Skip cost confirmation prompt (CLI-03).")
@click.option("--no-cost-cap", is_flag=True, help="Remove $50 hard-stop (CLI-03).")
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override output path (default: ~/.atelier/bench/<run-id>/).",
)
def main(
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
) -> None:
    """Run an A/B benchmark suite comparing Atelier-on vs off (CLI-01 through CLI-06).

    Results are stored under ~/.atelier/bench/<run-id>/ by default (CLI-05).
    Use `atelier bench publish` to generate a blog post from the results.

    Examples:

        atelier bench run --suite terminalbench --quick --yes

        atelier bench run --suite terminalbench --full --models claude-haiku-3-5

        atelier bench run --suite terminalbench --n 5 --tasks 8 --seed 99
    """
    # Apply --quick / --full presets (CLI-01, CLI-02)
    if quick and full:
        raise click.UsageError("--quick and --full are mutually exclusive.")
    if quick:
        n_tasks, n_reps = 1, 2
    elif full:
        n_tasks, n_reps = 10, 5

    mode_list = [m.strip() for m in modes.split(",")]

    # Load task IDs from suite
    from ab.runner import load_suite_tasks

    task_ids = load_suite_tasks(suite, n_tasks)
    n_trials = len(task_ids) * n_reps * len(mode_list)

    # Cost gate (CLI-03)
    cost_est = estimate_cost(n_trials, model)
    click.echo(
        f"  Suite: {suite}  |  Tasks: {len(task_ids)}  |  Reps: {n_reps}"
        f"  |  Modes: {mode_list}  |  Trials: {n_trials}"
    )
    click.echo(f"  Estimated cost: ${cost_est:.2f}  (model: {model})")

    if not no_cost_cap and cost_est > HARD_STOP_USD:
        raise click.ClickException(
            f"Estimated cost ${cost_est:.2f} exceeds $50 hard-stop. " "Use --no-cost-cap to override."
        )

    if not confirmed:
        click.confirm(f"Proceed with estimated cost ~${cost_est:.2f}?", abort=True)

    # Resolve output directory (CLI-05)
    run_id = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    resolved_out = out_dir if out_dir is not None else default_run_dir(run_id)
    resolved_out.mkdir(parents=True, exist_ok=True)
    click.echo(f"  Run directory: {resolved_out}")

    # Delegate to the low-level runner
    import subprocess

    cmd = [
        sys.executable,
        "-m",
        "ab.runner",
        "--suite",
        suite,
        "--tasks",
        str(n_tasks),
        "--n",
        str(n_reps),
        "--models",
        model,
        "--modes",
        modes,
        "--out",
        str(resolved_out),
        "--seed",
        str(seed),
    ]
    click.echo(f"  Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise click.ClickException(f"Runner exited with code {result.returncode}")

    # Load summary and print comparison table (CLI-04)
    summary_path = resolved_out / "summary.json"
    if summary_path.exists():
        import json

        summary = json.loads(summary_path.read_text())
        print_comparison_table(summary)

    click.echo(f"\nResults → {resolved_out}")
    click.echo("Run `atelier bench publish` to generate a blog post.")


if __name__ == "__main__":
    main()
