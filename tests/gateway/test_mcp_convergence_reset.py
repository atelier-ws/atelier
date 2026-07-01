"""Unit tests for mcp_server.py's convergence-spiral streak reset on a new
user message (see `_reset_gather_streaks_on_new_user_message`).

The MCP server's gather-without-edit streak counters (`_NONEDIT_STREAK`,
`_HISTORY_STREAK`) are in-process globals. A new user message means the
previous streak's premise (same open question, still-in-flight exploration)
no longer holds, so it must reset -- detected via sessions/<id>/stats.json's
`turns` counter, maintained by `update_session_stats` and bumped by the
separate UserPromptSubmit hook.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atelier.gateway.adapters import mcp_server


@pytest.fixture(autouse=True)
def _reset_globals():
    mcp_server._NONEDIT_STREAK[0] = 0
    mcp_server._HISTORY_STREAK[0] = 0
    mcp_server._LAST_SEEN_USER_TURNS[0] = 0
    yield
    mcp_server._NONEDIT_STREAK[0] = 0
    mcp_server._HISTORY_STREAK[0] = 0
    mcp_server._LAST_SEEN_USER_TURNS[0] = 0


def _patch_stats(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, turns: int) -> Path:
    stats_path = tmp_path / "stats.json"
    stats_path.write_text(json.dumps({"turns": turns}), encoding="utf-8")
    monkeypatch.setattr("atelier.core.capabilities.plugin_runtime.session_stats_path", lambda *a, **k: stats_path)
    monkeypatch.setattr(mcp_server, "_get_claude_session_id", lambda: "sess-x")
    return stats_path


def test_reset_clears_streaks_when_turns_advance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mcp_server._NONEDIT_STREAK[0] = 25
    mcp_server._HISTORY_STREAK[0] = 8
    _patch_stats(monkeypatch, tmp_path, turns=1)

    mcp_server._reset_gather_streaks_on_new_user_message()

    assert mcp_server._NONEDIT_STREAK[0] == 0
    assert mcp_server._HISTORY_STREAK[0] == 0


def test_reset_is_noop_when_turns_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_stats(monkeypatch, tmp_path, turns=1)
    mcp_server._reset_gather_streaks_on_new_user_message()  # observes turns=1, resets (already 0)
    mcp_server._NONEDIT_STREAK[0] = 12  # simulate tool calls made after that reset

    mcp_server._reset_gather_streaks_on_new_user_message()  # same turns -- no new user message

    assert mcp_server._NONEDIT_STREAK[0] == 12


def test_reset_advances_again_on_next_turn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stats_path = _patch_stats(monkeypatch, tmp_path, turns=1)
    mcp_server._reset_gather_streaks_on_new_user_message()
    mcp_server._NONEDIT_STREAK[0] = 30

    stats_path.write_text(json.dumps({"turns": 2}), encoding="utf-8")
    mcp_server._reset_gather_streaks_on_new_user_message()

    assert mcp_server._NONEDIT_STREAK[0] == 0


def test_reset_is_fail_open_on_missing_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setattr("atelier.core.capabilities.plugin_runtime.session_stats_path", lambda *a, **k: missing)
    monkeypatch.setattr(mcp_server, "_get_claude_session_id", lambda: "sess-x")
    mcp_server._NONEDIT_STREAK[0] = 5
    mcp_server._reset_gather_streaks_on_new_user_message()
    assert mcp_server._NONEDIT_STREAK[0] == 5


# --- execution bash is progress, not gathering (resets the gather streak) ---------
#
# Running the check / building / installing deps rides the `bash` tool, so without
# command classification the gather nudge would fire mid-verification. `_convergence_
# intervention` treats those commands like an edit -> reset. The edit->test->FAIL
# pathology is covered separately by `_test_churn_intervention`.


def _nudge(tool: str, command: str = "") -> bool:
    args = {"command": command} if tool == "bash" else {}
    return "FIXME (convergence)" in mcp_server._convergence_intervention(tool, args, "RESULT")


@pytest.mark.parametrize(
    "command",
    [
        "pip install -q pytest",
        "python3 -m pytest tests/ -q",
        "make -j4",
        "cargo build",
        "npm ci",
        "./configure",
        "gcc -o a a.c",
        "uv pip install foo",
    ],
)
def test_execution_command_resets_gather_streak(command: str) -> None:
    mcp_server._NONEDIT_STREAK[0] = mcp_server._NUDGE_AT - 1
    mcp_server._CONVERGENCE_TIER[0] = -1
    assert _nudge("bash", command) is False
    assert mcp_server._NONEDIT_STREAK[0] == 0


@pytest.mark.parametrize("command", ["git log --oneline", "grep -rn foo .", "cat file", "find / -name x"])
def test_investigative_command_still_counts(command: str) -> None:
    mcp_server._NONEDIT_STREAK[0] = mcp_server._NUDGE_AT - 1
    mcp_server._CONVERGENCE_TIER[0] = -1
    assert _nudge("bash", command) is True


def test_verification_phase_never_fires_but_pure_spiral_does() -> None:
    mcp_server._CONVERGENCE_TIER[0] = -1
    # gather -> edit -> long pytest/pip verification loop: no nudge
    seq = [("bash", "grep -rn secret .")] * 8 + [("edit", "")]
    seq += [("bash", "pip install -q pytest"), ("bash", "python3 -m pytest -q")] * 10
    assert sum(_nudge(t, c) for t, c in seq) == 0
    # a pure gather spiral still trips exactly once (one notice per tier)
    mcp_server._NONEDIT_STREAK[0] = 0
    mcp_server._CONVERGENCE_TIER[0] = -1
    assert sum(_nudge("bash", f"grep -rn p{i} .") for i in range(mcp_server._NUDGE_AT + 3)) == 1


# --- history-archaeology nudge: targeted retrieval is work, not spiral -------------
#
# Some tasks' answer legitimately lives in git history (reconstruct a past state,
# recover a deleted blob). A date/keyword-bounded read or a `git show <ref>:path`
# blob fetch is targeted retrieval -> resets the streak. Bare log/blame/show <commit>
# (reading diffs to understand code) still accumulates toward the archaeology nudge.


def _hist(command: str) -> bool:
    return "FIXME (convergence)" in mcp_server._history_archaeology_intervention("bash", {"command": command}, "R")


@pytest.mark.parametrize(
    "command",
    [
        'git log --all --before="2025-09-01"',
        "git rev-list -1 --before=2025-09-01 HEAD",
        'git log --oneline --grep="Scandinavian"',
        "git show 5bf303b2:mteb/benchmarks/benchmarks.py",
        "git fetch --unshallow && git log --reverse",
    ],
)
def test_targeted_history_retrieval_resets(command: str) -> None:
    mcp_server._HISTORY_STREAK[0] = mcp_server._HISTORY_TIERS[0] - 1
    assert _hist(command) is False
    assert mcp_server._HISTORY_STREAK[0] == 0


def test_blind_archaeology_still_fires() -> None:
    mcp_server._HISTORY_STREAK[0] = 0
    blind = [
        "git log --oneline",
        "git blame vm.js",
        "git show HEAD~1",
        "git log -p",
        "git blame p.c",
        "git show HEAD~2",
    ]
    assert any(_hist(c) for c in blind)  # crosses tier-1 at 6 blind reads


# --- test-churn: an explicit pass beats incidental "error"/"Traceback" text -------
#
# _classify_test_outcome used to check the FAIL regex before PASS, and FAIL matched
# bare "error"/"Traceback", so a green run whose output merely mentioned an error
# (a log line, a caught+asserted exception) was scored a failure -> the churn nudge
# fired on passing tests. A nonzero failure COUNT still wins; incidental words lose.


@pytest.mark.parametrize(
    "out,expected",
    [
        ("23 passed in 0.4s", "PASS"),
        ("23 passed\n[app] ERROR: retrying connection", "PASS"),  # incidental ERROR log
        ("5 passed\nTraceback (most recent call last): caught+asserted", "PASS"),  # caught tb
        ("Ran 5 tests in 0.1s\nOK", "PASS"),
        ("1 failed, 22 passed", "FAIL"),  # explicit nonzero failure count wins
        ("FAILED (failures=2, errors=1)", "FAIL"),  # unittest summary
        ("E   AssertionError: expected 3", "FAIL"),  # soft signal, no pass summary
        ("3 failed", "FAIL"),
    ],
)
def test_classify_test_outcome_prefers_pass_over_incidental_error(out: str, expected: str) -> None:
    assert mcp_server._classify_test_outcome("pytest -q", out) == expected


def test_classify_ignores_non_test_command() -> None:
    assert mcp_server._classify_test_outcome("ls -la", "whatever output") is None
