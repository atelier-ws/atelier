"""Window-anchored session-id resolution (the /clear + concurrent-session fix)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atelier.core.foundation import session_window as sw


def _write_rows(root: Path, ws: str, rows: list[dict[str, Any]]) -> None:
    p = sw.registry_path(root, ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_window_match_beats_stale_env(tmp_path: Path, monkeypatch: Any) -> None:
    ws = "deadbeef0001"
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: (4242, 999))
    _write_rows(
        tmp_path,
        ws,
        [
            {"session_id": "sibling", "window_pid": 7777, "window_btime": 111},
            {"session_id": "mine", "window_pid": 4242, "window_btime": 999},
        ],
    )
    # Launch env is stale; the window-matched row wins.
    assert sw.resolve_window_session_id(tmp_path, ws, env_session_id="stale-launch") == "mine"


def test_clear_newest_window_row_wins(tmp_path: Path, monkeypatch: Any) -> None:
    ws = "deadbeef0002"
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: (4242, 999))
    _write_rows(
        tmp_path,
        ws,
        [
            {"session_id": "pre-clear", "window_pid": 4242, "window_btime": 999, "source": "startup"},
            {"session_id": "post-clear", "window_pid": 4242, "window_btime": 999, "source": "clear"},
        ],
    )
    assert sw.resolve_window_session_id(tmp_path, ws, env_session_id="pre-clear") == "post-clear"


def test_concurrent_windows_isolated(tmp_path: Path, monkeypatch: Any) -> None:
    ws = "deadbeef0003"
    _write_rows(
        tmp_path,
        ws,
        [
            {"session_id": "win-a", "window_pid": 100, "window_btime": 1},
            {"session_id": "win-b", "window_pid": 200, "window_btime": 2},
        ],
    )
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: (100, 1))
    assert sw.resolve_window_session_id(tmp_path, ws, env_session_id="") == "win-a"
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: (200, 2))
    assert sw.resolve_window_session_id(tmp_path, ws, env_session_id="") == "win-b"


def test_pid_reuse_guarded_by_btime(tmp_path: Path, monkeypatch: Any) -> None:
    ws = "deadbeef0004"
    _write_rows(tmp_path, ws, [{"session_id": "old-proc", "window_pid": 4242, "window_btime": 111}])
    # Same pid, different start time -> not a match -> env fallback.
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: (4242, 222))
    assert sw.resolve_window_session_id(tmp_path, ws, env_session_id="env-live") == "env-live"


def test_env_fallback_when_no_window(tmp_path: Path, monkeypatch: Any) -> None:
    ws = "deadbeef0005"
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: None)
    _write_rows(tmp_path, ws, [{"session_id": "mru", "window_pid": 1, "window_btime": 1}])
    assert sw.resolve_window_session_id(tmp_path, ws, env_session_id="env-x") == "env-x"


def test_mru_fallback_when_no_window_no_env(tmp_path: Path, monkeypatch: Any) -> None:
    ws = "deadbeef0006"
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: None)
    _write_rows(
        tmp_path,
        ws,
        [
            {"session_id": "old", "window_pid": 1, "window_btime": 1},
            {"session_id": "newest", "window_pid": 2, "window_btime": 2},
        ],
    )
    assert sw.resolve_window_session_id(tmp_path, ws, env_session_id="") == "newest"


def test_register_roundtrip_and_trim(tmp_path: Path, monkeypatch: Any) -> None:
    ws = "deadbeef0007"
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: (555, 42))
    monkeypatch.setattr(sw, "_MAX_REGISTRY_ROWS", 5)
    for i in range(12):
        sw.register_window_session(tmp_path, ws, session_id=f"s{i}", source="startup")
    rows = sw._read_registry(tmp_path, ws)
    assert len(rows) == 5  # trimmed to most recent N
    assert rows[-1]["session_id"] == "s11"
    assert rows[-1]["window_pid"] == 555 and rows[-1]["window_btime"] == 42
    assert sw.resolve_window_session_id(tmp_path, ws, env_session_id="") == "s11"


def test_empty_session_id_not_registered(tmp_path: Path, monkeypatch: Any) -> None:
    ws = "deadbeef0008"
    monkeypatch.setattr(sw, "host_window_id", lambda *a, **k: (1, 1))
    sw.register_window_session(tmp_path, ws, session_id="")
    assert sw._read_registry(tmp_path, ws) == []
