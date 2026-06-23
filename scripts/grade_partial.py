"""Grade whatever atelier rep1 patches have finished so far, into a separate dir.

Re-runnable: discovers *_atelier_rep1.patch files in the run dir, grades them with
the swebench harness into grade_partial_rep1/ (separate run_id from the final
grade_atelier_rep1/, so it never collides with the still-running solve).
"""

from __future__ import annotations

import sys
from pathlib import Path

from benchmarks.codebench import swebench_data, swebench_grade

RUN_DIR = Path("reports/benchmark/codebench/postremoval_swe30_rep1")
ARM = "atelier"
REP = 1


def main() -> int:
    suffix = f"_{ARM}_rep{REP}.patch"
    patch_files = sorted(RUN_DIR.glob(f"*{suffix}"))
    task_ids = [p.name[: -len(suffix)] for p in patch_files]
    if not task_ids:
        print("[partial-grade] no finished patches yet")
        return 0
    print(f"[partial-grade] {len(task_ids)} finished: {task_ids}", flush=True)

    insts = swebench_data.load_instances(dataset=None, instances=task_ids, min_changed_files=1)
    by_id = {i.instance_id: i for i in insts}
    patches = {
        tid: (RUN_DIR / f"{tid}{suffix}").read_text(encoding="utf-8")
        for tid in task_ids
        if tid in by_id and (RUN_DIR / f"{tid}{suffix}").exists()
    }

    work_dir = (RUN_DIR / "grade_partial_rep1").resolve()
    resolved = swebench_grade.grade(
        list(by_id.values()),
        patches,
        dataset_name=None,
        work_dir=work_dir,
        max_workers=1,
        timeout=1800,
    )
    print("[partial-grade] === results ===", flush=True)
    for tid in task_ids:
        print(f"  {tid}: resolved={bool(resolved.get(tid, False))}")
    n = sum(1 for tid in task_ids if resolved.get(tid))
    print(f"[partial-grade] resolved {n}/{len(task_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
