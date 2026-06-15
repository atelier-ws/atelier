from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from atelier.core.foundation.models import RawArtifact
from atelier.core.foundation.session_store import SessionStore
from atelier.core.foundation.store import ContextStore


def _artifact(
    artifact_id: str,
    *,
    source: str = "claude",
    source_session_id: str = "sess1",
    kind: str = "transcript",
    content_path: str | None = None,
) -> RawArtifact:
    rel = f"{artifact_id}.jsonl"
    return RawArtifact(
        id=artifact_id,
        source=source,
        source_session_id=source_session_id,
        kind=kind,
        relative_path=rel,
        content_path=content_path or f"raw/{source}/{source_session_id}/{rel}",
        sha256_original="0" * 64,
        sha256_redacted="1" * 64,
        byte_count_original=10,
        byte_count_redacted=8,
    )


def test_record_get_roundtrip_and_content(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    art = _artifact("claude-ws-sess1")
    store.record_raw_artifact(art, "hello redacted body")

    fetched = store.get_raw_artifact("claude-ws-sess1")
    assert fetched is not None
    assert fetched.id == art.id
    assert fetched.source_session_id == "sess1"
    assert store.read_raw_artifact_content(fetched) == "hello redacted body"


def test_content_and_metadata_live_under_session_dir(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    art = _artifact("claude-ws-sess1")
    store.record_raw_artifact(art, "body")

    session_dir = tmp_path / "sessions" / "sess1"
    assert (session_dir / "raw" / "claude" / "sess1" / "claude-ws-sess1.jsonl").read_text() == "body"
    assert (session_dir / "raw_artifacts.jsonl").exists()
    # nothing is written to a top-level root/raw dir anymore
    assert not (tmp_path / "raw").exists()


def test_record_is_idempotent_per_id(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record_raw_artifact(_artifact("a1"), "v1")
    store.record_raw_artifact(_artifact("a1"), "v2")  # same id; appends a newer line
    assert store.read_raw_artifact_content(store.get_raw_artifact("a1")) == "v2"
    meta_lines = [
        line
        for line in (tmp_path / "sessions" / "sess1" / "raw_artifacts.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(meta_lines) == 2  # append-only file keeps both physical lines
    assert len(store.list_raw_artifacts(source_session_id="sess1")) == 1  # reader dedupes by id


def test_list_filters_by_source_and_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record_raw_artifact(_artifact("a1", source="claude", source_session_id="s1"), "x")
    store.record_raw_artifact(_artifact("a2", source="codex", source_session_id="s2"), "y")

    assert {a.id for a in store.list_raw_artifacts()} == {"a1", "a2"}
    assert [a.id for a in store.list_raw_artifacts(source="codex")] == ["a2"]
    assert [a.id for a in store.list_raw_artifacts(source_session_id="s1")] == ["a1"]


def test_rebuild_index_repopulates_raw_artifacts(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.record_raw_artifact(_artifact("a1", source_session_id="s1"), "x")
    # blow away the derivable index; the jsonl files remain the source of truth
    store.index_path.unlink()
    assert SessionStore(tmp_path).get_raw_artifact("a1") is None  # index lost, not yet rebuilt
    rebuilt = SessionStore(tmp_path)
    rebuilt.rebuild_index()
    fetched = rebuilt.get_raw_artifact("a1")
    assert fetched is not None and fetched.source_session_id == "s1"


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    art = _artifact("evil", content_path="../../escape.txt")
    with pytest.raises(ValueError, match="escapes session dir"):
        store.record_raw_artifact(art, "nope")


def test_path_escape_via_source_session_id_is_rejected(tmp_path: Path) -> None:
    # A dot-dot in source_session_id must not escape the sessions tree: the base
    # dir is built from the (untrusted) session id, so confinement is checked
    # against the sessions root, not the attacker-built per-session base.
    store = SessionStore(tmp_path)
    art = _artifact("evil", source_session_id="../../escape")
    with pytest.raises(ValueError, match="escapes session dir"):
        store.record_raw_artifact(art, "nope")


def test_context_store_keeps_raw_artifacts_out_of_atelier_db(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)
    store.init()
    art = _artifact("claude-ws-sess1")
    store.record_raw_artifact(art, "body")

    # retrievable through the stable ContextStore API
    assert store.get_raw_artifact("claude-ws-sess1") is not None
    assert store.read_raw_artifact_content(art) == "body"
    # ...but atelier.db no longer carries a raw_artifacts table
    with sqlite3.connect(str(tmp_path / "atelier.db")) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "raw_artifacts" not in tables
    assert (tmp_path / "sessions" / "sess1" / "raw").exists()
