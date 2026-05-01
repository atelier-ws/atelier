"""Tests for the action-based benchmark CLI workflow."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atelier.gateway.adapters.cli import cli


def test_benchmark_run_action_writes_runtime_report(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(tmp_path / ".atelier"),
            "benchmark",
            "run",
            "--prompt",
            "Fix Shopify publish",
            "--rounds",
            "2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["tasks"]
    report_path = tmp_path / ".atelier" / "benchmarks" / "runtime" / "latest.json"
    assert report_path.exists()


def test_benchmark_compare_and_export_actions(tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / ".atelier"
    run_one = runner.invoke(
        cli,
        ["--root", str(root), "benchmark", "run", "--prompt", "Fix Shopify publish", "--json"],
    )
    assert run_one.exit_code == 0, run_one.output

    latest = root / "benchmarks" / "runtime" / "latest.json"
    other = root / "benchmarks" / "runtime" / "other.json"
    other.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")

    compare = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "benchmark",
            "compare",
            "--input",
            str(latest),
            "--input",
            str(other),
        ],
    )
    assert compare.exit_code == 0, compare.output
    assert len(json.loads(compare.output)["reports"]) == 2

    export_path = root / "benchmarks" / "runtime" / "report.csv"
    export = runner.invoke(
        cli,
        [
            "--root",
            str(root),
            "benchmark",
            "export",
            "--input",
            str(latest),
            "--output",
            str(export_path),
            "--format",
            "csv",
        ],
    )
    assert export.exit_code == 0, export.output
    assert export_path.exists()


def test_benchmark_core_command_runs(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(tmp_path / ".atelier"),
            "benchmark-core",
            "--prompt",
            "Validate publish workflow",
            "--rounds",
            "2",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["suite"] == "core"
    assert payload["report"]["tasks"]


def test_benchmark_packs_command_runs(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(tmp_path / ".atelier"),
            "benchmark-packs",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["suite"] == "domains"
    assert payload["domains_total"] >= payload["domains_benchmarked"]
