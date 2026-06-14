from __future__ import annotations

from pathlib import Path

from atelier.core.foundation.session_store import SessionStore


def _trace(tid: str, session_id: str, **extra: object) -> dict:
    base: dict = {
        "id": tid,
        "session_id": session_id,
        "agent": "gsd-executor",
        "host": "claude",
        "domain": "coding",
        "status": "success",
        "task": "do a thing",
        "output_summary": "did it",
        "files_touched": ["a.py"],
        "created_at": "2026-06-10T00:00:00+00:00",
        "input_tokens": 100,
        "output_tokens": 20,
    }
    base.update(extra)
    return base


def test_list_full_returns_payloads(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1", task="real work"))
    store.record(_trace("t3", "s3", domain="docs"))
    coding = store.list_full(domain="coding")
    assert [t["id"] for t in coding] == ["t1"]  # t3 is docs
    assert coding[0]["output_summary"] == "did it"  # full payload, not just index meta


def test_list_full_query_path(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1", task="fix the redis limiter"))
    store.record(_trace("t2", "s2", task="update docs"))
    hits = store.list_full(query="redis")
    assert [t["id"] for t in hits] == ["t1"]


def test_metrics_counts_and_distincts(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1", status="success"))
    store.record(_trace("t2", "s2", status="failed", host="codex"))
    m = store.metrics()
    assert m["total"] == 2
    assert m["success"] == 1 and m["failed"] == 1
    assert set(m["hosts"]) == {"claude", "codex"}


def test_delete_removes_from_file_and_index(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1"))
    store.record(_trace("t2", "s1"))
    store.delete("t1")
    assert not store.exists("t1")
    assert [t["id"] for t in store.traces_for("s1")] == ["t2"]
    assert {r["id"] for r in store.query()} == {"t2"}


def test_sync_tracking(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1"))
    store.record(_trace("t2", "s1"))
    assert set(store.unsynced_ids()) == {"t1", "t2"}
    store.mark_synced("s1", at="2026-06-11T00:00:00+00:00")
    assert store.unsynced_ids() == []
