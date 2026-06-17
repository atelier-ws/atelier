from __future__ import annotations

import sqlite3
from pathlib import Path

from atelier.core.foundation.store import ContextStore
from atelier.infra.storage.migrations import V2_REQUIRED_TABLES
from atelier.infra.storage.sqlite_store import SQLiteStore


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE '%_config'"
        ).fetchall()
    return {row[0] for row in rows}


def test_v2_migrations_apply_idempotently_for_reasoning_store(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "atelier")
    store.init()
    store.init()

    assert set(V2_REQUIRED_TABLES).issubset(_tables(store.db_path))
    assert store.verify_v2_schema()


def test_v2_migrations_apply_idempotently_for_sqlite_store(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "atelier")
    store.init()
    store.init()

    assert set(V2_REQUIRED_TABLES).issubset(_tables(store.db_path))
    assert store.health_check()["ok"] is True


_LEGACY_REASONBLOCKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS reasonblocks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    usage_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reasonblocks_domain ON reasonblocks(domain);
CREATE INDEX IF NOT EXISTS idx_reasonblocks_status ON reasonblocks(status);
CREATE VIRTUAL TABLE IF NOT EXISTS reasonblocks_fts USING fts5(
    id UNINDEXED, title, triggers, situation, dead_ends, procedure, failure_signals,
    tokenize = 'porter'
);
"""


def _seed_legacy_reasonblocks_db(root: Path) -> Path:
    """Create a pre-v3 database whose playbooks live in ``reasonblocks``."""
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "atelier.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_LEGACY_REASONBLOCKS_SCHEMA)
        conn.execute(
            "INSERT INTO reasonblocks (id, title, domain, status, created_at, updated_at, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy-1", "Legacy playbook", "coding", "active", "2026-01-01", "2026-01-01", "{}"),
        )
        conn.execute(
            "INSERT INTO reasonblocks_fts (id, title) VALUES (?, ?)",
            ("legacy-1", "Legacy playbook"),
        )
        conn.commit()
    return db_path


def test_playbook_rename_migration_preserves_existing_rows(tmp_path: Path) -> None:
    root = tmp_path / "atelier"
    db_path = _seed_legacy_reasonblocks_db(root)

    store = ContextStore(root)
    store.init()

    tables = _tables(db_path)
    # Legacy table renamed in place; no orphaned old table, no empty duplicate.
    assert "playbooks" in tables
    assert "reasonblocks" not in tables
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT id, title FROM playbooks").fetchall()
        fts_rows = conn.execute("SELECT id FROM playbooks_fts").fetchall()
        legacy_indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_reasonblocks_%'"
        ).fetchall()
    assert rows == [("legacy-1", "Legacy playbook")]  # the real row survived
    assert ("legacy-1",) in fts_rows  # FTS rows migrated with the table
    assert legacy_indexes == []  # legacy indexes dropped
    assert store.verify_v2_schema()


def test_playbook_rename_migration_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "atelier"
    _seed_legacy_reasonblocks_db(root)

    store = ContextStore(root)
    store.init()
    # A second init() (already-migrated DB) must not raise or duplicate data.
    store.init()

    with sqlite3.connect(root / "atelier.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM playbooks").fetchone()[0]
    assert count == 1


def test_playbook_rename_migration_is_noop_on_fresh_db(tmp_path: Path) -> None:
    # Fresh DB never had ``reasonblocks``; the guarded migration is a no-op and
    # init() succeeds with the greenfield playbooks table.
    store = ContextStore(tmp_path / "atelier")
    store.init()
    tables = _tables(store.db_path)
    assert "playbooks" in tables
    assert "reasonblocks" not in tables
