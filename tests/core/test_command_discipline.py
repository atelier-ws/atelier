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


def test_shell_grep_is_redirected_to_grep_tool() -> None:
    decision = command_discipline.pre_run_gate("grep -r foo src/")
    assert decision.action == "warn"
    assert "`grep`" in decision.reason and "`read`" in decision.reason


def test_db_shell_is_redirected_to_sql_tool() -> None:
    decision = command_discipline.pre_run_gate("psql -c 'select 1'")
    assert decision.action == "warn"
    assert "`sql`" in decision.reason


def test_search_redirect_warns_then_blocks_repeat_in_class() -> None:
    assert command_discipline.pre_run_gate("grep foo a.py").action == "warn"
    # Repeat in the same class after coaching -> blocked with the replacement named.
    blocked = command_discipline.pre_run_gate("rg bar src/")
    assert blocked.action == "block"
    assert "`code_search`" in blocked.reason
    # Other classes get their own single coaching warn.
    assert command_discipline.pre_run_gate("find . -name '*.py'").action == "warn"
    assert command_discipline.pre_run_gate("cat a.py").action == "warn"


def test_find_and_sql_never_block() -> None:
    assert command_discipline.pre_run_gate("find . -name '*.py'").action == "warn"
    assert command_discipline.pre_run_gate("find src -type f").action == "allow"
    assert command_discipline.pre_run_gate("psql -c 'select 1'").action == "warn"
    assert command_discipline.pre_run_gate("psql -c 'select 2'").action == "allow"


def test_read_redirect_blocks_repeat_but_exempts_writes_and_follows() -> None:
    assert command_discipline.pre_run_gate("cat a.py").action == "warn"
    blocked = command_discipline.pre_run_gate("head -50 b.py")
    assert blocked.action == "block"
    assert "`read`" in blocked.reason
    # Heredocs/redirects are writes; tail -f is a follow — read can't replace them.
    assert command_discipline.pre_run_gate("cat > out.txt").action == "allow"
    assert command_discipline.pre_run_gate("tail -f server.log").action == "allow"


def test_redirect_block_kill_switch(monkeypatch) -> None:
    monkeypatch.setenv("ATELIER_SHELL_REDIRECT_BLOCK", "0")
    assert command_discipline.pre_run_gate("grep foo a.py").action == "warn"
    assert command_discipline.pre_run_gate("grep bar b.py").action == "allow"


def test_piped_grep_is_not_redirected() -> None:
    # grep filtering command output is legitimate; only the leading word matters.
    assert command_discipline.pre_run_gate("ps aux | grep node").action == "allow"


def test_search_redirect_skipped_for_out_of_repo_absolute_path(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    scratch = tmp_path / "scratch.html"
    scratch.write_text("x")
    assert command_discipline.pre_run_gate(f"grep -o foo {scratch}", cwd=str(repo)).action == "allow"


def test_search_redirect_still_fires_for_in_repo_absolute_path(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "a.py"
    target.write_text("x")
    assert command_discipline.pre_run_gate(f"grep foo {target}", cwd=str(repo)).action == "warn"


def test_reset_clears_redirect_memory() -> None:
    assert command_discipline.pre_run_gate("grep foo a.py").action == "warn"
    command_discipline.reset()
    assert command_discipline.pre_run_gate("grep foo a.py").action == "warn"
