"""Shared test helpers - reusable across test files without conftest import hacks."""

from __future__ import annotations

import functools
from pathlib import Path


@functools.cache
def init_store_at(root_str: str) -> None:
    """Initialize atelier at *root_str*. Cached so repeated inits for the
    same path are no-ops (saves ~1-2 s per redundant call).

    Caller must pass a **string** (not a Path) so lru_cache can hash it.
    """
    from atelier.infra.storage.factory import create_store

    create_store(Path(root_str)).init()
