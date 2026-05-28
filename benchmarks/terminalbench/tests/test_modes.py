"""TB-05 mode-difference tests for AtelierClaudeAgent and make_arm_env.

Acceptance criterion (TB-05): mode=on and mode=off arms produce distinguishably
different ATELIER_BENCH_MODE environment variables.

All tests are in-process only: no Docker, no live claude subprocess, no network.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Ensure ANTHROPIC_API_KEY is available in the environment for agent instantiation.
# Tests that need a specific value use monkeypatch; this default prevents KeyError
# in tests that only care about ATELIER_BENCH_MODE.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-tb05-tests")


# ---------------------------------------------------------------------------
# AtelierClaudeAgent mode-difference tests
# ---------------------------------------------------------------------------


def test_mode_on_sets_atelier_bench_mode_on() -> None:
    """AtelierClaudeAgent(bench_mode='on')._env['ATELIER_BENCH_MODE'] == 'on'."""
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    assert agent._env["ATELIER_BENCH_MODE"] == "on"


def test_mode_off_sets_atelier_bench_mode_off() -> None:
    """AtelierClaudeAgent(bench_mode='off')._env['ATELIER_BENCH_MODE'] == 'off'."""
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="off")
    assert agent._env["ATELIER_BENCH_MODE"] == "off"


def test_mode_on_and_off_envs_differ() -> None:
    """TB-05 PRIMARY ASSERTION: on/off arms must differ on ATELIER_BENCH_MODE."""
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent_on = AtelierClaudeAgent(bench_mode="on")
    agent_off = AtelierClaudeAgent(bench_mode="off")

    assert (
        agent_on._env["ATELIER_BENCH_MODE"] != agent_off._env["ATELIER_BENCH_MODE"]
    ), "TB-05 FAIL: on/off arms must produce distinguishably different ATELIER_BENCH_MODE"


def test_mode_env_dicts_differ() -> None:
    """Full _env dicts of on/off agents must differ (at minimum on ATELIER_BENCH_MODE)."""
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent_on = AtelierClaudeAgent(bench_mode="on")
    agent_off = AtelierClaudeAgent(bench_mode="off")

    assert agent_on._env != agent_off._env


def test_mode_dev_mode_not_leaked(monkeypatch: pytest.MonkeyPatch) -> None:
    """ATELIER_DEV_MODE is never forwarded into the container env (PITFALLS.md #3b)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    monkeypatch.setenv("ATELIER_DEV_MODE", "1")

    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    assert "ATELIER_DEV_MODE" not in agent._env


# ---------------------------------------------------------------------------
# make_arm_env tests — full arm isolation contract
# ---------------------------------------------------------------------------


def test_mode_atelier_root_independent() -> None:
    """make_arm_env with ON vs OFF arms using different tmp dirs → different ATELIER_ROOT."""
    from atelier.bench.mode import BenchMode, make_arm_env

    with (
        tempfile.TemporaryDirectory(prefix="test_arm_on_") as tmp1,
        tempfile.TemporaryDirectory(prefix="test_arm_off_") as tmp2,
    ):
        env_on = make_arm_env(Path(tmp1), mode=BenchMode.ON)
        env_off = make_arm_env(Path(tmp2), mode=BenchMode.OFF)

        assert env_on["ATELIER_ROOT"] != env_off["ATELIER_ROOT"]
        assert env_on["ATELIER_BENCH_MODE"] == "on"
        assert env_off["ATELIER_BENCH_MODE"] == "off"
