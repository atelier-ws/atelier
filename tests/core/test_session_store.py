from __future__ import annotations

import json
from pathlib import Path

from atelier.core.foundation.session_store import SessionStore


def _trace(tid: str, session_id: str, **extra: object) -> dict:
    base = {
        "id": tid,
        "session_id": session_id,
        "agent": "gsd-executor",
        "host": "claude",
        "domain": "coding",
        "status": "success",
        "task": "do a thing",
        "output_summary": "did the thing",
        "files_touched": ["a.py"],
        "created_at": "2026-06-10T00:00:00+00:00",
        "input_tokens": 100,
        "output_tokens": 20,
    }
    base.update(extra)
    return base


def test_record_writes_file_meta_and_index(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = store.record(_trace("t1", "sess1"))
    assert sid == "sess1"
    traces_file = store.session_dir("sess1") / "traces.jsonl"
    assert traces_file.exists()
    assert len(store.traces_for("sess1")) == 1
    meta = store.meta("sess1")
    assert meta is not None and meta["trace_ids"] == ["t1"]
    # index round-trip
    assert store.get("t1")["task"] == "do a thing"


def test_meta_records_transcript_path(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    tpath = "/home/u/.claude/projects/ws/sess1.jsonl"
    store.record(_trace("t1", "sess1", transcript_path=tpath))
    meta = store.meta("sess1")
    assert meta is not None and meta["transcript_path"] == tpath
    # A later trace without the path must not clobber the recorded one.
    store.record(_trace("t2", "sess1"))
    assert store.meta("sess1")["transcript_path"] == tpath


def test_record_is_idempotent_per_trace_id(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "sess1", status="partial"))
    store.record(_trace("t1", "sess1", status="success"))  # same id replaces
    traces = store.traces_for("sess1")
    assert len(traces) == 1
    assert traces[0]["status"] == "success"
    assert store.meta("sess1")["trace_ids"] == ["t1"]


def test_query_filters_and_orders(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1", domain="coding", created_at="2026-06-01T00:00:00+00:00"))
    store.record(_trace("t2", "s2", domain="docs", created_at="2026-06-05T00:00:00+00:00"))
    store.record(_trace("t3", "s3", domain="coding", created_at="2026-06-09T00:00:00+00:00"))
    coding = store.query(domain="coding")
    assert [r["id"] for r in coding] == ["t3", "t1"]  # newest first
    recent = store.query(since="2026-06-04T00:00:00+00:00")
    assert {r["id"] for r in recent} == {"t2", "t3"}


def test_search_matches_document(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1", task="fix the redis rate limiter"))
    store.record(_trace("t2", "s2", task="update the docs"))
    hits = store.search("redis")
    assert [h["id"] for h in hits] == ["t1"]


def test_rebuild_index_from_files(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1"))
    store.record(_trace("t2", "s1"))
    # nuke the index; files remain the source of truth
    store.index_path.unlink()
    assert store.query() == []
    count = store.rebuild_index()
    assert count == 2
    assert {r["id"] for r in store.query()} == {"t1", "t2"}


def test_orphan_session_id_falls_back_to_trace_id(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = store.record({"id": "loose", "task": "x", "created_at": "2026-06-10T00:00:00+00:00"})
    assert sid == "loose"
    assert (store.session_dir("loose") / "traces.jsonl").exists()


def test_delete_prunes_meta_trace_ids(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "sess1"))
    store.record(_trace("t2", "sess1"))
    store.delete("t1")
    # files-as-source-of-truth must stay internally consistent after a delete
    assert [t["id"] for t in store.traces_for("sess1")] == ["t2"]
    assert store.meta("sess1")["trace_ids"] == ["t2"]
    assert store.get("t1") is None


def test_traces_jsonl_is_valid_jsonl(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record(_trace("t1", "s1"))
    store.record(_trace("t2", "s1"))
    lines = (store.session_dir("s1") / "traces.jsonl").read_text("utf-8").strip().splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["id"] for line in lines)
