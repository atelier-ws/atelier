"""Smoke tests for the deprecated V2 context-savings harness.

The real measured context-savings gate is WP-50's replay benchmark. These tests only
assert that the old harness still loads and serializes for trace continuity.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.swe.savings_bench import _SUITE_YAML, _load_suite, run_savings_bench


def test_context_savings_harness_smoke(tmp_path: Path) -> None:
    result = run_savings_bench(tmp_path)
    assert result.reduction_pct >= 0.0


def test_suite_has_exactly_11_prompts() -> None:
    entries = _load_suite(_SUITE_YAML)
    assert len(entries) == 11


def test_suite_prompt_ids_are_unique() -> None:
    entries = _load_suite(_SUITE_YAML)
    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids))


def test_savings_result_to_dict_is_json_serialisable(tmp_path: Path) -> None:
    result = run_savings_bench(tmp_path)
    payload = result.to_dict()
    dumped = json.dumps(payload)
    reloaded = json.loads(dumped)
    assert "reduction_pct" in reloaded
    assert len(reloaded["prompts"]) == 11
