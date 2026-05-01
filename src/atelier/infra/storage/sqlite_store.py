"""SQLiteStore — thin alias for atelier.core.store.ReasoningStore.

Provides:
  - the name ``SQLiteStore`` as the canonical export for the sqlite backend
  - a ``health_check`` method to satisfy StoreProtocol
  - no behaviour change for existing callers that use ReasoningStore directly
"""

from __future__ import annotations

from typing import Any

from atelier.core.foundation.store import ReasoningStore


class SQLiteStore(ReasoningStore):
    """SQLite-backed store (extends ReasoningStore with storage-layer helpers)."""

    def health_check(self) -> dict[str, Any]:
        """Return basic health information."""
        try:
            with self._connect() as conn:
                count = conn.execute("SELECT COUNT(*) AS n FROM reasonblocks").fetchone()
                block_count = count["n"] if count else 0
            return {
                "ok": True,
                "backend": "sqlite",
                "db_path": str(self.db_path),
                "block_count": block_count,
            }
        except Exception as exc:
            return {"ok": False, "backend": "sqlite", "error": str(exc)}


__all__ = ["SQLiteStore"]
