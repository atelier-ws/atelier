"""Unit tests for the SWE-bench (Python) backend folded into ``atelier benchmark swe``.

No Docker / network: the loader reads a local JSONL (swebench supports it) and
the grader's harness subprocess is stubbed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from benchmarks.codebench import swebench_data, swebench_grade


def _row(instance_id: str, *, n_files: int, repo: str = "o/r", base: str = "abc") -> dict[str, Any]:
    patch = "".join(f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n" for i in range(n_files))
    return {
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": base,
        "problem_statement": f"fix {instance_id}",
        "patch": patch,
        "test_patch": "diff --git a/t.py b/t.py\n",
        "FAIL_TO_PASS": "[]",
        "PASS_TO_PASS": "[]",
    }


def _write(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "swe.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_image_ref_namespaces_and_rewrites_double_underscore() -> None:
    assert (
        swebench_data.image_ref("astropy__astropy-12907")
        == "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"
    )


def test_load_instances_filters_single_file_and_targets_testbed(tmp_path: Path) -> None:
    rows = [
        _row("o__r-2", n_files=2),  # keep (multi-file)
        _row("o__r-1", n_files=1),  # drop: single-file
    ]
    insts = swebench_data.load_instances(dataset=str(_write(tmp_path, rows)))
    assert [i.instance_id for i in insts] == ["o__r-2"]
    inst = insts[0]
    assert inst.language == "python"
    assert inst.repo_dir == "/testbed"
    assert inst.image == "swebench/sweb.eval.x86_64.o_1776_r-2:latest"
    assert inst.changed_files == 2
    assert inst.problem_statement == "fix o__r-2"


def test_load_instances_respects_limit_and_instance_filter(tmp_path: Path) -> None:
    path = _write(tmp_path, [_row(f"o__r-{n}", n_files=2) for n in (2, 3, 4)])
    assert [i.instance_id for i in swebench_data.load_instances(dataset=str(path), limit=2)] == ["o__r-2", "o__r-3"]
    only = swebench_data.load_instances(dataset=str(path), instances=["o__r-4"])
    assert [i.instance_id for i in only] == ["o__r-4"]


def test_strip_gold_test_files_drops_colliding_sections() -> None:
    """Sections for files the gold test patch owns are dropped; solution code stays."""
    model_patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/tests/roots/r/conf.py b/tests/roots/r/conf.py\n"
        "new file mode 100644\n--- /dev/null\n+++ b/tests/roots/r/conf.py\n@@ -0,0 +1 @@\n+pass\n"
    )
    gold_test = (
        "diff --git a/tests/roots/r/conf.py b/tests/roots/r/conf.py\n"
        "diff --git a/tests/test_x.py b/tests/test_x.py\n"
    )
    out = swebench_grade._strip_gold_test_files(model_patch, gold_test)
    assert "a/src/app.py" in out  # solution code kept
    assert "tests/roots/r/conf.py" not in out  # gold owns it -> dropped to avoid collision
    # No gold test patch (or empty model patch) -> unchanged passthrough.
    assert swebench_grade._strip_gold_test_files(model_patch, "") == model_patch
    assert swebench_grade._strip_gold_test_files("", gold_test) == ""


def test_grade_writes_predictions_and_parses_resolved(tmp_path: Path, monkeypatch: Any) -> None:
    insts = [
        swebench_data.SweBenchInstance("o__r-2", "o/r", "abc", "python", "img2", "fix", 2),
        swebench_data.SweBenchInstance("o__r-3", "o/r", "def", "python", "img3", "fix", 2),
    ]
    patches = {"o__r-2": "DIFF2", "o__r-3": ""}
    captured: dict[str, Any] = {}

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        cwd = Path(kwargs["cwd"])
        captured["cmd"] = cmd
        captured["preds"] = [
            json.loads(line) for line in (cwd / "predictions.jsonl").read_text().splitlines() if line.strip()
        ]
        report = {"resolved_ids": ["o__r-2"], "unresolved_ids": ["o__r-3"]}
        (cwd / f"atelier-codebench.{cwd.name}.json").write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(swebench_grade.subprocess, "run", _fake_run)
    resolved = swebench_grade.grade(insts, patches, work_dir=tmp_path / "grade_atelier_rep1", dataset_name="X")

    assert resolved == {"o__r-2": True, "o__r-3": False}
    preds = captured["preds"]
    assert {p["instance_id"] for p in preds} == {"o__r-2", "o__r-3"}
    assert all(p["model_name_or_path"] == "atelier-codebench" for p in preds)
    assert next(p for p in preds if p["instance_id"] == "o__r-2")["model_patch"] == "DIFF2"
    cmd = captured["cmd"]
    assert cmd[cmd.index("--dataset_name") + 1] == "X"
    assert cmd[cmd.index("--run_id") + 1] == "grade_atelier_rep1"
    assert cmd[cmd.index("--namespace") + 1] == "swebench"
    assert "--instance_ids" in cmd
