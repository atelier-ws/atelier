"""Process-local content-addressed cache for internal-LLM results.

Internal-LLM calls (summaries for background compaction, consolidation, etc.)
are effectively pure functions of ``(text, model, max_tokens, backend)``: the
same input yields an equivalent summary, so recomputing it burns provider tokens
for nothing. This is a thread-safe LRU that memoizes those results within a
process.

Entries are short strings (a summary bounded by ``max_tokens``), so even a large
entry count is modest memory -- the default holds ~16k summaries. Tune the
capacity with ``ATELIER_INTERNAL_LLM_CACHE_MAX_ENTRIES``; disable caching
entirely with ``ATELIER_INTERNAL_LLM_CACHE=0``.

Kept self-contained (stdlib only) on purpose: this module lives in the infra
layer and must not import from ``core/`` or ``gateway/``.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from collections.abc import Callable

# Generous default: cached summaries are small strings and most machines have
# plenty of RAM, so a large entry count costs little memory while greatly
# improving hit rate across a long-lived MCP server process. Override per-process
# with ATELIER_INTERNAL_LLM_CACHE_MAX_ENTRIES.
_DEFAULT_MAX_ENTRIES = 16384


def _enabled() -> bool:
    return os.environ.get("ATELIER_INTERNAL_LLM_CACHE", "1") != "0"


def _configured_max_entries() -> int:
    raw = os.environ.get("ATELIER_INTERNAL_LLM_CACHE_MAX_ENTRIES")
    if raw is None:
        return _DEFAULT_MAX_ENTRIES
    try:
        configured = int(raw)
    except ValueError:
        return _DEFAULT_MAX_ENTRIES
    return max(1, configured)


class _LRUCache:
    """Minimal thread-safe LRU over string keys and string values."""

    def __init__(self, max_entries: int | None = None) -> None:
        resolved = max_entries if max_entries is not None else _configured_max_entries()
        self._max_entries = max(1, resolved)
        self._store: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_SUMMARY_CACHE = _LRUCache()


def summary_key(text: str, *, model: str | None, max_tokens: int, backend: str) -> str:
    payload = f"{backend}\x00{model or ''}\x00{max_tokens}\x00{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cached_summarize(
    text: str,
    *,
    model: str | None,
    max_tokens: int,
    backend: str,
    compute: Callable[[], str],
) -> str:
    """Return a cached summary for identical inputs, else compute and store it.

    Only successful results are cached -- if ``compute`` raises, the exception
    propagates and nothing is stored.
    """
    if not _enabled():
        return compute()
    key = summary_key(text, model=model, max_tokens=max_tokens, backend=backend)
    cached = _SUMMARY_CACHE.get(key)
    if cached is not None:
        return cached
    value = compute()
    _SUMMARY_CACHE.put(key, value)
    return value


__all__ = ["cached_summarize", "summary_key"]
