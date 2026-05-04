"""Tests for fuzzy matching utilities used by batch_edit (WP-24)."""

from __future__ import annotations

import pytest

from atelier.core.capabilities.tool_supervision.fuzzy_match import (
    FuzzyAmbiguousMatchError,
    apply_fuzzy_replace,
    normalize_for_fuzzy,
)


def test_normalize_for_fuzzy_tolerates_whitespace_variants() -> None:
    left = "\tdef fn( )  :   \n    return 1   "
    right = "    def fn( ):\n\treturn   1"
    assert normalize_for_fuzzy(left) == normalize_for_fuzzy(right)


def test_apply_fuzzy_replace_handles_indentation_drift() -> None:
    content = "def outer():\n\tif True:\n\t\treturn 1\n"
    old = "def outer():\n    if True:\n        return 1\n"
    new = "def outer():\n\tif True:\n\t\treturn 2\n"

    updated, line_start, line_end = apply_fuzzy_replace(content, old, new)

    assert "return 2" in updated
    assert line_start == 1
    assert line_end == 3


def test_apply_fuzzy_replace_handles_trailing_whitespace_drift() -> None:
    content = "SELECT id, name   \nFROM users\n"
    old = "SELECT id, name\nFROM users\n"
    new = "SELECT id\nFROM users\n"

    updated, line_start, line_end = apply_fuzzy_replace(content, old, new)

    assert updated == new
    assert line_start == 1
    assert line_end == 2


def test_apply_fuzzy_replace_handles_blank_line_drift() -> None:
    content = "def outer():\n\n\tif True:\n\t\treturn 1\n"
    old = "def outer():\n    if True:\n        return 1\n"
    new = "def outer():\n    if True:\n        return 2\n"

    updated, line_start, line_end = apply_fuzzy_replace(content, old, new)

    assert "return 2" in updated
    assert line_start == 1
    assert line_end == 4


def test_apply_fuzzy_replace_raises_on_ambiguity_with_ranges() -> None:
    content = "def hello():\n    return 1\n\ndef hello():\n    return 1\n"
    old = "def hello():\n\treturn 1\n"
    new = "def hello():\n    return 2\n"

    with pytest.raises(FuzzyAmbiguousMatchError) as exc:
        apply_fuzzy_replace(content, old, new)

    message = str(exc.value)
    assert "ranges" in message
    assert "1-2" in message
    assert "4-5" in message
