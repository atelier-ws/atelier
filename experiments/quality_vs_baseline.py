"""Quality-adjusted size-intelligent atelier vs baseline, on every task we have
a size-intelligent result for. Cost AND resolve-rate (cheaper-but-wrong != win).

baseline = swe50_final_5rep (5 reps/task); atelier = the 3 size-intelligent dirs
(1 rep/task). Reports baseline both as rep1 (1-v-1 fair) and mean-over-5 reps.

PYTHONPATH=.:src uv run --project benchmarks python experiments/quality_vs_baseline.py
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("reports/benchmark/codebench")
SI_DIRS = ["swe50_13449_smart", "swe50_exp16_smart", "swe50_rest33_smart"]
BASE = "swe50_final_5rep"


def rows(d):
    p = ROOT / d / "results.jsonl"
    out = []
    if p.exists():
        for ln in p.read_text().splitlines():
            if ln.strip():
                out.append(json.loads(ln))
    return out


# atelier size-intelligent: 1 rep/task
si = {}
for d in SI_DIRS:
    for r in rows(d):
        if r.get("arm") == "atelier":
            si[r["task"]] = (float(r["cost_usd"]), bool(r.get("correct")))

# baseline: gather all reps per task
base_cost = defaultdict(list)
base_corr = defaultdict(list)
base_rep1 = {}
for r in rows(BASE):
    if r.get("arm") != "baseline":
        continue
    t = r["task"]
    base_cost[t].append(float(r["cost_usd"]))
    base_corr[t].append(bool(r.get("correct")))
    if r.get("rep") == 1:
        base_rep1[t] = bool(r.get("correct"))

tasks = sorted(t for t in si if t in base_cost)
N = len(tasks)
a_cost = sum(si[t][0] for t in tasks)
a_corr = sum(1 for t in tasks if si[t][1])
b_cost_mean = sum(sum(base_cost[t]) / len(base_cost[t]) for t in tasks)
b_corr_rate = sum(sum(base_corr[t]) / len(base_corr[t]) for t in tasks)  # expected #resolved
b_rep1_corr = sum(1 for t in tasks if base_rep1.get(t))

print(f"tasks compared (size-intelligent result exists): {N}")
print("\n=== COST ===")
print(f"  atelier (size-intel, 1 rep):  ${a_cost:7.2f}")
print(f"  baseline (mean of 5 reps):    ${b_cost_mean:7.2f}")
print(f"  -> atelier is {(b_cost_mean - a_cost) / b_cost_mean * 100:+.1f}% vs baseline (positive = cheaper)")
print("\n=== CORRECTNESS (resolve rate) ===")
print(f"  atelier (size-intel, 1 rep):  {a_corr}/{N}  = {a_corr / N * 100:.0f}%")
print(f"  baseline (rep1, 1-v-1):       {b_rep1_corr}/{N}  = {b_rep1_corr / N * 100:.0f}%")
print(f"  baseline (expected, 5-rep):   {b_corr_rate:.1f}/{N}  = {b_corr_rate / N * 100:.0f}%")
print("\n=== QUALITY-ADJUSTED ($/resolved task) ===")
if a_corr:
    print(f"  atelier:  ${a_cost / a_corr:.3f} per resolved")
if b_corr_rate:
    print(f"  baseline: ${b_cost_mean / b_corr_rate:.3f} per resolved (5-rep expected)")
if b_rep1_corr:
    print(f"  baseline: ${b_cost_mean / b_rep1_corr:.3f} per resolved (rep1)")

# disagreements: where atelier wrong but baseline (mostly) right, and vice-versa
print("\n=== correctness disagreements ===")
for t in tasks:
    ac = si[t][1]
    br = sum(base_corr[t]) / len(base_corr[t])
    if ac and br < 0.5:
        print(f"  atelier WON  (base {br:.0%}): {t}")
    if not ac and br >= 0.5:
        print(f"  atelier LOST (base {br:.0%}): {t}  atelier=${si[t][0]:.2f}")
