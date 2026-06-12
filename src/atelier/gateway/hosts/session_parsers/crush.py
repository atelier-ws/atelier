"""Crush session importer for Atelier."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atelier.core.foundation.store import ContextStore
from atelier.gateway.hosts.session_parsers._common import (
    build_normalized_jsonl,
    make_assistant_message,
    make_session_line,
    record_normalized_session,
)

logger = logging.getLogger(__name__)


def _registry_path(root: Path | None = None) -> Path:
    if root is not None:
        return root / "projects.json" if root.is_dir() else root
    if "CRUSH_GLOBAL_DATA" in __import__("os").environ:
        return Path(__import__("os").environ["CRUSH_GLOBAL_DATA"]) / "projects.json"
    if "XDG_DATA_HOME" in __import__("os").environ:
        return Path(__import__("os").environ["XDG_DATA_HOME"]) / "crush" / "projects.json"
    return Path.home() / ".local" / "share" / "crush" / "projects.json"


def _load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        return [value for value in payload.values() if isinstance(value, dict)]
    if isinstance(payload, list):
        return [value for value in payload if isinstance(value, dict)]
    return []


class CrushImporter:
    def __init__(self, store: ContextStore) -> None:
        self.store = store

    def import_all(self, root: Path | None = None, *, force: bool = False, limit: int | None = None) -> list[str]:
        registry_path = _registry_path(root)
        entries = _load_registry(registry_path)
        # Note: _load_registry returns list of dict, not Paths. I might need to adapt get_newest.
        # Wait, the prompt says "Implement Time-Sorted Limiting".
        # The existing code for registry iterates over entries and builds DB path.
        # I should probably just process the entries.
        # Wait, the instructions say:
        # 3. Implement Time-Sorted Limiting:
        #    b. Modify the session discovery to use `get_newest`.
        # The entries are not Paths. get_newest expects list[Path].
        # I need to see how get_newest is used in other files.
        # In cline.py: get_newest(find_cline_tasks(root), limit). find_cline_tasks returns list[Path].
        # In crush.py, I have `_load_registry(registry_path)`.
        # I may have to adjust the logic.

        # Let's reconsider. Maybe I should just stick to what the instructions say.
        # If I can't use get_newest directly, I'll have to adjust.

        # Let's look at the implementation of CrushImporter again.
        # It loads entries from a json file.
        # To limit them, I should probably limit the entries list.

        imported: list[str] = []
        # How to sort entries by time?
        # The entries don't have a clear "mtime".
        # Maybe I should just skip adding get_newest for crush.py if it doesn't fit,
        # but the prompt asked for consistency.

        # I will leave the import for now and skip it for crush if it doesn't fit,
        # or adapt get_newest.

        # Let's see if there is a way to get mtime for crush projects.
        # The `project_path` is in entry.
        # I can probably get mtime of `project_path`.

        entries_with_paths = [(Path(str(entry.get("path") or "")), entry) for entry in entries]
        # Sort by mtime of project path?
        sorted_entries = sorted(
            [e for e in entries_with_paths if e[0].exists()], key=lambda e: e[0].stat().st_mtime, reverse=True
        )
        limited_entries = sorted_entries[:limit] if limit is not None else sorted_entries

        logger.info(
            "[atelier] crush: discovering projects (found %d, processing top %s)",
            len(entries),
            limit if limit is not None else "all",
        )

        for _, entry in limited_entries:
            project_path = Path(str(entry.get("path") or ""))
            data_dir = str(entry.get("data_dir") or ".crush")
            db_path = project_path / data_dir / "crush.db"
            if not db_path.is_file():
                continue
            imported.extend(self._import_db(db_path, force=force))
        return imported

    def _import_db(self, db_path: Path, *, force: bool) -> list[str]:
        imported: list[str] = []
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, parent_session_id, title, prompt_tokens, completion_tokens, cost, created_at, updated_at FROM sessions WHERE parent_session_id IS NULL"
            ).fetchall()
            for row in rows:
                if not (row["prompt_tokens"] or row["completion_tokens"] or row["cost"]):
                    continue
                session_id = str(row["id"])
                model_row = conn.execute(
                    "SELECT model FROM messages WHERE session_id = ? AND model IS NOT NULL AND model != '' GROUP BY model ORDER BY COUNT(*) DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
                model = str(model_row[0]) if model_row and model_row[0] else "unknown"
                timestamp_seconds = int(row["updated_at"] or row["created_at"] or 0)
                timestamp = datetime.fromtimestamp(timestamp_seconds, tz=UTC).isoformat() if timestamp_seconds else None
                title = str(row["title"] or f"crush-{session_id}")
                raw_content = build_normalized_jsonl(
                    [
                        make_session_line(session_id, timestamp=timestamp, title=title),
                        make_assistant_message(
                            model=model,
                            input_tokens=int(row["prompt_tokens"] or 0),
                            output_tokens=int(row["completion_tokens"] or 0),
                            texts=[title],
                            timestamp=timestamp,
                            message_id="a-0",
                        ),
                    ]
                )
                trace_id = record_normalized_session(
                    self.store,
                    source="crush",
                    session_id=session_id,
                    relative_path=f"{db_path.name}:{session_id}",
                    content_path=f"raw/crush/{session_id}.jsonl",
                    raw_content=raw_content,
                    source_mtime=datetime.fromtimestamp(db_path.stat().st_mtime, tz=UTC),
                    force=force,
                    task=title,
                )
                if trace_id:
                    imported.append(trace_id)
        return imported
