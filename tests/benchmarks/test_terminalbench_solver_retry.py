from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS_ROOT = ROOT / "benchmarks"
if str(BENCHMARKS_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_ROOT))

pytest.importorskip("terminalbench.agent_adapter")

from terminalbench.agent_adapter import (  # noqa: E402
    AtelierOwnedSolverAgent,
    _agent_import_path,
    run_terminalbench_trial,
)


def test_terminalbench_owned_provider_selects_owned_agent_import() -> None:
    assert _agent_import_path("owned") == "terminalbench.agent_adapter:AtelierOwnedSolverAgent"


def test_terminalbench_owned_provider_builds_owned_solver_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    agent = AtelierOwnedSolverAgent(bench_mode="on", model="claude-opus-4.8")
    command = agent._run_agent_commands("solve the benchmark task")[0].command

    assert "atelier benchmark solver" in command
    assert "--format stream-json" in command
    assert "--out /logs/owned" in command


def test_terminalbench_owned_provider_requires_on_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bench_mode='on'"):
        run_terminalbench_trial(
            task_id="hello-world",
            bench_mode="off",
            rep=1,
            out_dir=tmp_path,
            model="claude-opus-4.8",
            provider="owned",
        )
