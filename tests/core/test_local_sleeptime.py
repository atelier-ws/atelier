"""Tests for the local deterministic sleeptime summarizer."""

from __future__ import annotations

from atelier.core.capabilities.context_compression.sleeptime import (
    SleeptimeChunk,
    local_summarize,
)


def _make_events(kinds_summaries: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"kind": k, "summary": s} for k, s in kinds_summaries]


def test_local_summarize_empty() -> None:
    assert local_summarize([]) == []


def test_local_summarize_single_group() -> None:
    events = _make_events([("tool_output", "foo"), ("tool_output", "bar")])
    chunks = local_summarize(events)
    assert len(chunks) == 1
    assert chunks[0].start_event_index == 0
    assert chunks[0].end_event_index == 1
    assert "tool_output" in chunks[0].paraphrase
    assert "bar" in chunks[0].paraphrase  # last event summary


def test_local_summarize_multiple_groups() -> None:
    events = _make_events(
        [
            ("tool_output", "a"),
            ("tool_output", "b"),
            ("file_read", "c"),
            ("file_read", "d"),
            ("file_read", "e"),
        ]
    )
    chunks = local_summarize(events)
    assert len(chunks) == 2
    assert chunks[0].start_event_index == 0
    assert chunks[0].end_event_index == 1
    assert "[2 tool_outputs]" in chunks[0].paraphrase
    assert chunks[1].start_event_index == 2
    assert chunks[1].end_event_index == 4
    assert "[3 file_reads]" in chunks[1].paraphrase


def test_local_summarize_deterministic() -> None:
    events = _make_events([("tool_output", "same"), ("tool_output", "same")])
    chunks1 = local_summarize(events)
    chunks2 = local_summarize(events)
    assert chunks1[0].paraphrase == chunks2[0].paraphrase


def test_local_summarize_start_index_offset() -> None:
    events = _make_events([("trace", "x")])
    chunks = local_summarize(events, start_index=10)
    assert chunks[0].start_event_index == 10
    assert chunks[0].end_event_index == 10


def test_sleeptime_chunk_model() -> None:
    chunk = SleeptimeChunk(start_event_index=0, end_event_index=2, paraphrase="hello")
    assert chunk.paraphrase == "hello"
    assert chunk.start_event_index == 0
