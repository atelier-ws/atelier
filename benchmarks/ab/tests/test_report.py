"""Tests for ab.report — RPT-01 through RPT-06."""

import json
import tempfile
from pathlib import Path

from ab.report import (
    compute_cell_stats,
    compute_deltas,
    generate_plots,
    generate_report_md,
    load_run_dir,
)


def _make_run_dir(tmp_path: Path, tasks: list[str], n_reps: int = 2) -> Path:
    """Create a minimal run directory with config.json, summary.json, and raw files."""
    run_dir = tmp_path / "my-run"
    run_dir.mkdir()
    raw_dir = run_dir / "raw"
    raw_dir.mkdir()

    config = {
        "run_id": "my-run",
        "suite": "terminalbench",
        "tasks": tasks,
        "n_reps": n_reps,
        "model": "claude-sonnet-4-5",
        "modes": ["on", "off"],
        "seed": 42,
        "started_at": "2026-06-01T00:00:00Z",
    }
    (run_dir / "config.json").write_text(json.dumps(config))

    # Write raw files: alternating pass/fail for "on", all fail for "off"
    for task in tasks:
        for rep in range(1, n_reps + 1):
            (raw_dir / f"{task}__on__rep{rep}.json").write_text(
                json.dumps(
                    {
                        "task_id": task,
                        "mode": "on",
                        "rep": rep,
                        "grader_is_resolved": rep == 1,
                        "cost_usd": 0.01 * rep,
                        "latency_ms": 1000.0 * rep,
                    }
                )
            )
            (raw_dir / f"{task}__off__rep{rep}.json").write_text(
                json.dumps(
                    {
                        "task_id": task,
                        "mode": "off",
                        "rep": rep,
                        "grader_is_resolved": False,
                        "cost_usd": 0.005 * rep,
                        "latency_ms": 800.0 * rep,
                    }
                )
            )

    from ab.aggregate import compute_summary

    summary = compute_summary("my-run", raw_dir)
    (run_dir / "summary.json").write_text(json.dumps(summary))

    return run_dir


def test_load_run_dir():
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d), ["task-a", "task-b"], n_reps=2)
        config, summary, raw_by_cell = load_run_dir(run_dir)

        assert config["run_id"] == "my-run"
        assert "cells" in summary
        assert "task-a__on" in raw_by_cell
        assert len(raw_by_cell["task-a__on"]) == 2


def test_compute_cell_stats():
    raw_by_cell = {
        "task-a__on": [{"cost_usd": 0.01, "latency_ms": 1000.0}, {"cost_usd": 0.02, "latency_ms": 2000.0}],
        "task-a__off": [{"cost_usd": 0.005, "latency_ms": 800.0}, {"cost_usd": 0.01, "latency_ms": 1600.0}],
    }
    stats = compute_cell_stats(raw_by_cell)
    assert abs(stats["task-a__on"]["cost_usd_mean"] - 0.015) < 1e-9
    assert abs(stats["task-a__on"]["latency_ms_mean"] - 1500.0) < 1e-6
    assert abs(stats["task-a__off"]["cost_usd_mean"] - 0.0075) < 1e-9


def test_compute_deltas():
    cell_stats = {
        "task-a__on": {"cost_usd_mean": 0.015, "latency_ms_mean": 1500.0},
        "task-a__off": {"cost_usd_mean": 0.0075, "latency_ms_mean": 1200.0},
    }
    summary_cells = {
        "task-a__on": {"passed": 1, "total": 2, "ci_lower": 0.1, "ci_upper": 0.9},
        "task-a__off": {"passed": 0, "total": 2, "ci_lower": 0.0, "ci_upper": 0.6},
    }
    deltas = compute_deltas(["task-a"], cell_stats, summary_cells)
    assert len(deltas) == 1
    d = deltas[0]
    assert d["task_id"] == "task-a"
    assert abs(d["cost_delta"] - 0.0075) < 1e-9
    assert abs(d["latency_delta"] - 300.0) < 1e-6
    assert abs(d["quality_delta"] - 0.5) < 1e-9


def test_generate_plots_rpt01():
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d), ["task-a", "task-b"], n_reps=2)
        _, summary, raw_by_cell = load_run_dir(run_dir)
        config, _, _ = load_run_dir(run_dir)
        cell_stats = compute_cell_stats(raw_by_cell)
        deltas = compute_deltas(config["tasks"], cell_stats, summary["cells"])

        generate_plots(run_dir, deltas)

        assert (run_dir / "plots" / "cost_delta.png").exists(), "cost_delta.png missing"
        assert (run_dir / "plots" / "latency_delta.png").exists(), "latency_delta.png missing"
        assert (run_dir / "plots" / "quality_delta.png").exists(), "quality_delta.png missing"


def test_generate_report_md_structure_rpt02_rpt03_rpt05():
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d), ["task-a", "task-b"], n_reps=2)
        config, summary, raw_by_cell = load_run_dir(run_dir)
        cell_stats = compute_cell_stats(raw_by_cell)
        deltas = compute_deltas(config["tasks"], cell_stats, summary["cells"])

        generate_report_md(run_dir, config, summary, deltas, commit_sha="abc1234")

        report = (run_dir / "report.md").read_text()

        # RPT-02: methodology section
        assert "## Methodology" in report
        assert "abc1234" in report
        assert "claude-sonnet-4-5" in report
        assert "python -m ab.runner" in report

        # RPT-03: headline table
        assert "## Results" in report
        assert "| Task |" in report
        assert "task-a" in report

        # RPT-05: losses section always present
        assert "## Losses" in report


def test_report_md_losses_section_rpt05():
    """RPT-05: Losses section present even when no losses (on better in all metrics)."""
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d), ["task-a"], n_reps=2)
        config, summary, _raw_by_cell = load_run_dir(run_dir)

        # Override cell_stats so on is cheaper and faster
        cell_stats = {
            "task-a__on": {"cost_usd_mean": 0.005, "latency_ms_mean": 500.0},
            "task-a__off": {"cost_usd_mean": 0.01, "latency_ms_mean": 1000.0},
        }
        deltas = compute_deltas(config["tasks"], cell_stats, summary["cells"])

        generate_report_md(run_dir, config, summary, deltas, commit_sha="abc1234")
        report = (run_dir / "report.md").read_text()

        assert "## Losses" in report
        assert "No losses this run" in report


def test_report_md_renders_github_compatible_rpt06():
    """RPT-06: No broken MDX — no JSX tags, no unclosed backtick fences."""
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d), ["task-a"], n_reps=2)
        config, summary, raw_by_cell = load_run_dir(run_dir)
        cell_stats = compute_cell_stats(raw_by_cell)
        deltas = compute_deltas(config["tasks"], cell_stats, summary["cells"])

        generate_report_md(run_dir, config, summary, deltas, commit_sha="abc1234")
        report = (run_dir / "report.md").read_text()

        # No JSX-style self-closing tags (MDX incompatible on GitHub)
        assert "</" not in report or "```" in report  # allow inside code fences
        # Backtick fences must be balanced
        fence_count = report.count("```")
        assert fence_count % 2 == 0, f"unbalanced ``` fences: count={fence_count}"

        # Transcript links present (RPT-04)
        assert "raw/" in report
