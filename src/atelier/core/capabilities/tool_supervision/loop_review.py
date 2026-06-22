"""Spiral nudge at the MCP tool boundary.

Atelier's own runtime consults :class:`LoopDetectionCapability` to break out of
no-progress loops, but an external host driving Atelier over MCP (Claude Code,
Codex, ...) never sees that signal -- those detectors read a ``RunLedger`` the
MCP path does not populate, and several of them (``search_read_loop``,
``stall``, ``hypothesis_loop`` on re-reads) fire during *normal* early
exploration, so they cannot be surfaced verbatim to a host without nagging.

This module supplies the narrow, false-positive-free complement that *can* run
at the boundary: a per-session count of byte-identical tool calls. Re-issuing
the same call with the same arguments cannot change the result, so once it
crosses a threshold we surface a one-line note telling the agent to change
approach. ``read`` is intentionally excluded -- re-reading a file after an edit
is normal iteration, and identical reads are already deduplicated upstream.

Soft signal only: it never blocks a call. The MCP boundary owns the per-session
registry + kill switch; this module is pure logic so it is unit-testable on its
own.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from atelier.core.foundation.watchdogs import args_signature

# Repeating an identical call of these tools is unproductive: the result is a
# pure function of the inputs (search/grep), or the inputs already encode the
# full intent (edit/codemod/bash/sql/web_fetch). ``read`` is excluded on
# purpose -- re-reading after an edit is healthy, and identical reads are deduped
# elsewhere -- and unlisted tools are simply not tracked.
_REPEAT_SENSITIVE = frozenset({"bash", "grep", "search", "explore", "edit", "codemod", "sql", "web_fetch"})

# Nudge once the same (tool, args) has been issued this many times in a session.
# 4 == "medium" in loop_detection's hypothesis_loop, i.e. past the point where a
# repeat is plausibly a deliberate retry and into clear no-progress territory.
_REPEAT_THRESHOLD = 4

# Cap distinct signatures retained per session so a marathon run cannot grow the
# counter without bound; the hottest signatures (the only ones that can trip) are
# always kept.
_MAX_SIGNATURES = 512
_SIGNATURE_FLOOR = 256


def call_signature(name: str, args: dict[str, Any] | None) -> str | None:
    """Stable key for a repeat-sensitive call, or None when the tool is not
    tracked."""
    if name not in _REPEAT_SENSITIVE:
        return None
    payload = args if isinstance(args, dict) else {}
    return f"{name}:{args_signature(payload)}"


class SessionLoopTracker:
    """Per-session count of byte-identical tool calls (bounded, thread-naive --
    the caller serialises access the same way it does for ``SearchHistory``)."""

    __slots__ = ("_counts",)

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def record(self, name: str, args: dict[str, Any] | None) -> int:
        """Record a call; return how many times this exact call has now been
        seen this session (0 when the tool is not repeat-sensitive)."""
        sig = call_signature(name, args)
        if sig is None:
            return 0
        self._counts[sig] += 1
        seen = self._counts[sig]
        if len(self._counts) > _MAX_SIGNATURES:
            self._counts = Counter(dict(self._counts.most_common(_SIGNATURE_FLOOR)))
        return seen


def repeat_nudge(name: str, count: int, *, threshold: int = _REPEAT_THRESHOLD) -> str | None:
    """One-line nudge when an identical call has repeated past *threshold*; else
    None."""
    if count < threshold:
        return None
    return (
        f"[loop] `{name}` called {count}x with identical arguments -- repeating it "
        "cannot change the result. Act on the evidence you already have, or change "
        "approach (different inputs, a different tool, or step back and reconsider "
        "the root cause) before calling it again."
    )


__all__ = ["SessionLoopTracker", "call_signature", "repeat_nudge"]
