"""assemble a Docusaurus blog post from an A/B run directory.

PUB-01: assembles index.md, plots/, transcripts/, reproduce.sh
PUB-02: reproduce.sh contains exact CLI command + commit SHA
PUB-03: index.md has valid Docusaurus frontmatter + <!-- truncate -->
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click


def _git_commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _reproduce_sh(config: dict[str, Any], commit_sha: str) -> str:
    suite = config.get("suite", "terminalbench")
    tasks: list[str] = config.get("tasks", [])
    n = config.get("n_reps", 3)
    models: list[str] = config.get("model", ["claude-sonnet-4-5"])
    modes: list[str] = config.get("modes", ["on", "off"])
    seed: int = config.get("seed", 42)

    task_args = " ".join(f"--tasks {t}" for t in tasks)
    model_args = " ".join(f"--models {m}" for m in models)
    mode_args = " ".join(f"--modes {m}" for m in modes)

    return (
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "# Reproduce this benchmark from a clean clone",
                f"# Commit: {commit_sha}",
                "set -euo pipefail",
                "",
                "# Install the benchmarks package",
                "cd benchmarks && uv sync --extra dev && cd ..",
                "",
                "# Run the A/B suite (results stored under ~/.atelier/bench/)",
                (f"atelier bench run --suite {suite} {task_args}" f" --n {n} {model_args} {mode_args} --seed {seed}"),
            ]
        )
        + "\n"
    )


def _docusaurus_frontmatter(config: dict[str, Any], summary: dict[str, Any], commit_sha: str) -> str:
    suite = config.get("suite", "terminalbench")
    n_tasks = len(config.get("tasks", []))
    run_date = summary.get("created_at", config.get("started_at", datetime.now(UTC).isoformat()))[:10]
    title = f"Benchmark: {suite} ({n_tasks} tasks) — {run_date}"
    description = (
        f"A/B benchmark comparing Atelier-on vs Atelier-off on {n_tasks} {suite} tasks." f" Commit {commit_sha}."
    )
    tags = ["benchmark", "a-b-test", suite]
    tags_yaml = "[" + ", ".join(f'"{t}"' for t in tags) + "]"
    return "\n".join(
        [
            "---",
            f'title: "{title}"',
            f'date: "{run_date}"',
            'authors: ["atelier-bench"]',
            f"tags: {tags_yaml}",
            f'description: "{description}"',
            "custom_edit_url: null",
            "---",
        ]
    )


def assemble_post(run_dir: Path, out_dir: Path, commit_sha: str | None = None) -> None:
    """Assemble a Docusaurus blog post from an A/B run directory (PUB-01)."""
    config_path = run_dir / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"config.json not found in {run_dir}")
    config = json.loads(config_path.read_text())

    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}

    sha = commit_sha if commit_sha is not None else _git_commit_sha()
    out_dir.mkdir(parents=True, exist_ok=True)

    # copy plots/ (PUB-01)
    plots_src = run_dir / "plots"
    if plots_src.exists():
        plots_dst = out_dir / "plots"
        if plots_dst.exists():
            shutil.rmtree(plots_dst)
        shutil.copytree(plots_src, plots_dst)

    # copy raw/ as transcripts/ (PUB-01)
    raw_src = run_dir / "raw"
    if raw_src.exists():
        transcripts_dst = out_dir / "transcripts"
        if transcripts_dst.exists():
            shutil.rmtree(transcripts_dst)
        shutil.copytree(raw_src, transcripts_dst)

    # build index.md = frontmatter + truncate marker + report body (PUB-03)
    report_src = run_dir / "report.md"
    frontmatter = _docusaurus_frontmatter(config, summary, sha)
    if report_src.exists():
        body = report_src.read_text()
        # insert <!-- truncate --> after the first blank line following a heading
        lines = body.split("\n")
        insert_at = next(
            (i for i, ln in enumerate(lines[1:], 1) if ln.strip() == ""),
            min(8, len(lines)),
        )
        lines.insert(insert_at + 1, "\n<!-- truncate -->\n")
        body = "\n".join(lines)
    else:
        body = "*(no report.md generated yet — run `atelier bench run` first)*"

    (out_dir / "index.md").write_text(f"{frontmatter}\n\n{body}")

    # write reproduce.sh (PUB-02)
    sh_path = out_dir / "reproduce.sh"
    sh_path.write_text(_reproduce_sh(config, sha))
    sh_path.chmod(0o755)

    click.echo(f"Published → {out_dir}")
    click.echo(f"  index.md       ({(out_dir / 'index.md').stat().st_size} bytes)")
    if (out_dir / "plots").exists():
        click.echo(f"  plots/         ({len(list((out_dir / 'plots').iterdir()))} files)")
    if (out_dir / "transcripts").exists():
        click.echo(f"  transcripts/   ({len(list((out_dir / 'transcripts').iterdir()))} files)")
    click.echo("  reproduce.sh")


@click.command("publish")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Output blog post directory (e.g. docs-site/blog/my-bench/).",
)
def main(run_dir: Path, out_dir: Path) -> None:
    """Assemble a Docusaurus blog post from an A/B run directory."""
    assemble_post(run_dir, out_dir)


if __name__ == "__main__":
    main()
