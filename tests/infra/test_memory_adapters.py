"""Tests for memory interoperability wrappers."""

from __future__ import annotations

from atelier.infra.memory_bridges.openmemory import OpenMemoryAdapter


def test_openmemory_adapter_disabled_by_default() -> None:
    adapter = OpenMemoryAdapter()
    result = adapter.fetch_context(task="Fix the checkout bug")

    assert result.ok is True
    assert result.skipped is False
    assert result.source == "openmemory"
