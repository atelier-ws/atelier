"""Tests for the high-context compact nudge in the session telemetry hook."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from atelier.core.capabilities import plugin_runtime as pr
from atelier.core.capabilities import savings_summary as ss


def _payload() -> dict[str, Any]:
    return {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "read"}


def _prep_root(root: Path) -> None:
    # In production the SessionStart/update_session_stats path creates this
    # directory before the progress hook ever writes notices.
    (root / "session_stats").mkdir(parents=True, exist_ok=True)


def test_ctx_nudge_fires_once_above_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prep_root(tmp_path)
    monkeypatch.setattr(ss, "transcript_context_state", lambda sid: (200_000, "claude-sonnet-4-5"))
    out = pr.build_session_progress_optimization_output(tmp_path, _payload())
    text = json.dumps(out)
    assert "high context" in text
    assert "200k" in text
    # One-shot: the notice is persisted and must not fire again.
    out2 = pr.build_session_progress_optimization_output(tmp_path, _payload())
    assert "high context" not in json.dumps(out2)


def test_ctx_nudge_silent_below_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prep_root(tmp_path)
    monkeypatch.setattr(ss, "transcript_context_state", lambda sid: (40_000, "claude-sonnet-4-5"))
    out = pr.build_session_progress_optimization_output(tmp_path, _payload())
    assert "high context" not in json.dumps(out)


def test_ctx_nudge_threshold_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _prep_root(tmp_path)
    monkeypatch.setattr(ss, "transcript_context_state", lambda sid: (60_000, "claude-sonnet-4-5"))
    monkeypatch.setenv("ATELIER_CTX_NUDGE_TOKENS", "50000")
    out = pr.build_session_progress_optimization_output(tmp_path, _payload())
    assert "high context" in json.dumps(out)
