"""Process-local read-mode memory powering the expand-after-projection cost nudge.

A file served as outline/compact this session usually only needs a ``range``
read afterwards (e.g. for edit targeting). ``expand=True`` re-sends the whole
body — the single most common avoidable read cost. The nudge is advisory and
never blocks the read.
"""

from __future__ import annotations

import threading

_PROJECTED_MODES = frozenset({"outline", "compact"})

_lock = threading.Lock()
_last_projected_mode: dict[str, str] = {}


def note_read(path: str, mode: str) -> None:
    """Record that *path* was served as a projected view (outline/compact)."""
    if not path or mode not in _PROJECTED_MODES:
        return
    with _lock:
        _last_projected_mode[path] = mode


def expand_hint(path: str, *, expand: bool) -> str | None:
    """Cost hint when ``expand=True`` re-reads a path already projected this session."""
    if not expand or not path:
        return None
    with _lock:
        prior = _last_projected_mode.get(path)
    if prior is None:
        return None
    return (
        f"cost: this file was already read as {prior} this session; "
        'prefer range="N-M" for the exact lines you need - expand re-sends the whole file.'
    )


def reset() -> None:
    """Clear the process-local memory (tests)."""
    with _lock:
        _last_projected_mode.clear()
