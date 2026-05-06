"""Tests for the runtime benchmark helper workflows."""

from __future__ import annotations

from pathlib import Path

from atelier.infra.runtime.benchmarking import (
    compare_runtime_reports,
    export_runtime_report,
    run_runtime_benchmark,
)


def test_run_runtime_benchmark_writes_report(tmp_path: Path) -> None:
    report = run_runtime_benchmark(
        root=tmp_path / ".atelier",
        prompts=("Fix Shopify publish",),
        model="claude-sonnet-4.6",
        rounds=2,
    )

    assert report["tasks"]
    assert report["aggregate"]["total_calls"] >= 2


def test_compare_and_export_runtime_reports(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    first = run_runtime_benchmark(root=root, prompts=("Fix Shopify publish",), model="claude-sonnet-4.6", rounds=2)
    report_a = root / "benchmarks" / "runtime" / "a.json"
    report_b = root / "benchmarks" / "runtime" / "b.json"
    export_runtime_report(first, output_path=report_a, output_format="json")
    export_runtime_report(first, output_path=report_b, output_format="json")

    comparison = compare_runtime_reports([report_a, report_b])
    csv_path = root / "benchmarks" / "runtime" / "report.csv"
    export_runtime_report(first, output_path=csv_path, output_format="csv")

    assert len(comparison["reports"]) == 2
    assert csv_path.exists()
