"""Scoped pull-context capability orchestrator (M4)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from atelier.core.capabilities.code_context.budget import BudgetPacker
from atelier.core.capabilities.context_reuse.dead_ends import DeadEndTracker

from .models import ScopedContext, Subtask
from .pull import pull as _pull


class ScopedContextCapability:
    """Pull minimal, scoped context for a subtask over the code-context engine.

    ``engine`` is any object exposing ``search_symbols(query, *, limit, mode,
    snippet, file_glob)`` — in production the ``CodeContextEngine``.
    """

    def __init__(self, engine: Any, *, dead_ends: DeadEndTracker | None = None) -> None:
        self._engine = engine
        self._dead_ends = dead_ends or DeadEndTracker()
        self._packer = BudgetPacker()
        self._cache: dict[str, ScopedContext] = {}

    @staticmethod
    def _key(subtask: Subtask) -> str:
        parts = [
            subtask.description,
            "|".join(subtask.affected_paths),
            "|".join(subtask.keywords),
            "|".join(subtask.excluded_paths),
            str(subtask.budget_tokens),
        ]
        return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()

    def pull(self, subtask: Subtask) -> ScopedContext:
        key = self._key(subtask)
        cached = self._cache.get(key)
        if cached is not None:
            return replace(cached, provenance="cached")
        result = _pull(subtask, engine=self._engine, dead_ends=self._dead_ends, packer=self._packer)
        self._cache[key] = result
        return result

    def mark_dead_end(self, approach: str) -> None:
        self._dead_ends.mark_dead_end(approach)
