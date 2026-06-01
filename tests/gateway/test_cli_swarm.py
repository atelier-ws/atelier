from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from atelier.core.capabilities.swarm.models import SwarmChildState, SwarmRunState
from atelier.gateway.cli import cli


def test_swarm_start_requires_child_command(tmp_path: Path) -> None:
    runner = CliRunner()
    spec = tmp_path / "program.md"
    spec.write_text("# spec\n", encoding="utf-8")
    result = runner.invoke(cli, ["swarm", "start", str(spec)])
    assert result.exit_code != 0


def test_swarm_start_reports_winner(monkeypatch: object, tmp_path: Path) -> None:
    runner = CliRunner()
    spec = tmp_path / "program.md"
    spec.write_text("# spec\n", encoding="utf-8")
    root = tmp_path / "atelier-root"
    state = SwarmRunState(
        run_id="swarm-123",
        status="success",
        mode="continuous",
        repo_root=str(tmp_path),
        base_worktree=str(tmp_path),
        base_ref="HEAD",
        worktree_pool=str(tmp_path / "pool"),
        integration_worktree=str(tmp_path / "pool" / "integration"),
        integration_base_ref="HEAD",
        spec_source_path=str(spec),
        copied_spec_path=str(spec),
        child_command=["echo", "hi"],
        runs=1,
        current_wave=2,
        winner_child_id="wave-02-run-01",
        accepted_child_ids=["wave-01-run-01", "wave-02-run-01"],
        children=[
            SwarmChildState(
                child_id="wave-02-run-01",
                label="candidate-1",
                wave_index=2,
                status="success",
                worktree_path=str(tmp_path / "pool" / "wave-02-run-01"),
                atelier_root=str(root / "child"),
                run_dir=str(root / "runs" / "run-01"),
                spec_path=str(spec),
                result_path=str(root / "runs" / "run-01" / "result.json"),
                stdout_path=str(root / "runs" / "run-01" / "stdout.log"),
                stderr_path=str(root / "runs" / "run-01" / "stderr.log"),
                metadata_path=str(root / "runs" / "run-01" / "meta.json"),
                summary="best candidate",
                score=110.0,
                accepted=True,
            )
        ],
    )

    monkeypatch.setattr("atelier.gateway.cli.commands.swarm.discover_repo_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(
        "atelier.gateway.cli.commands.swarm.initialize_swarm_run",
        lambda **_: (state, tmp_path / "state.json"),
    )
    monkeypatch.setattr(
        "atelier.gateway.cli.commands.swarm.launch_swarm_children",
        lambda _root, _state: state,
    )

    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "swarm",
            "start",
            str(spec),
            "--continuous",
            "--",
            "echo",
            "hi",
        ],
    )

    assert result.exit_code == 0
    assert "latest_winner: wave-02-run-01" in result.output
    assert "mode: continuous" in result.output


def test_swarm_status_reads_state(monkeypatch: object, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / "atelier-root"
    run_id = "swarm-123"
    state_path = root / "swarm" / "runs" / run_id / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{}", encoding="utf-8")
    state = SwarmRunState(
        run_id=run_id,
        status="success",
        repo_root=str(tmp_path),
        base_worktree=str(tmp_path),
        base_ref="HEAD",
        worktree_pool=str(tmp_path / "pool"),
        integration_worktree=str(tmp_path / "pool" / "integration"),
        integration_base_ref="HEAD",
        spec_source_path=str(tmp_path / "program.md"),
        copied_spec_path=str(tmp_path / "program.md"),
        child_command=["echo", "hi"],
        runs=0,
        children=[],
    )
    monkeypatch.setattr("atelier.gateway.cli.commands.swarm.load_swarm_state", lambda _path: state)

    result = runner.invoke(cli, ["--root", str(root), "swarm", "status", run_id])

    assert result.exit_code == 0
    assert "run_id: swarm-123" in result.output


def test_swarm_list_prints_known_runs(monkeypatch: object, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / "atelier-root"
    state = SwarmRunState(
        run_id="swarm-123",
        status="running",
        mode="continuous",
        repo_root=str(tmp_path),
        base_worktree=str(tmp_path),
        base_ref="HEAD",
        worktree_pool=str(tmp_path / "pool"),
        integration_worktree=str(tmp_path / "pool" / "integration"),
        integration_base_ref="HEAD",
        spec_source_path=str(tmp_path / "program.md"),
        copied_spec_path=str(tmp_path / "program.md"),
        child_command=["echo", "hi"],
        runs=2,
        current_wave=3,
        accepted_child_ids=["wave-01-run-01"],
        children=[
            SwarmChildState(
                child_id="wave-03-run-01",
                label="candidate-1",
                wave_index=3,
                status="running",
                worktree_path=str(tmp_path / "pool" / "wave-03-run-01"),
                atelier_root=str(root / "child"),
                run_dir=str(root / "runs" / "run-01"),
                spec_path=str(tmp_path / "program.md"),
                result_path=str(root / "runs" / "run-01" / "result.json"),
                stdout_path=str(root / "runs" / "run-01" / "stdout.log"),
                stderr_path=str(root / "runs" / "run-01" / "stderr.log"),
                metadata_path=str(root / "runs" / "run-01" / "meta.json"),
            )
        ],
    )
    monkeypatch.setattr("atelier.gateway.cli.commands.swarm.list_swarm_runs", lambda _root: [state])

    result = runner.invoke(cli, ["--root", str(root), "swarm", "list"])

    assert result.exit_code == 0
    assert "swarm-123" in result.output
    assert "continuous" in result.output


def test_swarm_logs_reads_child_output(monkeypatch: object, tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / "atelier-root"
    monkeypatch.setattr(
        "atelier.gateway.cli.commands.swarm.read_swarm_log",
        lambda *_args, **_kwargs: "child is compacting json",
    )

    result = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "swarm",
            "logs",
            "swarm-123",
            "--child-id",
            "wave-01-run-01",
        ],
    )

    assert result.exit_code == 0
    assert "compacting json" in result.output
