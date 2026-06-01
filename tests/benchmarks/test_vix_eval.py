from __future__ import annotations

import csv
import importlib
import json
import sys
import types
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _ensure_benchmarks_package() -> None:
    benchmarks_pkg = types.ModuleType("benchmarks")
    benchmarks_pkg.__path__ = [str(ROOT / "benchmarks")]
    vix_pkg = types.ModuleType("benchmarks.vix_eval")
    vix_pkg.__path__ = [str(ROOT / "benchmarks" / "vix_eval")]
    sys.modules["benchmarks"] = benchmarks_pkg
    sys.modules["benchmarks.vix_eval"] = vix_pkg


def _load(module_name: str) -> ModuleType:
    _ensure_benchmarks_package()
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


VIX = _load("benchmarks.vix_eval.run")
TASKS = _load("benchmarks.vix_eval.tasks")


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


def test_task_prompt_prefers_variant_prompt_when_prompt_md_missing(tmp_path: Path, monkeypatch) -> None:
    vix_dir = tmp_path / "vix-eval"
    task_dir = vix_dir / "tasks" / "task2_variant"
    task_dir.mkdir(parents=True)
    (task_dir / "prompt_medium.md").write_text("medium prompt", encoding="utf-8")
    (task_dir / "prompt_hard.md").write_text("hard prompt", encoding="utf-8")
    monkeypatch.setenv("VIX_EVAL_DIR", str(vix_dir))

    task = TASKS.Task("task2", "swift", ("empty",), 1, "task2_variant")

    assert task.prompt() == "hard prompt"


def test_main_resume_skips_existing_runs(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    existing = VIX.ArmResult(
        task="task-1",
        arm="baseline",
        rep=0,
        ok=True,
        cost_usd=1.0,
        duration_ms=10,
        duration_api_ms=9,
        num_turns=1,
        input_tokens=11,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        output_tokens=7,
        models=["sonnet"],
        is_error=False,
        result_excerpt="ok",
        flow_path="baseline.flow",
    )
    (run_dir / "results.jsonl").write_text(json.dumps(existing.__dict__) + "\n", encoding="utf-8")

    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")
    monkeypatch.setattr(VIX, "TASKS", [task])
    monkeypatch.setattr(VIX, "BY_ID", {task.id: task})

    calls: list[tuple[str, str, int]] = []

    def fake_run_arm(
        task_obj: TASKS.Task,
        arm: str,
        rep: int,
        model: str,
        out_dir: Path,
        timeout: int,
    ) -> VIX.ArmResult:
        del model, out_dir, timeout
        calls.append((task_obj.id, arm, rep))
        return VIX.ArmResult(
            task=task_obj.id,
            arm=arm,
            rep=rep,
            ok=True,
            cost_usd=0.5,
            duration_ms=5,
            duration_api_ms=4,
            num_turns=1,
            input_tokens=6,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            output_tokens=3,
            models=["sonnet"],
            is_error=False,
            result_excerpt="ok",
            flow_path=f"{arm}.flow",
        )

    monkeypatch.setattr(VIX, "run_arm", fake_run_arm)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--tasks",
            "task-1",
            "--arms",
            "baseline",
            "atelier",
            "--reps",
            "1",
            "--out",
            str(run_dir),
            "--resume",
        ],
    )

    assert VIX.main() == 0
    assert calls == [("task-1", "atelier", 0)]
