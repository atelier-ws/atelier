"""Build task_matrix.csv: one row per swe50 task, columns grouped by run.

Column layout:
  task | baseline[run1]_cost | baseline[run1]_correct | atelier[run1]_cost | atelier[run1]_correct | ...

Cost = median USD across reps (rounded to 4dp).
Correct = "n/total" fraction when multi-rep, or True/False/"" when 1-rep / ungraded.

Only runs with at least one graded result on a swe50 task are included.
Runs are sorted: paired-arm runs first, then atelier-only, alphabetically within each group.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("reports/benchmark/codebench")
OUT = ROOT / "task_matrix.csv"

TASKS50 = [
    line.strip()
    for line in open("benchmarks/codebench/data/swe50_stress.txt")
    if line.strip() and not line.startswith("#")
]
TASK_SET = set(TASKS50)

# ── load all runs ──────────────────────────────────────────────────────────────────
# run_data[run_name][(task, arm)] = list of rows
run_data: dict[str, dict[tuple[str, str], list[dict]]] = {}

for jf in sorted(ROOT.rglob("results.jsonl")):
    run = jf.parent.name
    if run == "swe50_final_v2":  # seeded resume folder -- skip (duplicates stress_run1)
        continue
    rows = [json.loads(ln) for ln in jf.read_text().splitlines() if ln.strip()]
    # filter to swe50 tasks with at least one graded row in this run
    swe50_rows = [r for r in rows if r["task"] in TASK_SET]
    if not any(r.get("correct") is not None for r in swe50_rows):
        continue
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in swe50_rows:
        by_key[(r["task"], r["arm"])].append(r)
    if not by_key:
        continue
    run_data[run] = dict(by_key)


def summarise(rows: list[dict]) -> tuple[str, str]:
    """Return (cost_str, correct_str) for a list of same-(task,arm) rows."""
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    cost_s = f"{statistics.median(costs):.4f}" if costs else ""

    graded = [r for r in rows if r.get("correct") is not None]
    if not graded:
        correct_s = ""
    elif len(graded) == 1:
        correct_s = "1" if graded[0]["correct"] else "0"
    else:
        n_correct = sum(1 for r in graded if r["correct"])
        correct_s = f"{n_correct}/{len(graded)}"
    return cost_s, correct_s


# ── sort runs: paired first, then atelier-only, alpha within each group ───────────────
def run_arms(run: str) -> set[str]:
    return {arm for (_, arm) in run_data[run]}


paired = sorted(r for r in run_data if {"baseline", "atelier"} <= run_arms(r))
atel_only = sorted(r for r in run_data if "baseline" not in run_arms(r))
base_only = sorted(r for r in run_data if "atelier" not in run_arms(r))
ordered_runs = paired + atel_only + base_only

# ── build columns ───────────────────────────────────────────────────────────────────
cols = ["task"]
for run in ordered_runs:
    arms_present = run_arms(run)
    for arm in ("baseline", "atelier"):
        if arm in arms_present or {"baseline", "atelier"} <= arms_present:
            cols.append(f"{arm}[{run}]_cost")
            cols.append(f"{arm}[{run}]_correct")

# ── write ────────────────────────────────────────────────────────────────────────
with open(OUT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
    w.writeheader()

    for task in TASKS50:
        row: dict[str, str] = {"task": task}
        for run in ordered_runs:
            arms_present = run_arms(run)
            for arm in ("baseline", "atelier"):
                cost_col = f"{arm}[{run}]_cost"
                correct_col = f"{arm}[{run}]_correct"
                if cost_col not in cols:
                    continue
                arm_rows = run_data[run].get((task, arm), [])
                if arm_rows:
                    c, g = summarise(arm_rows)
                    row[cost_col] = c
                    row[correct_col] = g
                else:
                    row[cost_col] = ""
                    row[correct_col] = ""
        w.writerow(row)

print(f"Written {OUT}")
print(
    f"Runs included: {len(ordered_runs)}  (paired={len(paired)}, atelier-only={len(atel_only)}, baseline-only={len(base_only)})"
)
print(f"Columns: {len(cols)}")
print()
print("Run order:")
for run in ordered_runs:
    arms = sorted(run_arms(run))
    tasks_covered = len({t for (t, _) in run_data[run]})
    print(f"  {run:<45} arms={arms}  tasks={tasks_covered}")
