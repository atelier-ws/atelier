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

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

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
    files_json      TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_trace_index_session ON trace_index(session_id);
CREATE INDEX IF NOT EXISTS idx_trace_index_domain ON trace_index(domain);
CREATE INDEX IF NOT EXISTS idx_trace_index_created ON trace_index(created_at);
CREATE VIRTUAL TABLE IF NOT EXISTS trace_search USING fts5(id UNINDEXED, document);
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
        return conn

    def _index_trace(self, conn: sqlite3.Connection, trace: dict[str, Any], session_id: str) -> None:
        values = {field: trace.get(field) for field in _INDEXED_FIELDS}
        conn.execute(
            """
            INSERT INTO trace_index (
                id, session_id, agent, host, domain, status, task, workspace_path,
                created_at, input_tokens, output_tokens, cached_input_tokens, files_json
            ) VALUES (
                :id, :session_id, :agent, :host, :domain, :status, :task, :workspace_path,
                :created_at, :input_tokens, :output_tokens, :cached_input_tokens, :files_json
            )
            ON CONFLICT(id) DO UPDATE SET
                session_id=excluded.session_id, agent=excluded.agent, host=excluded.host,
                domain=excluded.domain, status=excluded.status, task=excluded.task,
                workspace_path=excluded.workspace_path, created_at=excluded.created_at,
                input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens,
                cached_input_tokens=excluded.cached_input_tokens, files_json=excluded.files_json
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
        path = self._traces_path(session_id)
        existing: list[dict[str, Any]] = []
        if path.exists():
            existing = [t for t in self._read_jsonl(path) if t.get("id") != trace["id"]]
        existing.append(trace)
        path.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in existing), encoding="utf-8")

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
        return out

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

    def rebuild_index(self) -> int:
        """Rebuild the index from the session files (the source of truth)."""
        with closing(self._connect_index()) as conn:
            conn.execute("DELETE FROM trace_index")
            conn.execute("DELETE FROM trace_search")
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
            conn.commit()
        return count
