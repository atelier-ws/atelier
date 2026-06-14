"""File-based session store — sessions are folders, not database rows.

A session transcript is inherently a file, so persisting full traces in SQLite
is the wrong design (it bloats atelier.db without being a source of truth). Here
each session lives at ``<root>/sessions/<session_id>/``::

    meta.json      session metadata (host, workspace, title, timestamps, cost, trace ids)
    traces.jsonl   append-only full Trace payloads (one JSON object per line)

A tiny, fully-derivable index (``<root>/sessions/index.db``) holds per-trace
metadata plus a short search document for aggregate queries and search — never
the full payloads, which stay in the files. ``rebuild_index`` reconstructs the
index from the files at any time, so the files remain the single source of truth.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from atelier.core.foundation.models import RawArtifact

_INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_index (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    agent           TEXT,
    host            TEXT,
    domain          TEXT,
    status          TEXT,
    task            TEXT,
    workspace_path  TEXT,
    created_at      TEXT,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cached_input_tokens INTEGER DEFAULT 0,
    thinking_tokens INTEGER DEFAULT 0,
    model           TEXT,
    files_json      TEXT DEFAULT '[]',
    synced_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_trace_index_session ON trace_index(session_id);
CREATE INDEX IF NOT EXISTS idx_trace_index_domain ON trace_index(domain);
CREATE INDEX IF NOT EXISTS idx_trace_index_created ON trace_index(created_at);
CREATE VIRTUAL TABLE IF NOT EXISTS trace_search USING fts5(id UNINDEXED, document);

CREATE TABLE IF NOT EXISTS raw_artifacts (
    id                 TEXT PRIMARY KEY,
    session_id         TEXT NOT NULL,
    source             TEXT NOT NULL,
    source_session_id  TEXT NOT NULL,
    kind               TEXT,
    source_file_mtime  TEXT,
    created_at         TEXT,
    payload            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_artifacts_source ON raw_artifacts(source, source_session_id);
"""

_INDEXED_FIELDS = (
    "agent",
    "host",
    "domain",
    "status",
    "task",
    "workspace_path",
    "created_at",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "thinking_tokens",
    "model",
)


def _search_document(trace: dict[str, Any]) -> str:
    """Short, low-cardinality searchable text — NOT the full reasoning/tool blob
    that bloated the old traces_fts index."""
    parts: list[str] = [str(trace.get("task") or ""), str(trace.get("output_summary") or "")]
    parts.extend(str(f) for f in (trace.get("files_touched") or []))
    for tool in trace.get("tools_called") or []:
        if isinstance(tool, dict):
            parts.append(str(tool.get("name") or ""))
    return "\n".join(p for p in parts if p)


def _session_id_of(trace: dict[str, Any]) -> str:
    return str(trace.get("session_id") or trace.get("id") or "unknown")


