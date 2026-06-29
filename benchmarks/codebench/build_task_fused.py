"""Build task_fused.csv: one row per swe50 task, all runs merged.

Columns:
  task
  baseline_reps          -- total rep count across all runs
  baseline_cost_min/max/avg
  baseline_correct_pct   -- % correct across all graded baseline reps
  baseline_correct_frac  -- n_correct/n_graded
  atelier_reps
  atelier_cost_min/max/avg
  atelier_correct_pct
  atelier_correct_frac
  cost_avg_delta_pct     -- (atelier_avg - baseline_avg) / baseline_avg * 100
  correct_pct_delta      -- atelier_correct_pct - baseline_correct_pct
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("reports/benchmark/codebench")
OUT = ROOT / "task_fused.csv"

TASKS50 = [
    line.strip()
    for line in open("benchmarks/codebench/data/swe50_stress.txt")
    if line.strip() and not line.startswith("#")
]
TASK_SET = set(TASKS50)

SKIP_RUNS = {"swe50_final_v2"}  # seeded resume folder -- duplicates stress_run1

# ── accumulate all rows per (task, arm) across every run ─────────────────────────
# key: (task, arm)  value: list of individual rep rows
accum: dict[tuple[str, str], list[dict]] = defaultdict(list)

for jf in sorted(ROOT.rglob("results.jsonl")):
    run = jf.parent.name
    if run in SKIP_RUNS:
        continue
    for ln in jf.read_text().splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r["task"] not in TASK_SET:
            continue
        accum[(r["task"], r["arm"])].append(r)


def arm_stats(rows: list[dict]) -> dict:
    """Summarise a list of rows for one (task, arm) pair."""
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    graded = [r for r in rows if r.get("correct") is not None]
    n_correct = sum(1 for r in graded if r["correct"])

    return {
        "reps": len(rows),
        "cost_min": round(min(costs), 4) if costs else "",
        "cost_max": round(max(costs), 4) if costs else "",
        "cost_avg": round(statistics.mean(costs), 4) if costs else "",
        "n_graded": len(graded),
        "n_correct": n_correct,
        "correct_pct": round(n_correct / len(graded) * 100, 1) if graded else "",
        "correct_frac": f"{n_correct}/{len(graded)}" if graded else "",
    }


# ── write ────────────────────────────────────────────────────────────────────────
COLS = [
    "task",
    "baseline_reps",
    "baseline_cost_min",
    "baseline_cost_max",
    "baseline_cost_avg",
    "baseline_correct_frac",
    "baseline_correct_pct",
    "atelier_reps",
    "atelier_cost_min",
    "atelier_cost_max",
    "atelier_cost_avg",
    "atelier_correct_frac",
    "atelier_correct_pct",
    "cost_avg_delta_pct",
    "correct_pct_delta",
]

with open(OUT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS)
    w.writeheader()

    for task in TASKS50:
        b = arm_stats(accum.get((task, "baseline"), []))
        a = arm_stats(accum.get((task, "atelier"), []))

        # cost delta: atelier cheaper = negative
        if b["cost_avg"] != "" and a["cost_avg"] != "" and b["cost_avg"] != 0:
            cost_delta = round((a["cost_avg"] - b["cost_avg"]) / b["cost_avg"] * 100, 1)
        else:
            cost_delta = ""

        # correctness delta: positive = atelier better
        if b["correct_pct"] != "" and a["correct_pct"] != "":
            correct_delta = round(a["correct_pct"] - b["correct_pct"], 1)
        else:
            correct_delta = ""

        w.writerow(
            {
                "task": task,
                "baseline_reps": b["reps"],
                "baseline_cost_min": b["cost_min"],
                "baseline_cost_max": b["cost_max"],
                "baseline_cost_avg": b["cost_avg"],
                "baseline_correct_frac": b["correct_frac"],
                "baseline_correct_pct": b["correct_pct"],
                "atelier_reps": a["reps"],
                "atelier_cost_min": a["cost_min"],
                "atelier_cost_max": a["cost_max"],
                "atelier_cost_avg": a["cost_avg"],
                "atelier_correct_frac": a["correct_frac"],
                "atelier_correct_pct": a["correct_pct"],
                "cost_avg_delta_pct": cost_delta,
                "correct_pct_delta": correct_delta,
            }
        )

print(f"Written: {OUT}")
print()

# ── print summary table to stdout ──────────────────────────────────────────────────
FMT = (
    f"{'task':<43} {'b_reps':>6} {'b_cost_avg':>10} {'b_correct':>10}"
    f" {'a_reps':>6} {'a_cost_avg':>10} {'a_correct':>10}"
    f" {'costΔ%':>8} {'corrΔpp':>8}"
)
print(FMT)
print("-" * len(FMT))

total_b_reps = total_a_reps = 0
all_b_costs: list[float] = []
all_a_costs: list[float] = []
all_b_correct: list[float] = []
all_a_correct: list[float] = []

for task in TASKS50:
    b = arm_stats(accum.get((task, "baseline"), []))
    a = arm_stats(accum.get((task, "atelier"), []))
    cost_delta = ""
    if b["cost_avg"] != "" and a["cost_avg"] != "" and b["cost_avg"] != 0:
        cost_delta = f"{(a['cost_avg'] - b['cost_avg']) / b['cost_avg'] * 100:+.1f}"
    correct_delta = ""
    if b["correct_pct"] != "" and a["correct_pct"] != "":
        correct_delta = f"{a['correct_pct'] - b['correct_pct']:+.1f}"

    b_corr = f"{b['correct_pct']}%" if b["correct_pct"] != "" else ""
    a_corr = f"{a['correct_pct']}%" if a["correct_pct"] != "" else ""
    print(
        f"{task:<43} {b['reps']:>6} {b['cost_avg']!s:>10} {b_corr:>10}"
        f" {a['reps']:>6} {a['cost_avg']!s:>10} {a_corr:>10}"
        f" {cost_delta!s:>8} {correct_delta!s:>8}"
    )
    total_b_reps += b["reps"]
    total_a_reps += a["reps"]
    if b["cost_avg"] != "":
        all_b_costs.append(b["cost_avg"])
    if a["cost_avg"] != "":
        all_a_costs.append(a["cost_avg"])
    if b["correct_pct"] != "":
        all_b_correct.append(b["correct_pct"])
    if a["correct_pct"] != "":
        all_a_correct.append(a["correct_pct"])

print("-" * len(FMT))
b_avg_cost = f"{statistics.mean(all_b_costs):.4f}" if all_b_costs else ""
a_avg_cost = f"{statistics.mean(all_a_costs):.4f}" if all_a_costs else ""
b_avg_corr = f"{statistics.mean(all_b_correct):.1f}%" if all_b_correct else ""
a_avg_corr = f"{statistics.mean(all_a_correct):.1f}%" if all_a_correct else ""
cost_d = (
    f"{(statistics.mean(all_a_costs) - statistics.mean(all_b_costs)) / statistics.mean(all_b_costs) * 100:+.1f}"
    if all_b_costs and all_a_costs
    else ""
)
corr_d = (
    f"{statistics.mean(all_a_correct) - statistics.mean(all_b_correct):+.1f}" if all_b_correct and all_a_correct else ""
)
print(
    f"{'TOTAL/AVG':<43} {total_b_reps:>6} {b_avg_cost:>10} {b_avg_corr:>10}"
    f" {total_a_reps:>6} {a_avg_cost:>10} {a_avg_corr:>10}"
    f" {cost_d:>8} {corr_d:>8}"
)
