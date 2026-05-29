"""Tests for the M4 scoped pull-context capability."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from atelier.core.capabilities.scoped_context import ScopedContextCapability, Subtask


@dataclass
class _FakeRecord:
    file_path: str
    symbol_name: str
    kind: str = "function"
    language: str = "python"
    qualified_name: str = ""
    signature: str = ""
    snippet: str = ""
    score: float | None = None


class _FakeEngine:
    """Minimal engine exposing the search_symbols subset pull() calls."""

    def __init__(self, records: list[_FakeRecord]) -> None:
        self._records = records

    def search_symbols(
        self,
        query: str,
        *,
        limit: int = 20,
        mode: str = "auto",
        snippet: str = "none",
        snippet_lines: int = 8,
        file_glob: str | None = None,
        **_: object,
    ) -> list[_FakeRecord]:
        recs = self._records
        if file_glob is not None:
            recs = [r for r in recs if r.file_path == file_glob or fnmatch.fnmatch(r.file_path, file_glob)]
        return recs[:limit]


def _records() -> list[_FakeRecord]:
    return [
        _FakeRecord("src/a.py", "alpha", score=0.9, snippet="x" * 200, signature="def alpha(): ..."),
        _FakeRecord("src/b.py", "beta", score=0.8, snippet="y" * 200, signature="def beta(): ..."),
        _FakeRecord("src/c.py", "gamma", score=0.7, snippet="z" * 200, signature="def gamma(): ..."),
        _FakeRecord("src/legacy/old.py", "delta", score=0.6, snippet="w" * 200),
    ]


def test_pull_respects_budget() -> None:
    cap = ScopedContextCapability(_FakeEngine(_records()))
    result = cap.pull(Subtask(description="work on alpha", budget_tokens=200))
    assert result.total_tokens <= 200
    assert result.dropped_for_budget > 0  # heavy snippet fields were dropped
    assert result.chunks  # something survived


def test_excluded_paths_honoured() -> None:
    cap = ScopedContextCapability(_FakeEngine(_records()))
    result = cap.pull(Subtask(description="work", excluded_paths=["src/legacy"], budget_tokens=4000))
    assert all("legacy" not in c.path for c in result.chunks)
    assert any(e.reason.startswith("excluded_path") for e in result.excluded)


def test_rationale_cites_scores() -> None:
    cap = ScopedContextCapability(_FakeEngine(_records()))
    result = cap.pull(Subtask(description="work on alpha", budget_tokens=4000))
    assert "score=" in result.rationale


def test_cache_hit() -> None:
    cap = ScopedContextCapability(_FakeEngine(_records()))
    subtask = Subtask(description="work on alpha", budget_tokens=4000)
    first = cap.pull(subtask)
    second = cap.pull(subtask)
    assert first.provenance == "fresh"
    assert second.provenance == "cached"
    assert [c.path for c in first.chunks] == [c.path for c in second.chunks]


def test_dead_end_filtered() -> None:
    cap = ScopedContextCapability(_FakeEngine(_records()))
    cap.mark_dead_end("beta src/b.py")
    result = cap.pull(Subtask(description="work", budget_tokens=4000))
    assert all(c.path != "src/b.py" for c in result.chunks)
    assert any(e.reason == "dead_end" for e in result.excluded)
