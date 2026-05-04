"""Storage factory functions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from atelier.core.foundation.store import ReasoningStore
from atelier.infra.storage.memory_store import MemoryStore

if TYPE_CHECKING:
    from atelier.infra.storage.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def create_store(root: Path) -> ReasoningStore:
    """Create a ReasoningStore for the given root path."""
    return ReasoningStore(root)


def make_memory_store(root: str | Path, *, prefer: str = "sqlite") -> MemoryStore:
    """Create the configured MemoryStore implementation."""
    if prefer == "letta":
        try:
            from atelier.infra.memory_bridges.letta_adapter import LettaAdapter, LettaMemoryStore

            if LettaAdapter.is_available():
                return LettaMemoryStore(root)
        except Exception as exc:
            logger.warning("falling back to SQLite memory store after Letta init failure: %s", exc)
    from atelier.infra.storage.sqlite_memory_store import SqliteMemoryStore

    return SqliteMemoryStore(root)


__all__ = ["create_store", "make_memory_store"]
