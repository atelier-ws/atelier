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
