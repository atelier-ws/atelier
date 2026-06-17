"""Loop pattern detectors.

Each detector receives the raw list of RunLedger event dicts and returns a
PatternMatch (or None if the pattern is not present).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .models import PatternMatch
from .signatures import near_duplicate_errors

# ---------------------------------------------------------------------------
# Individual detectors
# ---------------------------------------------------------------------------


def _detect_patch_revert_cycle(events: list[dict[str, Any]]) -> PatternMatch | None:
    """Detect alternating edit/revert on the same file(s)."""
    path_edits: dict[str, list[str]] = {}
    for ev in events:
        kind = ev.get("kind", "")
        path = ev.get("payload", {}).get("path", "")
        if kind in ("file_edit", "file_write", "edit_file") and path:
            path_edits.setdefault(path, []).append("edit")
        elif kind in ("file_revert", "revert") and path:
            path_edits.setdefault(path, []).append("revert")

    cycling: list[str] = []
    for path, ops in path_edits.items():
        alternations = sum(1 for i in range(1, len(ops)) if ops[i] != ops[i - 1])
        if alternations >= 3:
            cycling.append(f"{path} ({alternations} alternations)")

    if not cycling:
        return None
    count = len(cycling)
    severity = "high" if count >= 3 else "medium" if count >= 2 else "low"
    return PatternMatch(
        pattern_name="patch_revert_cycle",
        severity=severity,
        evidence=cycling,
        count=count,
    )


def _detect_search_read_loop(events: list[dict[str, Any]]) -> PatternMatch | None:
    """Detect repeated search → read → search sequences with no progress."""
    search_count = sum(1 for ev in events if ev.get("kind", "") in ("search", "grep", "file_search", "symbol_search"))
    read_count = sum(1 for ev in events if ev.get("kind", "") in ("read_file", "smart_read", "file_read"))
    total = search_count + read_count
    if total < 6:
        return None
    # Signal if >= 70% of events are just searching/reading
    ratio = total / max(len(events), 1)
    if ratio < 0.6:
        return None
    severity = "high" if ratio > 0.8 else "medium"
    return PatternMatch(
        pattern_name="search_read_loop",
        severity=severity,
        evidence=[f"search={search_count}, read={read_count}, ratio={ratio:.2f}"],
        count=total,
    )


def _detect_hypothesis_loop(events: list[dict[str, Any]]) -> PatternMatch | None:
    """Detect repeated identical tool calls (same kind + same key payload)."""
    from .signatures import _loop_signature

    sig_counts: Counter[str] = Counter()
    for ev in events:
        kind = ev.get("kind", "")
        payload = ev.get("payload", {})
        key = payload.get("path") or payload.get("query") or payload.get("key") or ""
        sig = _loop_signature([kind, str(key)])
        sig_counts[sig] += 1

    repeated = {sig: cnt for sig, cnt in sig_counts.items() if cnt >= 3}
    if not repeated:
        return None
    max_repeat = max(repeated.values())
    severity = "high" if max_repeat >= 6 else "medium" if max_repeat >= 4 else "low"
    return PatternMatch(
        pattern_name="hypothesis_loop",
        severity=severity,
        evidence=[f"signature repeated {cnt}x" for cnt in repeated.values()],
        count=sum(repeated.values()),
    )


def _detect_cascade_failure(events: list[dict[str, Any]]) -> PatternMatch | None:
    """Detect error_A → error_B → error_C cascade chains."""
    errors = [
        ev.get("payload", {}).get("error", "") or ev.get("summary", "")
        for ev in events
        if "error" in ev.get("kind", "").lower() or "fail" in ev.get("kind", "").lower()
    ]
    errors = [e for e in errors if e]
    if len(errors) < 3:
        return None
    # Group near-duplicates; a cascade has >= 2 distinct error types
    groups = near_duplicate_errors(errors)
    distinct_types = len(groups)
    if distinct_types < 2:
        return None
    severity = "high" if distinct_types >= 4 else "medium"
    return PatternMatch(
        pattern_name="cascade_failure",
        severity=severity,
        evidence=[f"distinct error types: {distinct_types}", f"total errors: {len(errors)}"],
        count=len(errors),
    )


def _detect_budget_burn(events: list[dict[str, Any]]) -> PatternMatch | None:
    """Detect when tool-call rate is accelerating (budget pressure)."""
    if len(events) < 10:
        return None
    # Compare first half vs second half tool call density
    mid = len(events) // 2
    first_half_tools = sum(1 for ev in events[:mid] if "tool" in ev.get("kind", "").lower())
    second_half_tools = sum(1 for ev in events[mid:] if "tool" in ev.get("kind", "").lower())
    if first_half_tools == 0:
        return None
    acceleration = second_half_tools / max(first_half_tools, 1)
    if acceleration < 1.5:
        return None
    severity = "high" if acceleration >= 2.5 else "medium"
    return PatternMatch(
        pattern_name="budget_burn",
        severity=severity,
        evidence=[f"tool call acceleration: {acceleration:.1f}x"],
        count=second_half_tools,
    )


def _detect_stall(events: list[dict[str, Any]]) -> PatternMatch | None:
    """Detect when the agent is stuck: many events but zero file writes or tool results."""
    if len(events) < 8:
        return None
    write_kinds = {"file_edit", "file_write", "edit_file", "create_file", "write_file"}
    success_kinds = {"tool_result", "success", "done", "complete"}
    writes = sum(1 for ev in events if ev.get("kind", "") in write_kinds)
    successes = sum(1 for ev in events if ev.get("kind", "") in success_kinds)
    if writes + successes > 0:
        return None
    reads = sum(
        1
        for ev in events
        if ev.get("kind", "") in {"tool_call", "read_file", "smart_read", "file_read", "search", "grep"}
    )
    stall_ratio = reads / max(len(events), 1)
    if stall_ratio < 0.5:
        return None
    severity = "high" if len(events) >= 15 else "medium"
    return PatternMatch(
        pattern_name="stall",
        severity=severity,
        evidence=[f"events={len(events)}, writes=0, read_ratio={stall_ratio:.2f}"],
        count=len(events),
    )


def _detect_second_guess_loop(events: list[dict[str, Any]]) -> PatternMatch | None:
    """Detect repeated clarification/re-analysis without commitment."""
    analysis_kinds = {
        "clarification",
        "re_analyze",
        "question",
        "ask",
        "reanalyze",
        "reconsider",
        "think",
        "hypothesis",
        "reasoning",
    }
    analysis_events = [ev for ev in events if ev.get("kind", "") in analysis_kinds]
    if len(analysis_events) < 4:
        return None
    # Require that analysis events are ≥ 40% of all events (no progress)
    ratio = len(analysis_events) / max(len(events), 1)
    if ratio < 0.4:
        return None
    severity = "high" if len(analysis_events) >= 7 else "medium"
    return PatternMatch(
        pattern_name="second_guess_loop",
        severity=severity,
        evidence=[f"analysis_events={len(analysis_events)}, ratio={ratio:.2f}"],
        count=len(analysis_events),
    )


_ALL_DETECTORS = [
    _detect_patch_revert_cycle,
    _detect_search_read_loop,
    _detect_hypothesis_loop,
    _detect_cascade_failure,
    _detect_budget_burn,
    _detect_stall,
    _detect_second_guess_loop,
]
