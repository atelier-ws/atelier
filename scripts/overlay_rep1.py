"""Build the post-removal atelier rep1 overlay vs the swe30_run1 baseline.

Authoritative correctness = grade report.json `resolved` field per (arm, rep).
Cost = results.csv per-rep cost_usd.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

BASE = Path("reports/benchmark/codebench/swe30_run1_20260622T043715Z")
NEW = Path("reports/benchmark/codebench/postremoval_swe30_rep1")
DEAD = {"astropy__astropy-8707"}  # harness-dead (pytest-7.4.0 nose collection error), 0/3 both arms
TIMEOUT = {"scikit-learn__scikit-learn-25102"}  # new rep1 hit 30-min wall, empty patch, cost=$0 not captured


def load_resolved(grade_dir: Path) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for rj in grade_dir.rglob("report.json"):
        for task, rec in json.loads(rj.read_text()).items():
            out[task] = bool(rec.get("resolved", False))
    return out


def load_costs(results_csv: Path) -> dict[tuple[str, str, str], float]:
    out: dict[tuple[str, str, str], float] = {}
    with results_csv.open() as f:
        for row in csv.DictReader(f):
            out[(row["task"], row["arm"], row["rep"])] = float(row["cost_usd"])
    return out


base_resolved: dict[str, dict[int, bool]] = defaultdict(dict)
old_resolved: dict[str, dict[int, bool]] = defaultdict(dict)
for rep in (1, 2, 3):
    for task, r in load_resolved(BASE / f"grade_baseline_rep{rep}").items():
        base_resolved[task][rep] = r
    for task, r in load_resolved(BASE / f"grade_atelier_rep{rep}").items():
        old_resolved[task][rep] = r
new_resolved = load_resolved(NEW / "grade_atelier_rep1")
base_rep1 = load_resolved(BASE / "grade_baseline_rep1")
old_rep1 = load_resolved(BASE / "grade_atelier_rep1")

base_costs = load_costs(BASE / "results.csv")
new_costs = load_costs(NEW / "results.csv")
tasks = sorted(set(base_resolved) | {k[0] for k in new_costs})


def n3(d: dict[int, bool]) -> int:
    return sum(1 for rep in (1, 2, 3) if d.get(rep))


def costs3(task: str, arm: str) -> list[float]:
    return [base_costs.get((task, arm, str(rep)), float("nan")) for rep in (1, 2, 3)]


def avg(cs: list[float]) -> float:
    vals = [c for c in cs if c == c]
    return sum(vals) / len(vals) if vals else float("nan")


print("task,vanilla_n3,old_atelier_n3,new_rep1,vanilla_cost_avg,old_cost_avg,new_cost,sav_vs_vanilla_pct,note")
for task in tasks:
    van_avg = avg(costs3(task, "baseline"))
    old_avg = avg(costs3(task, "atelier"))
    new_cost = new_costs.get((task, "atelier", "1"), float("nan"))
    new_r = new_resolved.get(task)
    new_r_str = {True: "1/1", False: "0/1", None: "-"}[new_r]
    note = "DEAD" if task in DEAD else ("TIMEOUT" if task in TIMEOUT else "")
    sav = (van_avg - new_cost) / van_avg * 100 if van_avg == van_avg and new_cost == new_cost else float("nan")
    print(
        f"{task},{n3(base_resolved.get(task, {}))}/3,{n3(old_resolved.get(task, {}))}/3,"
        f"{new_r_str},{van_avg:.4f},{old_avg:.4f},{new_cost:.4f},{sav:.1f},{note}"
    )


def agg(exclude: set[str], label: str) -> None:
    sub = [t for t in tasks if t not in exclude]
    van = sum(avg(costs3(t, "baseline")) for t in sub if avg(costs3(t, "baseline")) == avg(costs3(t, "baseline")))
    old = sum(avg(costs3(t, "atelier")) for t in sub if avg(costs3(t, "atelier")) == avg(costs3(t, "atelier")))
    new = sum(new_costs.get((t, "atelier", "1"), 0.0) for t in sub)
    n = len(sub)
    # correctness: rep1-vs-rep1 (fairest), plus baseline-arm majority-of-3
    van_r1 = sum(1 for t in sub if base_rep1.get(t))
    old_r1 = sum(1 for t in sub if old_rep1.get(t))
    new_r1 = sum(1 for t in sub if new_resolved.get(t))
    van_maj = sum(1 for t in sub if n3(base_resolved.get(t, {})) >= 2)
    old_maj = sum(1 for t in sub if n3(old_resolved.get(t, {})) >= 2)
    print(f"\n=== {label} ({n} tasks) ===")
    print(f"cost/rep:  vanilla ${van:.2f}  | old-atelier ${old:.2f}  | new-atelier-rep1 ${new:.2f}")
    print(
        f"savings new-atelier rep1 vs vanilla: {(van - new) / van * 100:.1f}%   vs old-atelier: {(old - new) / old * 100:.1f}%"
    )
    print(f"correctness rep1-vs-rep1:  vanilla {van_r1}/{n}  | old-atelier {old_r1}/{n}  | new-atelier {new_r1}/{n}")
    print(f"correctness baseline-arms majority-of-3:  vanilla {van_maj}/{n}  | old-atelier {old_maj}/{n}")


agg(set(), "ALL")
agg(DEAD, "excl harness-dead astropy-8707")
agg(DEAD | TIMEOUT, "clean set: excl harness-dead + new-rep1 timeout")
