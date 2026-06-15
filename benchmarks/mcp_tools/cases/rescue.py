"""Benchmark cases for the public `rescue` MCP tool."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from benchmarks.mcp_tools.harness import BenchCase
from benchmarks.mcp_tools.repo_facts import collect_symbol_facts, unique_symbol_facts

_TARGET_MATCHED_CASES = 150
_TARGET_UNMATCHED_CASES = 150


def _repo_root() -> Path:
    value = os.environ.get("CLAUDE_WORKSPACE_ROOT")
    if value:
        return Path(value)
    return Path(__file__).resolve().parents[3]


def _assert_matched_rescue(
    result: dict[str, Any],
    expected_block_id: str,
    expected_procedure_fragment: str,
) -> None:
    assert isinstance(result.get("rescue"), str) and result["rescue"], "matched rescue must return guidance text"
    assert "Stop retrying. Apply procedure" in result["rescue"], "matched rescue must return procedure guidance"
    assert expected_procedure_fragment in result["rescue"], "matched rescue must mention seeded procedure"
    matched_blocks = result.get("matched_blocks")
    assert isinstance(matched_blocks, list) and matched_blocks, "matched rescue must return matched blocks"
    assert expected_block_id in matched_blocks, f"expected matched block {expected_block_id!r}, got {matched_blocks!r}"
    analysis = result.get("analysis")
    assert isinstance(analysis, dict), "matched rescue should include failure analysis"


def _assert_unmatched_rescue(result: dict[str, Any]) -> None:
    rescue = str(result.get("rescue") or "")
    assert rescue.startswith(
        "No matching Playbook found."
    ), f"unmatched rescue must return fallback text, got: {rescue[:200]!r}"
    assert (
        result.get("matched_blocks") == []
    ), f"unmatched rescue must not match blocks, got: {result.get('matched_blocks')!r}"


def _matched_assert(expected_block_id: str, expected_procedure_fragment: str) -> Callable[[dict[str, Any]], None]:
    def _assert(result: dict[str, Any]) -> None:
        _assert_matched_rescue(result, expected_block_id, expected_procedure_fragment)

    return _assert


def _build_rescue_cases() -> list[BenchCase]:
    unique_symbols = unique_symbol_facts(collect_symbol_facts(_repo_root())[0])
    matched_symbols = unique_symbols[:_TARGET_MATCHED_CASES]
    unmatched_symbols = unique_symbols[_TARGET_MATCHED_CASES : _TARGET_MATCHED_CASES + _TARGET_UNMATCHED_CASES]
    assert len(matched_symbols) == _TARGET_MATCHED_CASES, "not enough symbols for matched rescue cases"
    assert len(unmatched_symbols) == _TARGET_UNMATCHED_CASES, "not enough symbols for unmatched rescue cases"

    cases: list[BenchCase] = []
    for index, symbol in enumerate(matched_symbols, start=1):
        block_id = f"bench-rescue-block-{index:03d}"
        procedure_fragment = f"inspect {symbol.path}"
        task = f"Fix failure in {symbol.name} defined in {symbol.path}"
        error = f"AssertionError: {symbol.name} regression at {symbol.path}:{symbol.line}"
        cases.append(
            BenchCase(
                op="rescue",
                label=f"rescue/matched/{index:03d}",
                args={
                    "task": task,
                    "error": error,
                    "domain": "coding",
                    "files": [symbol.path],
                    "recent_actions": [f"ran pytest for {symbol.name}", f"read {symbol.path}"],
                    "_seed_playbooks": [
                        {
                            "id": block_id,
                            "title": f"Fix {symbol.name} failure",
                            "domain": "coding",
                            "task_types": ["debug"],
                            "triggers": [symbol.name, "AssertionError", symbol.path],
                            "situation": f"Failures around {symbol.name} in {symbol.path}",
                            "procedure": [
                                procedure_fragment,
                                f"trace callers of {symbol.name}",
                                f"re-run targeted validation for {symbol.name}",
                            ],
                            "verification": [f"confirm {symbol.name} no longer fails"],
                            "failure_signals": [error],
                        }
                    ],
                    "_seed_traces": [
                        {
                            "id": f"bench-rescue-trace-{index:03d}-a",
                            "agent": "bench",
                            "domain": "coding",
                            "task": task,
                            "status": "failed",
                            "errors_seen": [error],
                            "commands_run": ["pytest -q"],
                        },
                        {
                            "id": f"bench-rescue-trace-{index:03d}-b",
                            "agent": "bench",
                            "domain": "coding",
                            "task": f"{task} retry",
                            "status": "failed",
                            "errors_seen": [error.replace("regression", "retry regression")],
                            "commands_run": ["pytest -q -x"],
                        },
                    ],
                },
                assert_keys=["rescue", "matched_blocks", "analysis"],
                custom_assert=_matched_assert(block_id, procedure_fragment),
                baseline_tokens=0,  # fixed-constant baseline removed; savings not claimed (correctness-only)
            )
        )
    for index, symbol in enumerate(unmatched_symbols, start=1):
        cases.append(
            BenchCase(
                op="rescue",
                label=f"rescue/unmatched/{index:03d}",
                args={
                    "task": f"Unmatched rescue task for {symbol.name}",
                    "error": f"UnmatchedError::{symbol.name}::{index:03d}",
                    "domain": f"benchmark-unmatched-{index:03d}",
                    "files": [symbol.path],
                    "recent_actions": [f"attempted {symbol.name} fallback"],
                },
                assert_keys=["rescue", "matched_blocks"],
                custom_assert=_assert_unmatched_rescue,
                baseline_tokens=0,  # fixed-constant baseline removed; savings not claimed (correctness-only)
            )
        )
    return cases


RESCUE_CASES = _build_rescue_cases()
