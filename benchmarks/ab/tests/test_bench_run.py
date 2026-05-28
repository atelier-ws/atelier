"""Tests for ab.bench_run — CLI-01 through CLI-06."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ab.bench_run import default_run_dir, estimate_cost, main


def test_estimate_cost_scales_with_trials():
    """CLI-03: cost scales linearly with trial count."""
    cost1 = estimate_cost(1, "claude-sonnet-4-5")
    cost10 = estimate_cost(10, "claude-sonnet-4-5")
    assert cost10 == pytest.approx(cost1 * 10, rel=1e-6)


def test_estimate_cost_positive():
    assert estimate_cost(5, "claude-sonnet-4-5") > 0


def test_default_run_dir_uses_atelier_root():
    """CLI-05: results go under ~/.atelier/bench/<run-id>/."""
    with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"ATELIER_ROOT": d}):
        result = default_run_dir("my-run-123")
    assert result == Path(d) / "bench" / "my-run-123"


def test_default_run_dir_falls_back_to_home():
    """CLI-05: if ATELIER_ROOT not set, use ~/.atelier/bench/."""
    env = {k: v for k, v in os.environ.items() if k != "ATELIER_ROOT"}
    with patch.dict(os.environ, env, clear=True):
        result = default_run_dir("abc")
    assert result == Path.home() / ".atelier" / "bench" / "abc"


def test_quick_flag_sets_1_task_n2(monkeypatch):
    """CLI-01: --quick sets 1 task, N=2."""
    captured = {}

    def fake_run(cmd, check):
        # Extract --tasks and --n from cmd
        i_tasks = cmd.index("--tasks") + 1
        i_n = cmd.index("--n") + 1
        captured["tasks"] = cmd[i_tasks]
        captured["n"] = cmd[i_n]
        return type("R", (), {"returncode": 0})()

    runner = CliRunner()
    with runner.isolated_filesystem():
        out_dir = Path("out")
        with patch("subprocess.run", fake_run):
            result = runner.invoke(
                main,
                ["--suite", "terminalbench", "--quick", "--yes", "--out", str(out_dir)],
            )

    assert captured.get("tasks") == "1", f"expected 1 task, got {captured.get('tasks')}: {result.output}"
    assert captured.get("n") == "2", f"expected n=2, got {captured.get('n')}: {result.output}"


def test_full_flag_sets_10_tasks_n5(monkeypatch):
    """CLI-02: --full sets 10 tasks, N=5."""
    captured = {}

    def fake_run(cmd, check):
        i_tasks = cmd.index("--tasks") + 1
        i_n = cmd.index("--n") + 1
        captured["tasks"] = cmd[i_tasks]
        captured["n"] = cmd[i_n]
        return type("R", (), {"returncode": 0})()

    runner = CliRunner()
    with runner.isolated_filesystem():
        out_dir = Path("out")
        with patch("subprocess.run", fake_run):
            runner.invoke(
                main,
                ["--suite", "terminalbench", "--full", "--yes", "--out", str(out_dir)],
            )

    assert captured.get("tasks") == "10"
    assert captured.get("n") == "5"


def test_quick_and_full_are_mutually_exclusive():
    """CLI-01+CLI-02: --quick and --full cannot both be set."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["--quick", "--full", "--yes", "--out", "out"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_cost_gate_aborts_above_hard_stop():
    """CLI-03: hard-stop at $50 raises error without --no-cost-cap."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Force a large trial count to exceed $50
        result = runner.invoke(
            main,
            ["--n", "500", "--tasks", "50", "--yes", "--out", "out"],
        )
    assert result.exit_code != 0
    assert "hard-stop" in result.output.lower() or "50" in result.output


def test_help_documents_subcommands():
    """CLI-06: --help shows key options."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "--suite" in result.output
    assert "--quick" in result.output
    assert "--full" in result.output
    assert "--yes" in result.output
