"""Storage factory functions."""

from __future__ import annotations

from pathlib import Path

from atelier.core.foundation.store import ReasoningStore


def create_store(root: Path) -> ReasoningStore:
    """Create a ReasoningStore for the given root path."""
    return ReasoningStore(root)
