"""Verbatim-retry and diagnostic-silencing command gates."""

from __future__ import annotations

import pytest

from atelier.core.capabilities.tool_supervision import command_discipline


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    command_discipline.reset()


def test_fresh_command_is_allowed() -> None:
    assert command_discipline.pre_run_gate("pytest -q").action == "allow"


def test_failed_command_warns_then_blocks_on_verbatim_retry() -> None:
    command_discipline.note_result("pytest -q", exit_code=1)
    first = command_discipline.pre_run_gate("pytest -q")
    assert first.action == "warn"
    command_discipline.note_result("pytest -q", exit_code=1)
    second = command_discipline.pre_run_gate("pytest -q")
    assert second.action == "block"
    assert "approach" in second.reason


def test_whitespace_variants_count_as_verbatim() -> None:
    command_discipline.note_result("pytest   -q", exit_code=1)
    assert command_discipline.pre_run_gate("pytest -q").action == "warn"


def test_success_clears_failure_memory() -> None:
    command_discipline.note_result("pytest -q", exit_code=1)
    command_discipline.note_result("pytest -q", exit_code=0)
    assert command_discipline.pre_run_gate("pytest -q").action == "allow"


def test_timeout_counts_as_failure() -> None:
    command_discipline.note_result("make build", exit_code=None, timed_out=True)
    assert command_discipline.pre_run_gate("make build").action == "warn"


def test_workspace_change_clears_retry_memory() -> None:
    command_discipline.note_result("pytest -q", exit_code=1)
    assert command_discipline.pre_run_gate("pytest -q").action == "warn"
    command_discipline.note_workspace_changed()
    assert command_discipline.pre_run_gate("pytest -q").action == "allow"


def test_workspace_change_keeps_silence_escalation() -> None:
    cmd = "apt-get install -y jq 2>/dev/null"
    assert command_discipline.pre_run_gate(cmd).action == "warn"
    command_discipline.note_workspace_changed()
    assert command_discipline.pre_run_gate(cmd).action == "block"


def test_changed_command_is_not_gated() -> None:
    command_discipline.note_result("pytest -q", exit_code=1)
    assert command_discipline.pre_run_gate("pytest -q -x tests/foo.py").action == "allow"


def test_silenced_install_warns_then_blocks() -> None:
    cmd = "apt-get install -y jq 2>/dev/null"
    first = command_discipline.pre_run_gate(cmd)
    assert first.action == "warn"
    assert "stderr" in first.reason or "/dev/null" in first.reason
    second = command_discipline.pre_run_gate(cmd)
    assert second.action == "block"


def test_silencing_on_non_diagnostic_command_is_allowed() -> None:
    assert command_discipline.pre_run_gate("ls missing_dir 2>/dev/null").action == "allow"


def test_install_without_silencing_is_allowed() -> None:
    assert command_discipline.pre_run_gate("uv pip install requests").action == "allow"
