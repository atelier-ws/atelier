"""Tests for within-session content dedup (context_dedup)."""

from __future__ import annotations

import json

from atelier.core.capabilities.context_dedup import ContextDedup, current_epoch

_BIG = "x" * 5000  # above _MIN_DEDUP_CHARS
_BIG2 = "y" * 5000


def test_first_emit_is_not_stubbed_then_duplicate_is() -> None:
    d = ContextDedup()
    assert d.stub_for(session_id="s", content=_BIG, epoch=0, force=False) is None
    out = d.stub_for(session_id="s", content=_BIG, epoch=0, force=False)
    assert out is not None
    stub, saved = out
    assert "already returned" in stub
    assert saved > 0


def test_force_bypasses_and_keeps_recording() -> None:
    d = ContextDedup()
    d.stub_for(session_id="s", content=_BIG, epoch=0, force=False)
    # force => no stub even though it's a duplicate
    assert d.stub_for(session_id="s", content=_BIG, epoch=0, force=True) is None
    # subsequent non-forced call still dedups
    assert d.stub_for(session_id="s", content=_BIG, epoch=0, force=False) is not None


def test_small_content_is_never_stubbed() -> None:
    d = ContextDedup()
    small = "tiny"
    assert d.stub_for(session_id="s", content=small, epoch=0, force=False) is None
    assert d.stub_for(session_id="s", content=small, epoch=0, force=False) is None


def test_distinct_content_not_confused() -> None:
    d = ContextDedup()
    assert d.stub_for(session_id="s", content=_BIG, epoch=0, force=False) is None
    assert d.stub_for(session_id="s", content=_BIG2, epoch=0, force=False) is None


def test_epoch_change_resets_seen() -> None:
    d = ContextDedup()
    d.stub_for(session_id="s", content=_BIG, epoch=0, force=False)
    assert d.stub_for(session_id="s", content=_BIG, epoch=0, force=False) is not None
    # compaction bumped the epoch -> seen-set reset -> not a duplicate anymore
    assert d.stub_for(session_id="s", content=_BIG, epoch=1, force=False) is None


def test_sessions_are_isolated() -> None:
    d = ContextDedup()
    d.stub_for(session_id="a", content=_BIG, epoch=0, force=False)
    assert d.stub_for(session_id="b", content=_BIG, epoch=0, force=False) is None


def test_missing_session_id_is_noop() -> None:
    d = ContextDedup()
    assert d.stub_for(session_id="", content=_BIG, epoch=0, force=False) is None
    assert d.stub_for(session_id="", content=_BIG, epoch=0, force=False) is None


def test_current_epoch_reads_session_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    assert current_epoch() == 0
    import hashlib

    digest = hashlib.sha256(str(tmp_path.resolve()).encode("utf-8")).hexdigest()[:12]
    state_path = tmp_path / "workspaces" / digest / "session_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"compaction_epoch": 3}), encoding="utf-8")
    assert current_epoch() == 3
