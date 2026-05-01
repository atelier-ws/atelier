"""OpenCode session importer for Atelier.

Converts ``~/.local/share/opencode/opencode.db`` sessions into redacted
RawArtifacts + curated Atelier Traces.

OpenCode stores everything in a single SQLite database:

- ``session``  — id, title, directory, time_created (ms UNIX timestamp)
- ``message``  — id, session_id, time_created, data (JSON)
- ``part``     — id, message_id, session_id, time_created, data (JSON)

Relevant part types::

    {"type":"tool",  "tool":"bash",      "state":{"input":{"command":"..."}}}
    {"type":"tool",  "tool":"write",     "state":{"input":{"filePath":"..."}}}
    {"type":"tool",  "tool":"edit",      "state":{"input":{"filePath":"..."}}}
    {"type":"tool",  "tool":"multiedit", "state":{"input":{"filePath":"..."}}}
    {"type":"patch", "files":["...",]}

Lookup path::

    agent → curated Trace (fast, retrieval-friendly)
    human → RawArtifact content (full redacted JSONL for audit)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import traceback as _traceback
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atelier.core.foundation.models import (
    RawArtifact,
    ToolCall,
    Trace,
)
from atelier.core.foundation.redaction import redact
from atelier.core.foundation.store import ReasoningStore

# Tools that touch the filesystem (used to build files_touched)
_FILE_TOOLS = frozenset({"read", "glob", "grep", "rg", "write", "edit", "multiedit"})

# Default DB location
_DEFAULT_DB = Path("~/.local/share/opencode/opencode.db")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ms_to_dt(ms: int | float | None) -> datetime:
    """Convert milliseconds-since-epoch to a UTC datetime."""
    if ms is None:
        return _utcnow()
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=UTC)
    except (OSError, ValueError, OverflowError):
        return _utcnow()


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------


def find_opencode_sessions(db_path: Path | None = None) -> Iterator[dict[str, Any]]:
    """Yield one dict per session row from the OpenCode SQLite DB."""
    if db_path is None:
        db_path = _DEFAULT_DB.expanduser()
    if not db_path.is_file():
        return
    try:
        # Open read-only via URI to avoid locking the live DB
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, title, directory, time_created FROM session ORDER BY time_created"
            ).fetchall()
            for row in rows:
                yield dict(row)
        finally:
            conn.close()
    except sqlite3.Error:
        _traceback.print_exc()


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


class OpenCodeImporter:
    """Loss-preserving importer for OpenCode sessions.

    For every session in ``opencode.db``:

    1. Serialize the session's messages + parts into a newline-delimited
       JSON blob, apply Atelier redaction, and store it as a
       **RawArtifact** at ``<store_root>/raw/opencode/<session_id>.jsonl``.
    2. Parse the *redacted* blob into a compact ``Trace`` whose
       ``raw_artifact_ids`` links back to the raw artifact.

    Nothing is thrown away beyond what Atelier's redactor strips.
    """

    def __init__(self, store: ReasoningStore, db_path: Path | None = None) -> None:
        self.store = store
        self.db_path = (db_path or _DEFAULT_DB).expanduser()

    def import_all(self, db_path: Path | None = None, *, force: bool = False) -> int:
        """Import all sessions.  Returns the number successfully imported."""
        effective_db = db_path.expanduser() if db_path else self.db_path
        count = 0
        skipped = 0
        for session_row in find_opencode_sessions(effective_db):
            try:
                if self._import_session(session_row, effective_db, force=force):
                    count += 1
                else:
                    skipped += 1
            except Exception as exc:
                _traceback.print_exc()
                print(f"[atelier] skipping opencode session {session_row.get('id')}: {exc}")
        if skipped > 0:
            print(f"[atelier] {skipped} sessions already imported (skipped by dedup)")
        return count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _import_session(
        self, session_row: dict[str, Any], db_path: Path, *, force: bool = False
    ) -> bool:
        session_id: str = session_row["id"]

        # ── Timestamp-based dedup check ────────────────────────────────
        artifact_id = f"opencode-{session_id}"
        existing = self.store.get_raw_artifact(artifact_id)
        # Use time_created (ms timestamp) from DB as proxy for mtime
        session_mtime = _ms_to_dt(session_row.get("time_created"))
        if (
            not force
            and existing
            and existing.source_file_mtime
            and session_mtime <= existing.source_file_mtime
        ):
            return False  # unchanged, skip

        # ── Step 1: serialize raw data and apply redaction ──────────────────
        raw_content = self._serialize_session(session_id, db_path)
        redacted = redact(raw_content)

        artifact = RawArtifact(
            id=artifact_id,
            source="opencode",
            source_session_id=session_id,
            kind="session.jsonl",
            relative_path=f"{session_id}.jsonl",
            content_path=f"raw/opencode/{session_id}.jsonl",
            sha256_original=_sha256(raw_content),
            sha256_redacted=_sha256(redacted),
            byte_count_original=len(raw_content.encode("utf-8")),
            byte_count_redacted=len(redacted.encode("utf-8")),
            created_at=_utcnow(),
            source_file_mtime=session_mtime,
        )
        self.store.record_raw_artifact(artifact, redacted)

        # ── Step 2: build Trace from the redacted serialisation ───────────────
        tools_called: dict[str, int] = {}
        files_touched: set[str] = set()
        commands_run: list[str] = []
        reasoning_snippets: list[str] = []

        for line in redacted.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._process_part(ev, tools_called, files_touched, commands_run, reasoning_snippets)

        title: str = str(session_row.get("title") or "untitled opencode session")

        trace = Trace(
            id=f"opencode-{session_id}",
            run_id=session_id,
            agent="opencode",
            domain="coding",
            task=title[:200],
            status="success",
            files_touched=sorted(files_touched),
            tools_called=[ToolCall(name=n, args_hash="", count=c) for n, c in tools_called.items()],
            commands_run=commands_run,
            errors_seen=[],
            validation_results=[],
            raw_artifact_ids=[artifact.id],
            reasoning=reasoning_snippets,
            created_at=_ms_to_dt(session_row.get("time_created")),
        )
        self.store.record_trace(trace)

        # ── Step 3: reconstruct fully populated RunLedger ────────────────────
        # Skip if ledger reconstruction fails - don't crash the main import
        try:
            from atelier.core.service.config import cfg
            from atelier.gateway.integrations.ledger_reconstructor import LedgerReconstructor

            recon = LedgerReconstructor(root=Path(cfg.atelier_root))
            led = recon.reconstruct(
                source="opencode",
                session_id=session_id,
                raw_content=raw_content,
                task=trace.task,
            )
            led.persist()
        except Exception as e:
            print(f"[atelier] failed to reconstruct ledger for {session_id}: {e}")

        return True

    def _serialize_session(self, session_id: str, db_path: Path) -> str:
        """Export messages + parts for one session as newline-delimited JSON."""
        lines: list[str] = []
        try:
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            try:
                msgs = conn.execute(
                    "SELECT id, data FROM message WHERE session_id = ? ORDER BY time_created",
                    (session_id,),
                ).fetchall()
                for msg in msgs:
                    lines.append(
                        json.dumps(
                            {
                                "_type": "message",
                                "id": msg["id"],
                                "data": json.loads(msg["data"] or "{}"),
                            },
                            ensure_ascii=False,
                        )
                    )

                parts = conn.execute(
                    "SELECT data FROM part WHERE session_id = ? ORDER BY time_created",
                    (session_id,),
                ).fetchall()
                for part in parts:
                    lines.append(
                        json.dumps(
                            {"_type": "part", "data": json.loads(part["data"] or "{}")},
                            ensure_ascii=False,
                        )
                    )
            finally:
                conn.close()
        except sqlite3.Error:
            _traceback.print_exc()
        return "\n".join(lines)

    def _process_part(
        self,
        ev: dict[str, Any],
        tools_called: dict[str, int],
        files_touched: set[str],
        commands_run: list[str],
        reasoning_snippets: list[str],
    ) -> None:
        # Only interested in "part" events
        if ev.get("_type") != "part":
            return
        data: dict[str, Any] = ev.get("data") or {}
        ptype: str = data.get("type", "")

        # Extract reasoning from thinking blocks
        if ptype == "reasoning":
            reasoning_text = str(data.get("summary") or data.get("thought") or "")
            if reasoning_text:
                reasoning_snippets.append(reasoning_text[:500])

        if ptype == "tool":
            tool_name: str = data.get("tool", "unknown")
            tools_called[tool_name] = tools_called.get(tool_name, 0) + 1

            state: dict[str, Any] = data.get("state") or {}
            inp: dict[str, Any] = state.get("input") or {}

            if tool_name in _FILE_TOOLS:
                fp = inp.get("filePath") or inp.get("path") or inp.get("file_path")
                if fp:
                    files_touched.add(str(fp))

            elif tool_name in ("glob", "grep", "rg"):
                pattern = inp.get("pattern") or inp.get("query") or ""
                if pattern and len(str(pattern)) < 100:
                    files_touched.add(f"{tool_name}:{pattern}")

            elif tool_name == "bash":
                cmd = inp.get("command")
                if cmd:
                    commands_run.append(str(cmd)[:200])

        elif ptype == "patch":
            # patch parts carry a flat list of affected file paths
            for fp in data.get("files") or []:
                files_touched.add(str(fp))
            if data.get("files"):
                tools_called["patch"] = tools_called.get("patch", 0) + 1
