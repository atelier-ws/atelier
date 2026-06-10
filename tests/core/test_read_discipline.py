"""Tests for the expand-after-projection read nudge."""

from __future__ import annotations

import pytest

from atelier.core.capabilities.tool_supervision.read_discipline import (
    expand_hint,
    note_read,
    reset,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset()


def test_no_hint_without_prior_projected_read() -> None:
    assert expand_hint("/ws/a.py", expand=True) is None


def test_no_hint_when_not_expanding() -> None:
    note_read("/ws/a.py", "outline")
    assert expand_hint("/ws/a.py", expand=False) is None


def test_hint_after_outline_read() -> None:
    note_read("/ws/a.py", "outline")
    hint = expand_hint("/ws/a.py", expand=True)
    assert hint is not None
    assert "outline" in hint
    assert "range" in hint


def test_hint_after_compact_read() -> None:
    note_read("/ws/a.py", "compact")
    hint = expand_hint("/ws/a.py", expand=True)
    assert hint is not None
    assert "compact" in hint


def test_non_projected_modes_not_recorded() -> None:
    note_read("/ws/a.py", "full")
    note_read("/ws/a.py", "range")
    assert expand_hint("/ws/a.py", expand=True) is None


def test_paths_are_independent() -> None:
    note_read("/ws/a.py", "outline")
    assert expand_hint("/ws/b.py", expand=True) is None


def test_reset_clears_memory() -> None:
    note_read("/ws/a.py", "outline")
    reset()
    assert expand_hint("/ws/a.py", expand=True) is None
