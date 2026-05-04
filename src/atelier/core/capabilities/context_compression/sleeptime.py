"""Local (deterministic) sleeptime summarizer for context compression."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SleeptimeChunk(BaseModel):
    """A paraphrase of a consecutive group of evicted ledger events."""

    start_event_index: int
    end_event_index: int
    paraphrase: str


def local_summarize(
    dropped_events: list[dict[str, Any]],
    *,
    start_index: int = 0,
) -> list[SleeptimeChunk]:
    """Group consecutive same-kind evicted events and emit one chunk per group.

    This is fully deterministic (no LLM calls) so CI stays hermetic.

    For each group the paraphrase is:
        "[<n> <kind>s] " + last_event.summary[:200]
    """
    if not dropped_events:
        return []

    chunks: list[SleeptimeChunk] = []
    group_start = 0
    group_kind = str(dropped_events[0].get("kind", "unknown"))
    group_events = [dropped_events[0]]

    def _emit(g_start: int, g_end: int, events: list[dict[str, Any]], kind: str) -> SleeptimeChunk:
        n = len(events)
        last_summary = str(events[-1].get("summary", ""))[:200]
        label = f"{kind}s" if not kind.endswith("s") else kind
        paraphrase = f"[{n} {label}] {last_summary}".strip()
        return SleeptimeChunk(
            start_event_index=start_index + g_start,
            end_event_index=start_index + g_end,
            paraphrase=paraphrase,
        )

    for i, ev in enumerate(dropped_events[1:], start=1):
        kind = str(ev.get("kind", "unknown"))
        if kind == group_kind:
            group_events.append(ev)
        else:
            chunks.append(
                _emit(group_start, group_start + len(group_events) - 1, group_events, group_kind)
            )
            group_start = i
            group_kind = kind
            group_events = [ev]

    chunks.append(_emit(group_start, group_start + len(group_events) - 1, group_events, group_kind))
    return chunks


__all__ = ["SleeptimeChunk", "local_summarize"]
