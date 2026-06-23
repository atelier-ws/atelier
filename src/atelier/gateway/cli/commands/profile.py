"""``atelier profile`` -- MCP tool latency profiling with drift detection.

Bare ``atelier profile`` runs the profile and prints per-tool drift vs the last
recorded run (without recording). ``atelier profile append`` also records the
run into the history file. ``atelier profile show`` prints the recorded history.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from atelier.gateway.cli.commands._mcp_profile import (
    append_history,
    default_history_path,
    load_last_run,
    render_drift,
    run_profile,
    summarize_history,
)


def _profile_options(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn = click.option(
        "--repo",
        "repo",
        type=click.Path(file_okay=False, path_type=Path),
        default=Path("."),
        help="Repo to profile (default: cwd).",
    )(fn)
    fn = click.option("--runs", "runs", default=7, show_default=True, help="Warm samples per tool (median reported).")(
        fn
    )
    fn = click.option("--warmup", "warmup", default=2, show_default=True, help="Warm-up calls before sampling.")(fn)
    fn = click.option(
        "--threshold", "threshold", default=25.0, show_default=True, help="Drift %% that flags a regression."
    )(fn)
    fn = click.option("--no-edit", "no_edit", is_flag=True, help="Skip the (mutating) edit probe.")(fn)
    fn = click.option("--json", "as_json", is_flag=True, help="Emit the run record as JSON instead of the table.")(fn)
    return fn


def _profile_and_render(
    *, repo: Path, runs: int, warmup: int, threshold: float, no_edit: bool, as_json: bool, store: bool
) -> bool:
    repo = repo.resolve()
    history = default_history_path(repo)
    current = run_profile(repo, warmup=warmup, runs=runs, include_edit=not no_edit)
    prev = load_last_run(history, str(repo))
    text, regressed = render_drift(current, prev, threshold)
    if as_json:
        click.echo(json.dumps(current, indent=2, sort_keys=True))
    else:
        click.echo(text)
    if store:
        append_history(history, current)
        if not as_json:
            click.echo(f"\nappended to {history}")
    return regressed


@click.group("profile", invoke_without_command=True)
@click.pass_context
def profile_group(ctx: click.Context) -> None:
    """Profile MCP tool latency and track drift across runs."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(profile_run)


@profile_group.command("run")
@_profile_options
@click.option(
    "--fail-on-regression",
    "fail_on_regression",
    is_flag=True,
    help="Exit non-zero if any tool regresses past --threshold.",
)
def profile_run(
    repo: Path, runs: int, warmup: int, threshold: float, no_edit: bool, as_json: bool, fail_on_regression: bool
) -> None:
    """Profile and print drift vs the last recorded run (does NOT record)."""
    regressed = _profile_and_render(
        repo=repo, runs=runs, warmup=warmup, threshold=threshold, no_edit=no_edit, as_json=as_json, store=False
    )
    if fail_on_regression and regressed:
        raise SystemExit(1)


@profile_group.command("append")
@_profile_options
def profile_append(repo: Path, runs: int, warmup: int, threshold: float, no_edit: bool, as_json: bool) -> None:
    """Profile, print drift, and append this run to the history file."""
    _profile_and_render(
        repo=repo, runs=runs, warmup=warmup, threshold=threshold, no_edit=no_edit, as_json=as_json, store=True
    )


@profile_group.command("show")
@click.option(
    "--repo", "repo", type=click.Path(file_okay=False, path_type=Path), default=Path("."), help="Repo (default: cwd)."
)
@click.option("--last", "last", default=10, show_default=True, help="How many recent runs to show.")
def profile_show(repo: Path, last: int) -> None:
    """Print the recorded latency history (warm_ms per tool across runs)."""
    repo = repo.resolve()
    click.echo(summarize_history(default_history_path(repo), str(repo), last))
