"""Grade agent diffs with the official Multi-SWE-bench Docker harness.

Each (instance, arm) diff becomes a Patch row ``{org,repo,number,fix_patch}``;
``multi_swe_bench.harness.run_evaluation`` applies it plus the dataset's hidden
``test_patch`` inside the instance image, runs the tests, and writes
``final_report.json`` listing resolved / unresolved instances. We map that back
to ``{instance_id: resolved_bool}`` for the run.py ArmResult grade.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from benchmarks.codebench.multiswe import MultiSweInstance, iter_rows
from benchmarks.codebench.run import REPO_ROOT


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _instance_id(row: dict[str, Any]) -> str:
    return str(row.get("instance_id") or f"{row.get('org')}__{row.get('repo')}-{row.get('number')}")


def _resolved_ids(report: Any) -> set[str]:
    """Extract resolved instance ids from final_report.json, tolerant of shape.

    The report nests resolved ids under keys like ``resolved_instances`` /
    ``resolved_ids`` (sometimes per-language). Collect every string under any
    key containing 'resolved' and not 'unresolved'.
    """
    out: set[str] = set()

    def walk(node: Any, key_hint: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k))
        elif isinstance(node, list):
            keep = "resolved" in key_hint.lower() and "unresolved" not in key_hint.lower()
            for item in node:
                if keep and isinstance(item, str):
                    out.add(item)
                else:
                    walk(item, key_hint)

    walk(report, "")
    return out


def grade(
    instances: list[MultiSweInstance],
    patches: dict[str, str],
    *,
    dataset_path: str | Path,
    work_dir: str | Path,
    max_workers: int = 4,
    timeout: int = 3600,
    force_build: bool = False,
) -> dict[str, bool]:
    """Grade ``patches`` (instance_id -> diff) for ``instances``.

    Returns ``{instance_id: resolved}``. Instances whose grading row is missing
    from the report default to ``False`` (unresolved).
    """
    work = Path(work_dir)
    for sub in ("", "workdir", "out", "repos", "logs"):
        (work / sub).mkdir(parents=True, exist_ok=True)

    ids = {inst.instance_id for inst in instances}
    patch_rows = [inst.patch_row(patches.get(inst.instance_id, "")) for inst in instances]
    dataset_rows = [row for row in iter_rows(dataset_path) if _instance_id(row) in ids]

    patch_file = work / "patch.jsonl"
    dataset_file = work / "dataset.jsonl"
    config_file = work / "config.json"
    _write_jsonl(patch_file, patch_rows)
    _write_jsonl(dataset_file, dataset_rows)

    config = {
        "mode": "evaluation",
        "workdir": str(work / "workdir"),
        "patch_files": [str(patch_file)],
        "dataset_files": [str(dataset_file)],
        "force_build": force_build,
        "output_dir": str(work / "out"),
        "specifics": [],
        "skips": [],
        "repo_dir": str(work / "repos"),
        "need_clone": False,
        "global_env": [],
        "clear_env": True,
        "stop_on_error": False,
        "max_workers": max_workers,
        "max_workers_build_image": max_workers,
        "max_workers_run_instance": max_workers,
        "log_dir": str(work / "logs"),
        "log_level": "INFO",
    }
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

    proc = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT / "benchmarks"),
            "python",
            "-m",
            "multi_swe_bench.harness.run_evaluation",
            "--config",
            str(config_file),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    report_path = next((work / "out").rglob("final_report.json"), None)
    if report_path is None:
        raise RuntimeError(
            f"multi_swe_bench produced no final_report.json (exit {proc.returncode}).\n"
            f"stdout:\n{proc.stdout[-1500:]}\nstderr:\n{proc.stderr[-1500:]}"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    resolved = _resolved_ids(report)
    return {inst.instance_id: (inst.report_id in resolved) for inst in instances}
