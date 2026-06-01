from __future__ import annotations

import csv
import importlib
import sys
import types
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _ensure_benchmarks_package() -> None:
    benchmarks_pkg = types.ModuleType("benchmarks")
    benchmarks_pkg.__path__ = [str(ROOT / "benchmarks")]
    vix_pkg = types.ModuleType("benchmarks.eval")
    vix_pkg.__path__ = [str(ROOT / "benchmarks" / "eval")]
    sys.modules["benchmarks"] = benchmarks_pkg
    sys.modules["benchmarks.eval"] = vix_pkg


def _load(module_name: str) -> ModuleType:
    _ensure_benchmarks_package()
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


VIX = _load("benchmarks.eval.run")


def test_write_csv_artifacts_emits_detail_and_summary(tmp_path: Path) -> None:
    results = [
        VIX.ArmResult(
            task="task-1",
            arm="baseline",
            rep=0,
            ok=True,
            cost_usd=1.25,
            duration_ms=1000,
            duration_api_ms=800,
            num_turns=3,
            input_tokens=100,
            cache_read_tokens=10,
            cache_creation_tokens=0,
            output_tokens=25,
            models=["sonnet"],
            is_error=False,
            result_excerpt="ok",
            flow_path="baseline.flow",
        ),
        VIX.ArmResult(
            task="task-1",
            arm="atelier",
            rep=0,
            ok=True,
            cost_usd=0.75,
            duration_ms=700,
            duration_api_ms=500,
            num_turns=2,
            input_tokens=70,
            cache_read_tokens=20,
            cache_creation_tokens=5,
            output_tokens=20,
            models=["sonnet"],
            is_error=False,
            result_excerpt="ok",
            flow_path="atelier.flow",
        ),
    ]

    VIX.write_csv_artifacts(tmp_path, results)

    with (tmp_path / "results.csv").open("r", encoding="utf-8", newline="") as handle:
        detail_rows = list(csv.DictReader(handle))
    with (tmp_path / "summary.csv").open("r", encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))

    assert len(detail_rows) == 2
    assert {row["arm"] for row in summary_rows} == {"baseline", "atelier"}
    atelier_row = next(row for row in summary_rows if row["arm"] == "atelier")
    assert atelier_row["cost_usd"] == "0.75"
