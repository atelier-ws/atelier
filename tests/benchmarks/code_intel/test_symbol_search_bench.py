"""Smoke tests for the Phase 1 code-intel symbol-search benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.code_intel.symbol_search_bench import run_symbol_search_bench


def test_symbol_search_bench_smoke(tmp_path: Path) -> None:
    result = run_symbol_search_bench(tmp_path)

    assert result.result_count >= 1
    assert result.uncached_cache_hit is False
    assert result.cached_cache_hit is True
    assert result.uncached_provenance == "local"
    assert result.cached_provenance == "cached"
    assert result.uncached_total_tokens <= result.budget_tokens


def test_symbol_search_bench_result_is_json_serializable(tmp_path: Path) -> None:
    payload = run_symbol_search_bench(tmp_path).to_dict()

    dumped = json.dumps(payload)
    reloaded = json.loads(dumped)

    assert reloaded["cached_cache_hit"] is True
    assert reloaded["uncached_provenance"] == "local"
