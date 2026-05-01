"""Persistent storage for ReasonBlocks, traces, and rubrics.

Backend: SQLite + FTS5 (no external services).

Design:
- One table per entity, JSON column for the full payload.
- A contentless FTS5 mirror table for ReasonBlocks for fast lookup by
  title / triggers / situation / dead_ends / procedure.
- Markdown copies of blocks live under <root>/blocks/ for human review
  and version control. Traces are mirrored under <root>/traces/.
- Redacted raw artifacts live under <root>/raw/ and are linked from traces
  when a host import preserves more detail than the curated Trace schema.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from atelier.core.foundation.models import (
    BlockStatus,
    RawArtifact,
    ReasonBlock,
    Rubric,
    Trace,
    to_jsonable,
)

# --------------------------------------------------------------------------- #
# Schema                                                                      #
# --------------------------------------------------------------------------- #

SCHEMA = """
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
    id UNINDEXED,
    title,
    triggers,
    situation,
    dead_ends,
    procedure,
    failure_signals,
    tokenize = 'porter'
);

CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    task TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_domain ON traces(domain);
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status);

CREATE TABLE IF NOT EXISTS raw_artifacts (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_path TEXT NOT NULL,
    sha256_original TEXT NOT NULL,
    sha256_redacted TEXT NOT NULL,
    byte_count_original INTEGER NOT NULL,
    byte_count_redacted INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    source_file_mtime TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_artifacts_source_session
    ON raw_artifacts(source, source_session_id);

CREATE TABLE IF NOT EXISTS rubrics (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


# --------------------------------------------------------------------------- #
# Store                                                                       #
# --------------------------------------------------------------------------- #


class ReasoningStore:
    """SQLite-backed store. Single-process, single-writer.

    The store is also responsible for mirroring blocks/traces to the filesystem
    so they can be reviewed in PRs without running tools.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.db_path = self.root / "atelier.db"
        self.blocks_dir = self.root / "blocks"
        self.traces_dir = self.root / "traces"
        self.rubrics_dir = self.root / "rubrics"
        self.raw_dir = self.root / "raw"

    # ----- lifecycle ------------------------------------------------------- #

    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.blocks_dir.mkdir(exist_ok=True)
        self.traces_dir.mkdir(exist_ok=True)
        self.rubrics_dir.mkdir(exist_ok=True)
        self.raw_dir.mkdir(exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            # Ensure source_file_mtime column exists (migration for existing DBs)
            import contextlib

            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE raw_artifacts ADD COLUMN source_file_mtime TEXT")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    # ----- ReasonBlocks ---------------------------------------------------- #

    def upsert_block(self, block: ReasonBlock, *, write_markdown: bool = True) -> None:
        payload = json.dumps(to_jsonable(block), ensure_ascii=False)
        with self._connect() as conn, closing(conn.cursor()) as cur:
            cur.execute(
                """
                INSERT INTO reasonblocks (
                    id, title, domain, status,
                    usage_count, success_count, failure_count,
                    created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    domain=excluded.domain,
                    status=excluded.status,
                    usage_count=excluded.usage_count,
                    success_count=excluded.success_count,
                    failure_count=excluded.failure_count,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    block.id,
                    block.title,
                    block.domain,
                    block.status,
                    block.usage_count,
                    block.success_count,
                    block.failure_count,
                    block.created_at.isoformat(),
                    block.updated_at.isoformat(),
                    payload,
                ),
            )
            cur.execute("DELETE FROM reasonblocks_fts WHERE id = ?", (block.id,))
            cur.execute(
                """
                INSERT INTO reasonblocks_fts (
                    id, title, triggers, situation, dead_ends, procedure, failure_signals
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    block.id,
                    block.title,
                    " ; ".join(block.triggers),
                    block.situation,
                    " ; ".join(block.dead_ends),
                    " ; ".join(block.procedure),
                    " ; ".join(block.failure_signals),
                ),
            )
        if write_markdown:
            self._write_block_markdown(block)

    def get_block(self, block_id: str) -> ReasonBlock | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM reasonblocks WHERE id = ?", (block_id,)
            ).fetchone()
        if row is None:
            return None
        return ReasonBlock.model_validate_json(row["payload"])

    def list_blocks(
        self,
        *,
        domain: str | None = None,
        status: BlockStatus | None = "active",
        include_deprecated: bool = False,
    ) -> list[ReasonBlock]:
        sql = "SELECT payload FROM reasonblocks WHERE 1=1"
        params: list[Any] = []
        if domain:
            sql += " AND domain = ?"
            params.append(domain)
        if status and not include_deprecated:
            sql += " AND status = ?"
            params.append(status)
        elif not include_deprecated:
            sql += " AND status != 'quarantined'"
        sql += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [ReasonBlock.model_validate_json(r["payload"]) for r in rows]

    def search_blocks(self, query: str, *, limit: int = 20) -> list[ReasonBlock]:
        if not query.strip():
            return self.list_blocks()[:limit]
        # Use FTS5 MATCH with safe quoting (escape internal double quotes).
        safe = query.replace('"', '""')
        sql = (
            "SELECT r.payload FROM reasonblocks_fts f "
            "JOIN reasonblocks r ON r.id = f.id "
            "WHERE reasonblocks_fts MATCH ? "
            "AND r.status != 'quarantined' "
            "ORDER BY rank LIMIT ?"
        )
        with self._connect() as conn:
            rows = conn.execute(sql, (f'"{safe}"', limit)).fetchall()
        return [ReasonBlock.model_validate_json(r["payload"]) for r in rows]

    def update_block_status(self, block_id: str, status: BlockStatus) -> bool:
        with self._connect() as conn, closing(conn.cursor()) as cur:
            cur.execute(
                "UPDATE reasonblocks SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now(UTC).isoformat(), block_id),
            )
            changed = cur.rowcount > 0
        if changed:
            block = self.get_block(block_id)
            if block:
                self._write_block_markdown(block)
        return changed

    def increment_usage(
        self,
        block_id: str,
        *,
        success: bool | None = None,
    ) -> None:
        with self._connect() as conn, closing(conn.cursor()) as cur:
            cur.execute(
                "UPDATE reasonblocks SET usage_count = usage_count + 1 WHERE id = ?",
                (block_id,),
            )
            if success is True:
                cur.execute(
                    "UPDATE reasonblocks SET success_count = success_count + 1 WHERE id = ?",
                    (block_id,),
                )
            elif success is False:
                cur.execute(
                    "UPDATE reasonblocks SET failure_count = failure_count + 1 WHERE id = ?",
                    (block_id,),
                )

    # ----- Traces ---------------------------------------------------------- #

    def record_trace(self, trace: Trace, *, write_json: bool = True) -> None:
        payload = json.dumps(to_jsonable(trace), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO traces (id, agent, domain, status, task, created_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    payload = excluded.payload
                """,
                (
                    trace.id,
                    trace.agent,
                    trace.domain,
                    trace.status,
                    trace.task,
                    trace.created_at.isoformat(),
                    payload,
                ),
            )
        if write_json:
            self._write_trace_json(trace)

    def get_trace(self, trace_id: str) -> Trace | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM traces WHERE id = ?", (trace_id,)).fetchone()
        if row is None:
            return None
        return Trace.model_validate_json(row["payload"])

    def list_traces(
        self,
        *,
        domain: str | None = None,
        status: str | None = None,
        agent: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Trace]:
        sql = "SELECT payload FROM traces WHERE 1=1"
        params: list[Any] = []
        if domain:
            sql += " AND domain = ?"
            params.append(domain)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(offset)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Trace.model_validate_json(r["payload"]) for r in rows]

    # ----- Raw artifacts -------------------------------------------------- #

    def record_raw_artifact(self, artifact: RawArtifact, content: str) -> None:
        payload = json.dumps(to_jsonable(artifact), ensure_ascii=False)
        with self._connect() as conn:

            conn.execute(
                """
                INSERT INTO raw_artifacts (
                    id, source, source_session_id, kind, relative_path,
                    content_path, sha256_original, sha256_redacted,
                    byte_count_original, byte_count_redacted,
                    created_at, source_file_mtime, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source = excluded.source,
                    source_session_id = excluded.source_session_id,
                    kind = excluded.kind,
                    relative_path = excluded.relative_path,
                    content_path = excluded.content_path,
                    sha256_original = excluded.sha256_original,
                    sha256_redacted = excluded.sha256_redacted,
                    byte_count_original = excluded.byte_count_original,
                    byte_count_redacted = excluded.byte_count_redacted,
                    source_file_mtime = excluded.source_file_mtime,
                    payload = excluded.payload
                """,
                (
                    artifact.id,
                    artifact.source,
                    artifact.source_session_id,
                    artifact.kind,
                    artifact.relative_path,
                    artifact.content_path,
                    artifact.sha256_original,
                    artifact.sha256_redacted,
                    artifact.byte_count_original,
                    artifact.byte_count_redacted,
                    artifact.created_at.isoformat(),
                    artifact.source_file_mtime.isoformat() if artifact.source_file_mtime else None,
                    payload,
                ),
            )
        self._write_raw_artifact(artifact, content)

    def get_raw_artifact(self, artifact_id: str) -> RawArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM raw_artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            return None
        return RawArtifact.model_validate_json(row["payload"])

    def list_raw_artifacts(
        self,
        *,
        source: str | None = None,
        source_session_id: str | None = None,
        limit: int = 100,
    ) -> list[RawArtifact]:
        sql = "SELECT payload FROM raw_artifacts WHERE 1=1"
        params: list[Any] = []
        if source:
            sql += " AND source = ?"
            params.append(source)
        if source_session_id:
            sql += " AND source_session_id = ?"
            params.append(source_session_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [RawArtifact.model_validate_json(r["payload"]) for r in rows]

    def read_raw_artifact_content(self, artifact: RawArtifact) -> str:
        return self._artifact_path(artifact).read_text(encoding="utf-8")

    # ----- Rubrics --------------------------------------------------------- #

    def upsert_rubric(self, rubric: Rubric, *, write_yaml: bool = True) -> None:
        payload = json.dumps(to_jsonable(rubric), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rubrics (id, domain, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    domain = excluded.domain,
                    payload = excluded.payload
                """,
                (rubric.id, rubric.domain, payload),
            )
        if write_yaml:
            self._write_rubric_yaml(rubric)

    def get_rubric(self, rubric_id: str) -> Rubric | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM rubrics WHERE id = ?", (rubric_id,)).fetchone()
        if row is None:
            return None
        return Rubric.model_validate_json(row["payload"])

    def list_rubrics(self, *, domain: str | None = None) -> list[Rubric]:
        sql = "SELECT payload FROM rubrics"
        params: list[Any] = []
        if domain:
            sql += " WHERE domain = ?"
            params.append(domain)
        sql += " ORDER BY id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Rubric.model_validate_json(r["payload"]) for r in rows]

    # ----- File mirrors ---------------------------------------------------- #

    def _write_block_markdown(self, block: ReasonBlock) -> None:
        path = self.blocks_dir / f"{block.id}.md"
        from atelier.core.foundation.renderer import render_block_markdown

        path.write_text(render_block_markdown(block), encoding="utf-8")

    def _write_trace_json(self, trace: Trace) -> None:
        path = self.traces_dir / f"{trace.id}.json"
        path.write_text(
            json.dumps(to_jsonable(trace), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_rubric_yaml(self, rubric: Rubric) -> None:
        path = self.rubrics_dir / f"{rubric.id}.yaml"
        path.write_text(
            yaml.safe_dump(to_jsonable(rubric), sort_keys=False),
            encoding="utf-8",
        )

    def _write_raw_artifact(self, artifact: RawArtifact, content: str) -> None:
        path = self._artifact_path(artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _artifact_path(self, artifact: RawArtifact) -> Path:
        path = (self.root / artifact.content_path).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError(f"raw artifact path escapes store root: {artifact.content_path}")
        return path

    # ----- Bulk import ---------------------------------------------------- #

    def import_blocks(self, blocks: Iterable[ReasonBlock]) -> int:
        n = 0
        for b in blocks:
            self.upsert_block(b)
            n += 1
        return n

    def import_rubrics(self, rubrics: Iterable[Rubric]) -> int:
        n = 0
        for r in rubrics:
            self.upsert_rubric(r)
            n += 1
        return n
