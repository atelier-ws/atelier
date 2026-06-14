from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from atelier.core.foundation.models import Trace
from atelier.core.foundation.store import ContextStore


def _trace(session_id: str) -> Trace:
    return Trace(
        id=Trace.make_id("session-store wiring", "gsd-executor"),
        agent="gsd-executor",
        domain="coding",
        task="wire session store",
        status="success",
        files_touched=["a.py"],
        diff_summary="x",
        output_summary="done",
        session_id=session_id,
        created_at=datetime.now(UTC),
    )


def test_record_trace_populates_session_store(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    store = ContextStore(root)
    store.init()
    trace = _trace("sess-1")
    store.record_trace(trace)

    # Per-session file is written (source of truth) ...
    assert (root / "sessions" / "sess-1" / "traces.jsonl").exists()
    recorded = store.session_store.traces_for("sess-1")
    assert [t["id"] for t in recorded] == [trace.id]
    # ... and the tiny index is queryable.
    assert [r["id"] for r in store.session_store.query(domain="coding")] == [trace.id]


def test_record_trace_write_json_false_skips_session_store(tmp_path: Path) -> None:
    # Bulk import path (write_json=False) must not pay per-trace file/index I/O;
    # host-session import populates the session store directly instead.
    root = tmp_path / ".atelier"
    store = ContextStore(root)
    store.init()
    store.record_trace(_trace("sess-2"), write_json=False)
    assert not (root / "sessions" / "sess-2").exists()
