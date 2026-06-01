"""Tests for the benchmark CLI subcommand workflow."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from atelier.gateway.cli import cli
from atelier.gateway.cli.commands import benchmark as benchmark_cmds

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_benchmark_legacy_top_level_commands_are_removed(tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"

    assert runner.invoke(cli, ["--root", str(root), "benchmark-core", "--json"]).exit_code != 0
    assert (
        runner.invoke(
            cli, ["--root", str(root), "benchmark", "--prompt", "Fix PDP", "--json"]
        ).exit_code
        != 0
    )


def test_help_command_shows_root_command_help(tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"

    root_help = runner.invoke(cli, ["--root", str(root), "help"])
    assert root_help.exit_code == 0, root_help.output
    assert "Commands:" in root_help.output
    assert "benchmark" in root_help.output


def test_benchmark_terminalbench_defaults_to_all_tasks_and_modes(
    monkeypatch, tmp_path: Path
) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"
    calls: list[tuple[list[str], str, dict[str, str] | None]] = []

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(benchmark_cmds, "_python_cmd", lambda _repo_root: ["python"])
    monkeypatch.setattr(
        benchmark_cmds, "_run_dir", lambda suite, out, repo_root=None: tmp_path / suite
    )
    monkeypatch.setattr(
        benchmark_cmds,
        "_run",
        lambda cmd, cwd, label, env=None: calls.append((cmd, label, env)),
    )

    result = runner.invoke(cli, ["--root", str(root), "benchmark", "terminalbench"])

    assert result.exit_code == 0, result.output
    trial_calls = [cmd for cmd, label, _env in calls if label == "TerminalBench trial"]
    summary_calls = [cmd for cmd, label, _env in calls if label == "TerminalBench summary"]
    assert len(trial_calls) == 20
    assert len(summary_calls) == 1
    assert {cmd[cmd.index("--mode") + 1] for cmd in trial_calls} == {"on", "off"}
    assert {cmd[cmd.index("--task") + 1] for cmd in trial_calls} == {
        "hello-world",
        "fix-pandas-version",
        "incompatible-python-fasttext",
        "csv-to-parquet",
        "fibonacci-server",
        "simple-web-scraper",
        "fix-git",
        "swe-bench-fsspec",
        "swe-bench-langcodes",
        "grid-pattern-transform",
    }


def test_benchmark_swe_defaults_to_real_eval(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"
    captured: dict[str, object] = {}

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(
        benchmark_cmds, "_run_dir", lambda suite, out, repo_root=None: tmp_path / suite
    )

    def fake_run_swe_eval(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(benchmark_cmds, "_run_swe_eval", fake_run_swe_eval)

    result = runner.invoke(cli, ["--root", str(root), "benchmark", "swe"])

    assert result.exit_code == 0, result.output
    assert captured["subset"] == "lite"
    assert captured["split"] == "dev"
    assert captured["slice_expr"] == "0:5"
    assert captured["workers"] == 1
    assert captured["proxy_upstream"] == "http://localhost:11434/v1"


def test_benchmark_vix_wraps_runner(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"
    calls: list[tuple[list[str], str, dict[str, str] | None]] = []
    eval_dir = tmp_path / "eval-eval"
    eval_dir.mkdir()

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(benchmark_cmds, "_python_cmd", lambda _repo_root: ["python"])
    monkeypatch.setattr(
        benchmark_cmds, "_run_dir", lambda suite, out, repo_root=None: tmp_path / suite
    )
    monkeypatch.setattr(
        benchmark_cmds, "_ensure_eval_dir", lambda repo_root, path: eval_dir
    )
    monkeypatch.setattr(
        benchmark_cmds,
        "_run",
        lambda cmd, cwd, label, env=None: calls.append((cmd, label, env)),
    )

    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "benchmark",
            "eval",
            "--eval-eval-dir",
            str(eval_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    cmd, label, env = calls[0]
    assert label == "VIX benchmark"
    assert cmd[:3] == ["python", "-m", "benchmarks.eval.run"]
    assert "--tasks" in cmd and cmd[cmd.index("--tasks") + 1] == "all"
    assert "--arms" in cmd
    assert env == {"VIX_EVAL_DIR": str(eval_dir.resolve())}


def test_benchmark_mcp_defaults_jobs_to_auto(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"
    calls: list[tuple[list[str], str, dict[str, str] | None]] = []

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(benchmark_cmds, "_python_cmd", lambda _repo_root: ["python"])
    monkeypatch.setattr(benchmark_cmds, "_resolve_mcp_jobs", lambda jobs, repo_root: 6)
    monkeypatch.setattr(
        benchmark_cmds, "_run_dir", lambda suite, out, repo_root=None: tmp_path / suite
    )
    monkeypatch.setattr(
        benchmark_cmds,
        "_run",
        lambda cmd, cwd, label, env=None: calls.append((cmd, label, env)),
    )

    result = runner.invoke(cli, ["--root", str(root), "benchmark", "mcp"])

    assert result.exit_code == 0, result.output
    cmd, _label, _env = calls[0]
    assert cmd[cmd.index("--jobs") + 1] == "6"


def test_benchmark_mcp_passes_parallel_jobs(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"
    calls: list[tuple[list[str], str, dict[str, str] | None]] = []

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(benchmark_cmds, "_python_cmd", lambda _repo_root: ["python"])
    monkeypatch.setattr(
        benchmark_cmds, "_run_dir", lambda suite, out, repo_root=None: tmp_path / suite
    )
    monkeypatch.setattr(
        benchmark_cmds,
        "_run",
        lambda cmd, cwd, label, env=None: calls.append((cmd, label, env)),
    )

    result = runner.invoke(cli, ["--root", str(root), "benchmark", "mcp", "--jobs", "3"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    cmd, label, _env = calls[0]
    assert label == "MCP benchmark"
    assert "--jobs" in cmd
    assert cmd[cmd.index("--jobs") + 1] == "3"


def test_benchmark_providers_passes_parallel_jobs(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"
    calls: list[tuple[list[str], str, dict[str, str] | None]] = []

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(benchmark_cmds, "_python_cmd", lambda _repo_root: ["python"])
    monkeypatch.setattr(
        benchmark_cmds, "_run_dir", lambda suite, out, repo_root=None: tmp_path / suite
    )
    monkeypatch.setattr(
        benchmark_cmds,
        "_workspace_dir",
        lambda suite, repo_root, run_id: tmp_path / "workspace",
    )
    monkeypatch.setattr(
        benchmark_cmds,
        "_run",
        lambda cmd, cwd, label, env=None: calls.append((cmd, label, env)),
    )

    result = runner.invoke(cli, ["--root", str(root), "benchmark", "providers", "--jobs", "4"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    cmd, label, _env = calls[0]
    assert label == "provider benchmark"
    assert "--jobs" in cmd
    assert cmd[cmd.index("--jobs") + 1] == "4"


def test_benchmark_providers_defaults_to_auto_and_cache_root(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"
    calls: list[tuple[list[str], str, dict[str, str] | None]] = []

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(benchmark_cmds, "_python_cmd", lambda _repo_root: ["python"])
    monkeypatch.setattr(
        benchmark_cmds, "_run_dir", lambda suite, out, repo_root=None: tmp_path / suite
    )
    monkeypatch.setattr(
        benchmark_cmds,
        "_workspace_dir",
        lambda suite, repo_root, run_id: tmp_path / "workspace",
    )
    monkeypatch.setattr(benchmark_cmds, "_resolve_provider_jobs", lambda jobs, providers: 3)
    monkeypatch.setattr(
        benchmark_cmds,
        "_cache_dir",
        lambda suite, repo_root: tmp_path / "cache",
    )
    monkeypatch.setattr(
        benchmark_cmds,
        "_run",
        lambda cmd, cwd, label, env=None: calls.append((cmd, label, env)),
    )

    result = runner.invoke(cli, ["--root", str(root), "benchmark", "providers"])

    assert result.exit_code == 0, result.output
    cmd, label, _env = calls[0]
    assert label == "provider benchmark"
    assert cmd[cmd.index("--jobs") + 1] == "3"
    assert cmd[cmd.index("--cache-root") + 1] == str((tmp_path / "cache").resolve())