def _dedupe_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse append-only JSONL lines to one entry per ``id`` (last write wins).

    Writers only ever append, so a file may carry several physical lines for the
    same id. Readers reconcile here: the newest line for an id replaces earlier
    ones in place, preserving first-seen order. Entries without a string id pass
    through untouched.
    """
    position: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for item in items:
        key = item.get("id") if isinstance(item, dict) else None
        if not isinstance(key, str):
            out.append(item)
            continue
        if key in position:
            out[position[key]] = item
        else:
            position[key] = len(out)
            out.append(item)
    return out


class SessionStore:
    """Per-session folders + a tiny derivable index."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.index_path = self.sessions_dir / "index.db"

    # ----- paths -----------------------------------------------------------
    def session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def _traces_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "traces.jsonl"

    def _meta_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "meta.json"

    # ----- index -----------------------------------------------------------
    def _connect_index(self) -> sqlite3.Connection:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.index_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_INDEX_SCHEMA)
        # Idempotent migrations for index.db files created before these columns.
        for ddl in (
            "ALTER TABLE trace_index ADD COLUMN synced_at TEXT",
            "ALTER TABLE trace_index ADD COLUMN thinking_tokens INTEGER DEFAULT 0",
            "ALTER TABLE trace_index ADD COLUMN model TEXT",
        ):
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(ddl)
        return conn

    def _index_trace(self, conn: sqlite3.Connection, trace: dict[str, Any], session_id: str) -> None:
        values = {field: trace.get(field) for field in _INDEXED_FIELDS}
        conn.execute(
            """
            INSERT INTO trace_index (
                id, session_id, agent, host, domain, status, task, workspace_path,
                created_at, input_tokens, output_tokens, cached_input_tokens,
                thinking_tokens, model, files_json
            ) VALUES (
                :id, :session_id, :agent, :host, :domain, :status, :task, :workspace_path,
                :created_at, :input_tokens, :output_tokens, :cached_input_tokens,
                :thinking_tokens, :model, :files_json
            )
            ON CONFLICT(id) DO UPDATE SET
                session_id=excluded.session_id, agent=excluded.agent, host=excluded.host,
                domain=excluded.domain, status=excluded.status, task=excluded.task,
                workspace_path=excluded.workspace_path, created_at=excluded.created_at,
                input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens,
                cached_input_tokens=excluded.cached_input_tokens,
                thinking_tokens=excluded.thinking_tokens, model=excluded.model,
                files_json=excluded.files_json
            """,
            {
                "id": trace["id"],
                "session_id": session_id,
                "agent": values["agent"],
                "host": values["host"],
                "domain": values["domain"],
                "status": values["status"],
                "task": values["task"],
                "workspace_path": values["workspace_path"],
                "created_at": values["created_at"],
                "input_tokens": int(values["input_tokens"] or 0),
                "output_tokens": int(values["output_tokens"] or 0),
                "cached_input_tokens": int(values["cached_input_tokens"] or 0),
                "thinking_tokens": int(values["thinking_tokens"] or 0),
                "model": values["model"],
                "files_json": json.dumps(trace.get("files_touched") or []),
            },
        )
        conn.execute("DELETE FROM trace_search WHERE id = ?", (trace["id"],))
        conn.execute(
            "INSERT INTO trace_search (id, document) VALUES (?, ?)",
            (trace["id"], _search_document(trace)),
        )

    # ----- write -----------------------------------------------------------
    def record(self, trace: dict[str, Any]) -> str:
        """Append a trace payload to its session file and update the index.

        Returns the session_id the trace was filed under. Idempotent per trace id
        (re-recording replaces the prior line for that id in the session file).
        """
        session_id = _session_id_of(trace)
        self.session_dir(session_id).mkdir(parents=True, exist_ok=True)
        self._append_trace_line(session_id, trace)
        self._update_meta(session_id, trace)
        with closing(self._connect_index()) as conn:
            self._index_trace(conn, trace, session_id)
            conn.commit()
        return session_id

    def _append_trace_line(self, session_id: str, trace: dict[str, Any]) -> None:
        # Append-only: never rewrite the file. A full rewrite is O(n) per trace and
        # loses any trace appended concurrently by another writer. Re-recording an id
        # just appends a newer line; _read_jsonl -> _dedupe_by_id collapses to last
        # write wins, and a torn final line is skipped on read.
        with self._traces_path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trace, ensure_ascii=False) + "\n")

    def _update_meta(self, session_id: str, trace: dict[str, Any]) -> None:
        meta = self.meta(session_id) or {
            "session_id": session_id,
            "host": trace.get("host"),
            "workspace_path": trace.get("workspace_path"),
            "title": trace.get("session_title"),
            "created_at": trace.get("created_at"),
            "trace_ids": [],
        }
        trace_ids = [tid for tid in meta.get("trace_ids", []) if tid != trace["id"]]
        trace_ids.append(trace["id"])
        meta["trace_ids"] = trace_ids
        meta["updated_at"] = trace.get("created_at")
        meta["title"] = meta.get("title") or trace.get("session_title")
        self._meta_path(session_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ----- read ------------------------------------------------------------
    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            text = path.read_text("utf-8")
        except OSError:
            return out
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return _dedupe_by_id(out)

    def meta(self, session_id: str) -> dict[str, Any] | None:
        path = self._meta_path(session_id)
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def traces_for(self, session_id: str) -> list[dict[str, Any]]:
        return self._read_jsonl(self._traces_path(session_id))

    def get(self, trace_id: str) -> dict[str, Any] | None:
        with closing(self._connect_index()) as conn:
            row = conn.execute("SELECT session_id FROM trace_index WHERE id = ?", (trace_id,)).fetchone()
        if row is None:
            return None
        for trace in self.traces_for(str(row["session_id"])):
            if trace.get("id") == trace_id:
                return trace
        return None

    def query(
        self,
        *,
        domain: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with closing(self._connect_index()) as conn:
            rows = conn.execute(f"SELECT * FROM trace_index{where} ORDER BY created_at DESC LIMIT ?", params).fetchall()
        return [dict(row) for row in rows]

    def search(self, text: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        with closing(self._connect_index()) as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT t.* FROM trace_search s JOIN trace_index t ON t.id = s.id
                    WHERE trace_search MATCH ? ORDER BY rank LIMIT ?
                    """,
                    (text, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(row) for row in rows]

    def exists(self, trace_id: str) -> bool:
        with closing(self._connect_index()) as conn:
            return conn.execute("SELECT 1 FROM trace_index WHERE id = ?", (trace_id,)).fetchone() is not None

    def delete(self, trace_id: str) -> None:
        with closing(self._connect_index()) as conn:
            row = conn.execute("SELECT session_id FROM trace_index WHERE id = ?", (trace_id,)).fetchone()
            conn.execute("DELETE FROM trace_index WHERE id = ?", (trace_id,))
            conn.execute("DELETE FROM trace_search WHERE id = ?", (trace_id,))
            conn.commit()
        if row is None:
            return
        path = self._traces_path(str(row["session_id"]))
        if path.exists():
            kept = [t for t in self._read_jsonl(path) if t.get("id") != trace_id]
            path.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in kept), encoding="utf-8")

    # ----- raw artifacts ---------------------------------------------------
    def _raw_meta_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "raw_artifacts.jsonl"

    def _artifact_content_path(self, artifact: RawArtifact) -> Path:
        base = self.session_dir(artifact.source_session_id).resolve()
        path = (base / artifact.content_path).resolve()
        if base not in path.parents and path != base:
            raise ValueError(f"raw artifact path escapes session dir: {artifact.content_path}")
        return path

    def _index_raw_artifact(self, conn: sqlite3.Connection, payload: dict[str, Any], session_id: str) -> None:
        conn.execute(
            """
            INSERT INTO raw_artifacts (
                id, session_id, source, source_session_id, kind, source_file_mtime, created_at, payload
            ) VALUES (
                :id, :session_id, :source, :source_session_id, :kind, :source_file_mtime, :created_at, :payload
            )
            ON CONFLICT(id) DO UPDATE SET
                session_id=excluded.session_id, source=excluded.source,
                source_session_id=excluded.source_session_id, kind=excluded.kind,
                source_file_mtime=excluded.source_file_mtime, created_at=excluded.created_at,
                payload=excluded.payload
            """,
            {
                "id": payload["id"],
                "session_id": session_id,
                "source": payload.get("source"),
                "source_session_id": payload.get("source_session_id"),
                "kind": payload.get("kind"),
                "source_file_mtime": payload.get("source_file_mtime"),
                "created_at": payload.get("created_at"),
                "payload": json.dumps(payload, ensure_ascii=False),
            },
        )

    def record_raw_artifact(self, artifact: RawArtifact, content: str) -> None:
        """Persist a raw artifact's content + metadata under its session folder.

        Content lives at ``sessions/<sid>/<content_path>`` (source of truth for the
        bytes); metadata is appended to ``sessions/<sid>/raw_artifacts.jsonl`` (source
        of truth for the record); a derivable row is upserted into the index.
        """
        session_id = artifact.source_session_id or "unknown"
        self.session_dir(session_id).mkdir(parents=True, exist_ok=True)
        content_file = self._artifact_content_path(artifact)
        content_file.parent.mkdir(parents=True, exist_ok=True)
        content_file.write_text(content, encoding="utf-8")
        payload = artifact.model_dump(mode="json")
        meta_path = self._raw_meta_path(session_id)
        # Append-only metadata; readers dedupe by id (last write wins).
        with meta_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        with closing(self._connect_index()) as conn:
            self._index_raw_artifact(conn, payload, session_id)
            conn.commit()

    def get_raw_artifact(self, artifact_id: str) -> RawArtifact | None:
        with closing(self._connect_index()) as conn:
            row = conn.execute("SELECT payload FROM raw_artifacts WHERE id = ?", (artifact_id,)).fetchone()
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
        with closing(self._connect_index()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [RawArtifact.model_validate_json(r["payload"]) for r in rows]

    def read_raw_artifact_content(self, artifact: RawArtifact) -> str:
        return self._artifact_content_path(artifact).read_text(encoding="utf-8")

    # ----- sync tracking ---------------------------------------------------
    def mark_synced(self, session_id: str, *, at: str) -> None:
        with closing(self._connect_index()) as conn:
            conn.execute("UPDATE trace_index SET synced_at = ? WHERE session_id = ?", (at, session_id))
            conn.commit()

    def unsynced_ids(self, limit: int = 500) -> list[str]:
        with closing(self._connect_index()) as conn:
            rows = conn.execute(
                "SELECT id FROM trace_index WHERE synced_at IS NULL ORDER BY created_at LIMIT ?", (limit,)
            ).fetchall()
        return [str(row["id"]) for row in rows]

    # ----- aggregates ------------------------------------------------------
    def _filter_sql(
        self,
        *,
        domain: str | None,
        status: str | None,
        agent: str | None,
        host: str | None,
        since: str | None,
        exclude_tasks: tuple[str, ...],
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("domain", domain), ("status", status), ("agent", agent), ("host", host)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        for task in exclude_tasks:
            clauses.append("task IS NOT ?")
            params.append(task)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def metrics(
        self,
        *,
        domain: str | None = None,
        agent: str | None = None,
        host: str | None = None,
        since: str | None = None,
        exclude_tasks: tuple[str, ...] = ("session-auto-record",),
    ) -> dict[str, Any]:
        where, params = self._filter_sql(
            domain=domain, status=None, agent=agent, host=host, since=since, exclude_tasks=exclude_tasks
        )
        stats: dict[str, Any] = {"total": 0, "success": 0, "failed": 0, "partial": 0}
        with closing(self._connect_index()) as conn:
            for row in conn.execute(f"SELECT status, COUNT(*) AS c FROM trace_index{where} GROUP BY status", params):
                count = int(row["c"])
                stats["total"] += count
                key = str(row["status"] or "")
                if key in stats:
                    stats[key] = count
            stats["hosts"] = [
                r["host"] for r in conn.execute(f"SELECT DISTINCT host FROM trace_index{where}", params) if r["host"]
            ]
            stats["agents"] = [
                r["agent"] for r in conn.execute(f"SELECT DISTINCT agent FROM trace_index{where}", params) if r["agent"]
            ]
            stats["domains"] = [
                r["domain"]
                for r in conn.execute(f"SELECT DISTINCT domain FROM trace_index{where}", params)
                if r["domain"]
            ]
        return stats

    def list_full(
        self,
        *,
        domain: str | None = None,
        status: str | None = None,
        agent: str | None = None,
        host: str | None = None,
        query: str | None = None,
        since: str | None = None,
        limit: int = 100,
        offset: int = 0,
        exclude_tasks: tuple[str, ...] = ("session-auto-record",),
    ) -> list[dict[str, Any]]:
        """Return full trace payloads (from the files) matching the filters."""
        where, params = self._filter_sql(
            domain=domain, status=status, agent=agent, host=host, since=since, exclude_tasks=exclude_tasks
        )
        with closing(self._connect_index()) as conn:
            if query and query.strip():
                rows = conn.execute(
                    f"""
                    SELECT t.id, t.session_id FROM trace_search s JOIN trace_index t ON t.id = s.id
                    {where.replace("WHERE", "WHERE trace_search MATCH ? AND") if where else "WHERE trace_search MATCH ?"}
                    ORDER BY rank LIMIT ? OFFSET ?
                    """,
                    [query, *params, limit, offset],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT id, session_id FROM trace_index{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    [*params, limit, offset],
                ).fetchall()
        ordered_ids = [str(row["id"]) for row in rows]
        wanted = set(ordered_ids)
        # Load full payloads, reading each session file at most once.
        by_session: dict[str, list[str]] = {}
        for row in rows:
            by_session.setdefault(str(row["session_id"]), []).append(str(row["id"]))
        loaded: dict[str, dict[str, Any]] = {}
        for session_id, ids in by_session.items():
            ids_set = set(ids)
            for trace in self.traces_for(session_id):
                tid = trace.get("id")
                if tid in ids_set and tid in wanted:
                    loaded[str(tid)] = trace
        return [loaded[tid] for tid in ordered_ids if tid in loaded]

    def token_rows(
        self,
        *,
        since: str | None = None,
        exclude_tasks: tuple[str, ...] = ("session-auto-record",),
    ) -> list[dict[str, Any]]:
        """Lightweight per-trace token/host/model rows for cost aggregates (index-only).

        Excludes ``session-auto-record`` meta traces by default, matching
        ``list_full``/``metrics`` so token totals and run counts cover the same
        population. (The auto-record trace carries no numeric tokens — its token
        figures live in ``output_summary`` text — so it only inflated run counts.)
        """
        where, params = self._filter_sql(
            domain=None, status=None, agent=None, host=None, since=since, exclude_tasks=exclude_tasks
        )
        with closing(self._connect_index()) as conn:
            rows = conn.execute(
                "SELECT id, host, model, input_tokens, output_tokens, cached_input_tokens, thinking_tokens "
                f"FROM trace_index{where}",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def rebuild_index(self) -> int:
        """Rebuild the index from the session files (the source of truth)."""
        with closing(self._connect_index()) as conn:
            conn.execute("DELETE FROM trace_index")
            conn.execute("DELETE FROM trace_search")
            conn.execute("DELETE FROM raw_artifacts")
            count = 0
            if self.sessions_dir.exists():
                for session_path in self.sessions_dir.iterdir():
                    if not session_path.is_dir():
                        continue
                    for trace in self._read_jsonl(session_path / "traces.jsonl"):
                        if "id" not in trace:
                            continue
                        self._index_trace(conn, trace, _session_id_of(trace))
                        count += 1
                    for payload in self._read_jsonl(session_path / "raw_artifacts.jsonl"):
                        if "id" not in payload:
                            continue
                        self._index_raw_artifact(conn, payload, session_path.name)
            conn.commit()
        return count
