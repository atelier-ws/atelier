from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_benchmarks_package() -> None:
    benchmarks_pkg = types.ModuleType("benchmarks")
    benchmarks_pkg.__path__ = [str(ROOT / "benchmarks")]
    mcp_pkg = types.ModuleType("benchmarks.mcp_tools")
    mcp_pkg.__path__ = [str(ROOT / "benchmarks" / "mcp_tools")]
    sys.modules["benchmarks"] = benchmarks_pkg
    sys.modules["benchmarks.mcp_tools"] = mcp_pkg


def test_generate_case_manifest_respects_small_quotas(tmp_path: Path) -> None:
    _ensure_benchmarks_package()
    src = tmp_path / "src" / "atelier"
    src.mkdir(parents=True)
    for index in range(1, 9):
        (src / f"mod_{index}.py").write_text(
            "\n".join(
                [
                    f"class Class{index}:",
                    f"    def method_{index}(self) -> int:",
                    f"        return {index}",
                    "",
                    f"def alpha{index}_bridgecase() -> int:",
                    f"    return Class{index}().method_{index}()",
                    "",
                    f"def beta{index}_bridgecase() -> int:",
                    f"    return alpha{index}_bridgecase()",
                    "",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    module = _load_module(
        "benchmarks.mcp_tools.external_matrix_cases",
        ROOT / "benchmarks" / "mcp_tools" / "external_matrix_cases.py",
    )
    quotas = {
        "exact_symbol": 4,
        "exact_search": 4,
        "substring_search": 4,
        "file_outline": 4,
        "nohit_search": 2,
    }

    cases = module.generate_case_manifest(tmp_path, case_quotas=quotas)

    assert len(cases) == sum(quotas.values())
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.family] = counts.get(case.family, 0) + 1
    assert counts == quotas
    assert len({case.case_id for case in cases}) == len(cases)


def test_score_case_accepts_substring_query_evidence() -> None:
    _ensure_benchmarks_package()
    cases_module = _load_module(
        "benchmarks.mcp_tools.external_matrix_cases",
        ROOT / "benchmarks" / "mcp_tools" / "external_matrix_cases.py",
    )
    runner_module = _load_module(
        "benchmarks.mcp_tools.bench_external_matrix",
        ROOT / "benchmarks" / "mcp_tools" / "bench_external_matrix.py",
    )
    case = cases_module.ExternalBenchCase(
        case_id="substring-search-0001",
        family="substring_search",
        query="activity",
        expected_paths=("src/atelier/core/capabilities/swarm/capability.py",),
        expected_names=("_update_child_activity",),
    )

    assert (
        runner_module.score_case(
            case,
            "src/atelier/core/capabilities/swarm/capability.py activity",
        )
        == 1.0
    )


def test_summarize_results_adds_atelier_comparison_columns() -> None:
    _ensure_benchmarks_package()
    runner_module = _load_module(
        "benchmarks.mcp_tools.bench_external_matrix",
        ROOT / "benchmarks" / "mcp_tools" / "bench_external_matrix.py",
    )
    rows = [
        runner_module.CaseBenchResult(
            case_id="case-1",
            family="substring_search",
            tool="atelier",
            status="ok",
            correctness=1.0,
            median_ms=50,
            p95_ms=50,
            median_tokens=100,
            runs=1,
            query="activity",
        ),
        runner_module.CaseBenchResult(
            case_id="case-1",
            family="substring_search",
            tool="other",
            status="ok",
            correctness=0.5,
            median_ms=100,
            p95_ms=100,
            median_tokens=400,
            runs=1,
            query="activity",
        ),
    ]

    summary = runner_module.summarize_results(rows)
    other = next(row for row in summary if row["tool"] == "other")

    assert other["atelier_score_result"] == "atelier better"
    assert other["atelier_score_vs_provider_pct"] == "+100.0%"
    assert other["atelier_latency_vs_provider_pct"] == "+50.0%"
    assert other["atelier_tokens_vs_provider_pct"] == "+75.0%"


def test_balanced_case_subset_round_robins_families() -> None:
    _ensure_benchmarks_package()
    cases_module = _load_module(
        "benchmarks.mcp_tools.external_matrix_cases",
        ROOT / "benchmarks" / "mcp_tools" / "external_matrix_cases.py",
    )
    runner_module = _load_module(
        "benchmarks.mcp_tools.bench_external_matrix",
        ROOT / "benchmarks" / "mcp_tools" / "bench_external_matrix.py",
    )
    cases = [
        cases_module.ExternalBenchCase(case_id="a1", family="exact_symbol", query="a"),
        cases_module.ExternalBenchCase(case_id="b1", family="exact_search", query="b"),
        cases_module.ExternalBenchCase(case_id="c1", family="substring_search", query="c"),
        cases_module.ExternalBenchCase(case_id="a2", family="exact_symbol", query="a2"),
        cases_module.ExternalBenchCase(case_id="b2", family="exact_search", query="b2"),
        cases_module.ExternalBenchCase(case_id="c2", family="substring_search", query="c2"),
    ]

    subset = runner_module._balanced_case_subset(cases, 5)

    assert [case.case_id for case in subset] == ["b1", "a1", "c1", "b2", "a2"]
