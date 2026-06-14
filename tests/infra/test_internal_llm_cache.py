"""Tests for the process-local internal-LLM summary cache."""

from __future__ import annotations

import pytest

from atelier.infra.internal_llm import cache as llm_cache


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    llm_cache._SUMMARY_CACHE.clear()


def test_cached_summarize_memoizes_identical_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_INTERNAL_LLM_CACHE", raising=False)
    calls = {"n": 0}

    def _compute() -> str:
        calls["n"] += 1
        return f"summary-{calls['n']}"

    first = llm_cache.cached_summarize("text", model="m", max_tokens=64, backend="openai", compute=_compute)
    second = llm_cache.cached_summarize("text", model="m", max_tokens=64, backend="openai", compute=_compute)
    assert first == second == "summary-1"
    assert calls["n"] == 1


def test_cached_summarize_distinct_keys_recompute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_INTERNAL_LLM_CACHE", raising=False)
    calls = {"n": 0}

    def _compute() -> str:
        calls["n"] += 1
        return f"summary-{calls['n']}"

    llm_cache.cached_summarize("text-a", model="m", max_tokens=64, backend="openai", compute=_compute)
    llm_cache.cached_summarize("text-b", model="m", max_tokens=64, backend="openai", compute=_compute)
    llm_cache.cached_summarize(
        "text-a", model="m", max_tokens=128, backend="openai", compute=_compute
    )  # diff max_tokens
    assert calls["n"] == 3


def test_cached_summarize_disabled_recomputes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_INTERNAL_LLM_CACHE", "0")
    calls = {"n": 0}

    def _compute() -> str:
        calls["n"] += 1
        return "summary"

    llm_cache.cached_summarize("text", model="m", max_tokens=64, backend="openai", compute=_compute)
    llm_cache.cached_summarize("text", model="m", max_tokens=64, backend="openai", compute=_compute)
    assert calls["n"] == 2


def test_cached_summarize_does_not_cache_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_INTERNAL_LLM_CACHE", raising=False)
    calls = {"n": 0}

    def _boom() -> str:
        calls["n"] += 1
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        llm_cache.cached_summarize("text", model="m", max_tokens=64, backend="openai", compute=_boom)
    with pytest.raises(RuntimeError):
        llm_cache.cached_summarize("text", model="m", max_tokens=64, backend="openai", compute=_boom)
    assert calls["n"] == 2  # nothing cached on failure
