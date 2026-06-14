"""Honest per-file cap on the "avoided full read" saving.

Both outline and range reads compute ``tokens_saved`` against the FULL-file
baseline (what the host's built-in Read would have emitted). Across multiple
reads of the SAME file in one session that double-counts: you can only avoid
reading a file once. This module records which files have already been credited
for baseline avoidance and signals callers to zero the saving on the 2nd+
outline/range read of the same file.

Full-mode reads are deliberately untouched -- their saving is *minification*
(byte reduction of the content actually delivered), not baseline avoidance, so
it never double-counts.

Every function is a PURE, total transform over a plain session-state dict: no
I/O, no exceptions raised to callers, tolerant of missing keys and wrong types.
The caller owns persistence, the kill switch, and the per-session epoch reset.
"""

from __future__ import annotations

import os
from typing import Any

# Modes whose ``tokens_saved`` is measured against the full-file baseline and so
# may be credited at most once per file per session.
_BASELINE_MODES = frozenset({"outline", "range"})
_CREDITED_KEY = "read_baseline_credited"


def _normalize_path(raw: Any) -> str:
    """Normalize to a stable workspace-relative key (abs and rel must match)."""
    if not isinstance(raw, str):
        return ""
    path = raw.strip()
    if not path:
        return ""
    cwd = os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()
    if cwd:
        cwd_norm = cwd.rstrip("/") + "/"
        if path.startswith(cwd_norm):
            path = path[len(cwd_norm) :]
    return path.lstrip("./").strip("/") if path not in (".", "/") else path


def _credited(state: Any) -> list[str]:
    if not isinstance(state, dict):
        return []
    current = state.get(_CREDITED_KEY)
    if not isinstance(current, list):
        current = []
        state[_CREDITED_KEY] = current
    return current


def should_credit(state: dict[str, Any], path: Any, mode: Any) -> tuple[dict[str, Any], bool]:
    """Return ``(state, credit?)`` for a read.

    ``credit=True``  -> emit the read's ``tokens_saved`` unchanged.
    ``credit=False`` -> this file's full-baseline avoidance was already counted
    this session, so the saving must be zeroed to avoid double-counting.

    Non-baseline modes (``full``/``summary``/``directory``) and unknown paths
    always return ``True`` (left untouched).
    """
    if not isinstance(state, dict):
        return state, True
    if mode not in _BASELINE_MODES:
        return state, True
    norm = _normalize_path(path)
    if not norm:
        return state, True
    credited = _credited(state)
    if norm in credited:
        return state, False
    credited.append(norm)
    state[_CREDITED_KEY] = credited
    return state, True


def reset(state: dict[str, Any]) -> dict[str, Any]:
    """Clear the credited set (used on compaction / epoch change)."""
    if isinstance(state, dict):
        state[_CREDITED_KEY] = []
    return state
