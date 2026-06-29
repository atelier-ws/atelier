"""Seed a new run folder for `--resume` so the runner skips all existing
baseline results and only needs to run:
  - missing baseline reps (tasks with <5 reps, or 5 zero-rep tasks)
  - all 50-task x 5-rep atelier arm

Usage:
    uv run python3 benchmarks/codebench/seed_resume_folder.py

Outputs:
    reports/benchmark/codebench/swe50_final_v2/results.jsonl  (baseline rows, grades merged)
    reports/benchmark/codebench/swe50_final_v2/<task>_baseline_rep<N>.patch  (one per row)
    reports/benchmark/codebench/swe50_final_v2/STATUS.txt     (gap report)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path("reports/benchmark/codebench")
SRC = ROOT / "swe50_stress_run1"
DST = ROOT / "swe50_final_v2"

TASKS50 = [l.strip() for l in open("benchmarks/codebench/data/swe50_stress.txt") if l.strip() and not l.startswith("#")]
TARGET_REPS = {1, 2, 3, 4, 5}

# ── load grade lookups ────────────────────────────────────────────────────
# _grades.json: keyed task|arm|rep  (atelier + some baseline)
grades_main: dict[tuple[str, str, int], bool] = {}
for k, v in json.load(open(SRC / "_grades.json")).items():
    parts = k.split("|")
    if len(parts) == 3:
        task, arm, rep_s = parts
        grades_main[(task, arm, int(rep_s))] = bool(v)

# _atel_grades.json: keyed task|rep  (earlier baseline-only pass, no arm in key)
grades_atel: dict[tuple[str, int], bool] = {}
grades_atel_path = SRC / "_atel_grades.json"
if grades_atel_path.exists():
    for k, v in json.load(open(grades_atel_path)).items():
        task, rep_s = k.rsplit("|", 1)
        grades_atel[(task, int(rep_s))] = bool(v)


def best_grade(task: str, rep: int) -> bool | None:
    """Return grade for a baseline (task, rep) from any available source."""
    g = grades_main.get((task, "baseline", rep))
    if g is not None:
        return g
    return grades_atel.get((task, rep))


# ── load all baseline rows from source ─────────────────────────────────────────
# Only keep rows whose tasks are in the swe50 list
task_set = set(TASKS50)
rows: dict[tuple[str, int], dict] = {}
for line in (SRC / "results.jsonl").read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if r.get("arm") != "baseline":
        continue
    if r["task"] not in task_set:
        continue
    rows[(r["task"], r["rep"])] = r

# ── merge grades into ungraded rows ───────────────────────────────────────────
grades_merged = 0
for (task, rep), r in rows.items():
    if r.get("correct") is None:
        g = best_grade(task, rep)
        if g is not None:
            r["correct"] = g
            r["score"] = 1.0 if g else 0.0
            r["judge_model"] = r.get("judge_model") or "swebench"
            grades_merged += 1

# ── create output dir ────────────────────────────────────────────────────────────────
DST.mkdir(parents=True, exist_ok=True)

# ── write results.jsonl (baseline rows only, sorted by task+rep) ──────────────────
out_lines = []
for task in TASKS50:
    for rep in sorted(TARGET_REPS):
        r = rows.get((task, rep))
        if r is not None:
            out_lines.append(json.dumps(r))

(DST / "results.jsonl").write_text("\n".join(out_lines) + ("\n" if out_lines else ""))

# ── copy .patch files (these trigger --resume skip) ─────────────────────────────
patches_copied = 0
patches_missing = []
for task, rep in rows:
    patch_src = SRC / f"{task}_baseline_rep{rep}.patch"
    if patch_src.exists():
        shutil.copy2(patch_src, DST / patch_src.name)
        patches_copied += 1
    else:
        patches_missing.append((task, rep))

# ── gap report ───────────────────────────────────────────────────────────────────
now_graded = sum(1 for r in rows.values() if r.get("correct") is not None)
still_ungraded = sum(1 for r in rows.values() if r.get("correct") is None)

# missing reps per task
missing_reps: dict[str, list[int]] = {}
for task in TASKS50:
    have = {rep for (t, rep) in rows if t == task}
    missing = sorted(TARGET_REPS - have)
    if missing:
        missing_reps[task] = missing

total_missing_baseline = sum(len(v) for v in missing_reps.values())

lines = [
    "=== swe50_final_v2 SEED REPORT ===",
    "",
    f"Source:  {SRC}",
    f"Dest:    {DST}",
    "",
    "--- Baseline rows seeded ---",
    f"  Rows written to results.jsonl : {len(rows)} / 250  (50 tasks x 5 reps)",
    f"  Grades already in results.jsonl : {now_graded - grades_merged}",
    f"  Grades merged from grade files  : {grades_merged}",
    f"  Total graded after merge        : {now_graded}",
    f"  Still ungraded                  : {still_ungraded}",
    f"  .patch files copied             : {patches_copied}",
    f"  .patch files missing (no skip)  : {len(patches_missing)}",
    "",
    "--- What --resume will still run ---",
    f"  Missing baseline reps ({total_missing_baseline} total):",
]
for task, reps in sorted(missing_reps.items()):
    lines.append(f"    {task}: reps {reps}")
lines += [
    "",
    "  Atelier arm: all 250 reps (50 tasks x 5) -- none seeded, all will run",
    "",
    "--- .patch files missing (baseline rows exist but patch not copied) ---",
]
for task, rep in sorted(patches_missing):
    lines.append(f"    {task}_baseline_rep{rep}.patch")

status = "\n".join(lines)
(DST / "STATUS.txt").write_text(status + "\n")
print(status)
