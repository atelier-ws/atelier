"""Benchmark cases for the public `verify` MCP tool."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from benchmarks.mcp_tools.harness import BenchCase
from benchmarks.mcp_tools.repo_facts import collect_symbol_facts, unique_symbol_facts

_STATUS_ORDER = ("pass", "warn", "blocked", "escalate")


def _repo_root() -> Path:
    value = os.environ.get("CLAUDE_WORKSPACE_ROOT")
    if value:
        return Path(value)
    return Path(__file__).resolve().parents[3]


def _assert_verify_case(
    result: dict[str, Any],
    expected_rubric_id: str,
    expected_status: str,
    expected_outcomes: dict[str, str],
    expected_escalations: list[str],
) -> None:
    assert result.get("rubric_id") == expected_rubric_id, (
        f"verify must return rubric_id={expected_rubric_id!r}, got {result.get('rubric_id')!r}"
    )
    assert result.get("status") == expected_status, (
        f"verify must return status={expected_status!r}, got {result.get('status')!r}"
    )
    outcomes = result.get("outcomes")
    assert isinstance(outcomes, list), "verify must return outcomes list"
    statuses = {str(item.get("name")): str(item.get("status")) for item in outcomes if isinstance(item, dict)}
    for name, status in expected_outcomes.items():
        assert statuses.get(name) == status, f"expected outcome {name!r}={status!r}, got {statuses.get(name)!r}"
    assert result.get("escalations") == expected_escalations, (
        f"expected escalations {expected_escalations!r}, got {result.get('escalations')!r}"
    )


def _verify_assert(
    expected_rubric_id: str,
    expected_status: str,
    expected_outcomes: dict[str, str],
    expected_escalations: list[str],
) -> Callable[[dict[str, Any]], None]:
    def _assert(result: dict[str, Any]) -> None:
        _assert_verify_case(
            result,
            expected_rubric_id,
            expected_status,
            expected_outcomes,
            expected_escalations,
        )

    return _assert


def _build_verify_cases() -> list[BenchCase]:
    symbols = unique_symbol_facts(collect_symbol_facts(_repo_root())[0])[:75]
    assert len(symbols) == 75, "not enough symbols for generated verify cases"

    cases: list[BenchCase] = []
    for index, symbol in enumerate(symbols, start=1):
        base_id = f"bench-verify-{index:03d}-{symbol.name}"
        for status in _STATUS_ORDER:
            rubric_id = f"{base_id}-{status}"
            rubric = {
                "id": rubric_id,
                "domain": "coding.verification",
                "required_checks": ["exists", "validated"] if status in {"pass", "blocked"} else ["exists"],
                "block_if_missing": ["exists"] if status in {"blocked", "escalate"} else [],
                "warning_checks": ["validated"] if status == "warn" else [],
                "escalation_conditions": ["critical_risk"] if status == "escalate" else [],
            }
            if status == "pass":
                checks = {"exists": True, "validated": True}
                expected_outcomes = {"exists": "pass", "validated": "pass"}
                expected_escalations: list[str] = []
            elif status == "warn":
                checks = {"exists": True, "validated": False}
                expected_outcomes = {"exists": "pass", "validated": "warn"}
                expected_escalations = []
            elif status == "blocked":
                checks = {"validated": True}
                expected_outcomes = {"exists": "missing", "validated": "pass"}
                expected_escalations = []
            else:
                checks = {"exists": True, "critical_risk": True}
                expected_outcomes = {"exists": "pass"}
                expected_escalations = ["critical_risk"]

            cases.append(
                BenchCase(
                    op="verify",
                    label=f"verify/{status}/{index:03d}",
                    args={
                        "rubric_id": rubric_id,
                        "checks": checks,
                        "_seed_rubric": rubric,
                    },
                    assert_keys=["rubric_id", "status", "outcomes", "escalations"],
                    custom_assert=_verify_assert(rubric_id, status, expected_outcomes, expected_escalations),
                    baseline_tokens=900,
                )
            )
    return cases


VERIFY_CASES = _build_verify_cases()
