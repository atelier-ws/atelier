from __future__ import annotations

import json
from pathlib import Path

import click

from atelier.core.capabilities.benchmark_solver import run_benchmark_solver, write_solver_artifacts


@click.command("solver")
@click.option("--task-prompt", type=str, default=None, help="Inline benchmark task prompt.")
@click.option(
    "--task-file",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to a file containing the benchmark task prompt.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "stream-json"]),
    default="text",
    show_default=True,
)
@click.option("--out", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option(
    "--route-mode",
    type=click.Choice(["native", "auto", "explicit"]),
    default="auto",
    show_default=True,
    help="Owned route selection mode for benchmark solver execution.",
)
@click.option("--provider", type=str, default=None, help="Explicit provider/vendor when route-mode=explicit.")
@click.option("--model", type=str, default=None, help="Override the owned solver model.")
@click.option(
    "--runner",
    type=str,
    default=None,
    help="Optional runner profile override for the selected route.",
)
def benchmark_solver_cmd(
    task_prompt: str | None,
    task_file: Path | None,
    output_format: str,
    out: Path | None,
    route_mode: str,
    provider: str | None,
    model: str | None,
    runner: str | None,
) -> None:
    """Run the owned benchmark solver headlessly."""
    prompt = _load_task_prompt(task_prompt=task_prompt, task_file=task_file)
    run = run_benchmark_solver(
        prompt,
        repo_root=Path.cwd().resolve(),
        route_mode=route_mode,
        provider=provider,
        model=model,
        runner=runner,
    )
    artifacts = write_solver_artifacts(run, out or Path.cwd().resolve() / ".atelier-benchmark-solver")
    payload = dict(run.to_dict())
    payload["artifact_paths"] = {
        "run_json": str(artifacts.run_json_path),
        "stream_jsonl": str(artifacts.stream_jsonl_path),
    }

    if output_format == "json":
        click.echo(json.dumps(payload))
        return
    if output_format == "stream-json":
        for event in run.events:
            click.echo(json.dumps(event.to_dict()))
        return

    click.echo(f"run_id: {run.run_id}")
    click.echo(f"status: {run.status}")
    click.echo(f"attempts: {len(run.attempts)}")
    click.echo(f"run_json: {artifacts.run_json_path}")
    click.echo(f"stream_jsonl: {artifacts.stream_jsonl_path}")


def _load_task_prompt(*, task_prompt: str | None, task_file: Path | None) -> str:
    if task_prompt and task_file:
        raise click.ClickException("choose either --task-prompt or --task-file")
    if task_file is not None:
        return task_file.read_text(encoding="utf-8")
    if task_prompt:
        return task_prompt
    raise click.ClickException("one of --task-prompt or --task-file is required")


__all__ = ["benchmark_solver_cmd"]
