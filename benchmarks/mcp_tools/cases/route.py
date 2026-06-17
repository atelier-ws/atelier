"""Benchmark cases for the public `route` MCP tool."""

from __future__ import annotations

import os
from pathlib import Path

from benchmarks.mcp_tools.harness import BenchCase
from benchmarks.mcp_tools.repo_facts import (
    collect_repo_file_facts,
    collect_symbol_facts,
    unique_symbol_facts,
)

_TASK_TYPES = ("debug", "feature", "refactor", "test", "explain", "review", "docs", "ops")


def _repo_root() -> Path:
    value = os.environ.get("CLAUDE_WORKSPACE_ROOT")
    if value:
        return Path(value)
    return Path(__file__).resolve().parents[3]


def _assert_route_shape(result: dict[str, object]) -> None:
    assert "model" in result, f"route response must have 'model', got: {list(result)}"
    assert "tier" in result, f"route response must have 'tier', got: {list(result)}"
    assert "route_tier" in result, f"route response must have 'route_tier', got: {list(result)}"
    assert "rationale" in result, f"route response must have 'rationale', got: {list(result)}"


def _assert_route_cheap(result: dict[str, object]) -> None:
    _assert_route_shape(result)
    assert result["tier"] == "cheap", f"budget=cheap must yield tier=cheap, got: {result['tier']}"


def _assert_route_balanced(result: dict[str, object]) -> None:
    _assert_route_shape(result)
    assert result["tier"] in {
        "cheap",
        "balanced",
        "high",
        "best",
    }, f"balanced route returned unknown tier {result['tier']!r}"


def _assert_route_best(result: dict[str, object]) -> None:
    _assert_route_shape(result)
    assert result["tier"] != "cheap", f"budget=best must not yield tier=cheap, got: {result['tier']}"


def _build_prompt(task_type: str, symbol_name: str, path: str, anchor_path: str) -> str:
    prompts = {
        "debug": f"debug a regression around {symbol_name} in {path} using {anchor_path} for context",
        "feature": f"implement a feature adjacent to {symbol_name} in {path} and wire tests in {anchor_path}",
        "refactor": f"refactor {symbol_name} in {path} without breaking callers mentioned in {anchor_path}",
        "test": f"write missing tests for {symbol_name} in {path} and compare with patterns in {anchor_path}",
        "explain": f"explain what {symbol_name} in {path} does and summarize nearby code in {anchor_path}",
        "review": f"review a patch touching {symbol_name} in {path} with surrounding files like {anchor_path}",
        "docs": f"document how {symbol_name} in {path} works and reference {anchor_path}",
        "ops": f"triage an operational issue tied to {symbol_name} in {path} and nearby code in {anchor_path}",
    }
    return prompts[task_type]


def _build_route_cases() -> list[BenchCase]:
    repo_root = _repo_root()
    symbols = unique_symbol_facts(collect_symbol_facts(repo_root)[0])[:100]
    files = collect_repo_file_facts(repo_root)
    assert len(symbols) == 100, "not enough unique symbols for generated route cases"
    assert files, "route benchmarks need repo files"

    cases: list[BenchCase] = []
    for index, symbol in enumerate(symbols, start=1):
        task_type = _TASK_TYPES[(index - 1) % len(_TASK_TYPES)]
        anchor = files[(index - 1) % len(files)]
        prompt = _build_prompt(task_type, symbol.name, symbol.path, anchor.path)
        cases.extend(
            [
                BenchCase(
                    op="route",
                    label=f"route/cheap/{index:03d}",
                    args={"task": prompt, "task_type": task_type, "budget": "cheap"},
                    assert_keys=["model", "tier", "route_tier", "rationale"],
                    custom_assert=_assert_route_cheap,
                    baseline_tokens=0,  # fixed-constant baseline removed; savings not claimed (correctness-only)
                ),
                BenchCase(
                    op="route",
                    label=f"route/balanced/{index:03d}",
                    args={"task": prompt, "task_type": task_type, "budget": "balanced"},
                    assert_keys=["model", "tier", "route_tier", "rationale"],
                    custom_assert=_assert_route_balanced,
                    baseline_tokens=0,  # fixed-constant baseline removed; savings not claimed (correctness-only)
                ),
                BenchCase(
                    op="route",
                    label=f"route/best/{index:03d}",
                    args={"task": prompt, "task_type": task_type, "budget": "best"},
                    assert_keys=["model", "tier", "route_tier", "rationale"],
                    custom_assert=_assert_route_best,
                    baseline_tokens=0,  # fixed-constant baseline removed; savings not claimed (correctness-only)
                ),
            ]
        )
    return cases


ROUTE_CASES = _build_route_cases()
