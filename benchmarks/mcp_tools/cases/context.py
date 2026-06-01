"""Benchmark cases for the `context` MCP tool.

This suite keeps only real, reproducible benchmark surfaces:
- 1 cold-start contract validation case
- 299 warm symbol-mode retrieval cases over real repo symbols
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchmarks.mcp_tools.harness import BenchCase
from benchmarks.mcp_tools.repo_facts import (
    benchmark_repo_root,
    collect_symbol_facts,
    unique_symbol_facts,
)

_TARGET_WARM_CASES = 299


def _assert_context(result: dict[str, Any]) -> None:
    assert "context" in result, "response must have 'context'"
    assert "bootstrap" in result, "response must have 'bootstrap'"
    assert isinstance(result["context"], str), "'context' must be a string"
    bootstrap = result["bootstrap"]
    assert isinstance(bootstrap, dict), "'bootstrap' must be a dict"
    assert "status" in bootstrap, "'bootstrap' must have 'status'"
    assert bootstrap["status"] in (
        "warm",
        "warming",
        "cold",
        "indexing",
        "error",
        "partial",
    ), f"unexpected bootstrap status: {bootstrap['status']}"


def _assert_cold_start_context(result: dict[str, Any]) -> None:
    _assert_context(result)


def _assert_symbols_context(
    result: dict[str, Any], expected_symbol: str, expected_path: str
) -> None:
    assert isinstance(result, dict), (
        f"symbols-mode response must be a dict, got: {type(result).__name__}"
    )
    assert isinstance(result.get("symbols"), list) and result["symbols"], (
        "symbols-mode must return ranked symbols"
    )
    assert isinstance(result.get("entry_points"), list) and result["entry_points"], (
        "symbols-mode must return entry points"
    )
    assert int(result.get("total_tokens", 0)) > 0, "symbols-mode must report total_tokens"
    assert int(result.get("tokens_saved", 0)) >= 0, "symbols-mode must report tokens_saved"
    text = str(result)
    assert expected_symbol in text, (
        f"symbols-mode should surface symbol {expected_symbol!r}, got: {text[:400]!r}"
    )
    assert expected_path in text, (
        f"symbols-mode should surface path {expected_path!r}, got: {text[:400]!r}"
    )


def _symbols_assert(
    expected_symbol: str, expected_path: str
) -> Callable[[dict[str, Any]], None]:
    def _assert(result: dict[str, Any]) -> None:
        _assert_symbols_context(result, expected_symbol, expected_path)

    return _assert


def _build_context_cases() -> list[BenchCase]:
    symbol_facts, _ = collect_symbol_facts(benchmark_repo_root())
    unique_symbols = unique_symbol_facts(symbol_facts)[:_TARGET_WARM_CASES]
    assert len(unique_symbols) == _TARGET_WARM_CASES, (
        "not enough unique symbols for warm context benchmark"
    )

    cases: list[BenchCase] = [
        BenchCase(
            op="get_context",
            label="context/cold-start",
            args={
                "task": "warm the repository context for later benchmark runs",
                "recall": False,
            },
            assert_keys=["context", "bootstrap"],
            custom_assert=_assert_cold_start_context,
            baseline_tokens=0,
        )
    ]
    for index, symbol in enumerate(unique_symbols, start=1):
        cases.append(
            BenchCase(
                op="get_context",
                label=f"context/symbols/{index:03d}",
                args={
                    "task": f"Locate symbol {symbol.name} defined in {symbol.path} and summarize how it fits in the implementation.",
                    "mode": "symbols",
                    "token_budget": 2400,
                    "max_blocks": 5,
                    "recall": False,
                },
                assert_keys=["symbols", "entry_points", "total_tokens"],
                custom_assert=_symbols_assert(symbol.name, symbol.path),
                baseline_tokens=10_000,
            )
        )
    return cases


CONTEXT_CASES: list[BenchCase] = _build_context_cases()
