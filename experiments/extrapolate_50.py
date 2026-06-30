"""Project 50-task atelier-vs-baseline cost using the completed expensive-task
re-runs. Substitute each re-run task's NEW cost into the established 50-task
A/B (swe50_final_5rep) and recompute the overall saving.

PYTHONPATH=.:src uv run --project benchmarks python experiments/extrapolate_50.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("reports/benchmark/codebench")
BASE_RUN = ROOT / "swe50_final_5rep"
# Re-runs on the CURRENT size-intelligent code_search (+ read fixes).
RERUN_DIRS = [ROOT / "swe50_13449_smart", ROOT / "swe50_exp16_smart"]

_COST_KEYS = ("cost", "cost_usd", "total_cost", "usd", "cost_total")


def _rows(run_dir):
    p = run_dir / "results.jsonl"
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _cost_key(rows):
    if not rows:
        return None
    keys = rows[0].keys()
    for k in _COST_KEYS:
        if k in keys:
            return k
    # fall back: any float field with 'cost' in the name
    for k in keys:
        if "cost" in k.lower():
            return k
    return None


def _avg_cost_per_task(rows, ckey, arm):
    by_task = defaultdict(list)
    for r in rows:
        if r.get("arm") != arm:
            continue
        c = r.get(ckey)
        if isinstance(c, (int, float)):
            by_task[r.get("task")].append(float(c))
    return {t: sum(v) / len(v) for t, v in by_task.items() if v}


def main():
    base_rows = _rows(BASE_RUN)
    rerun_rows = []
    for d in RERUN_DIRS:
        rerun_rows.extend(_rows(d))
    if not base_rows:
        print(f"no rows in {BASE_RUN}/results.jsonl")
        # show what fields exist anywhere
        return
    ckey = _cost_key(base_rows)
    print(f"cost field = {ckey!r}; sample base row keys = {sorted(base_rows[0].keys())}")
    if ckey is None:
        return
    base = _avg_cost_per_task(base_rows, ckey, "baseline")
    atel_old = _avg_cost_per_task(base_rows, ckey, "atelier")
    rkey = _cost_key(rerun_rows) or ckey
    atel_new = _avg_cost_per_task(rerun_rows, rkey, "atelier")

    tasks = sorted(set(base) | set(atel_old))
    n = len(tasks)
    base_tot = sum(base.get(t, 0.0) for t in tasks)
    old_tot = sum(atel_old.get(t, 0.0) for t in tasks)
    # substitute new cost where we have a re-run
    new_tot = 0.0
    swapped = []
    for t in tasks:
        if t in atel_new:
            new_tot += atel_new[t]
            swapped.append((t, atel_old.get(t, 0.0), atel_new[t], base.get(t, 0.0)))
        else:
            new_tot += atel_old.get(t, 0.0)

    def pct(a, b):
        return (b - a) / b * 100 if b else 0.0

    print(f"\ntasks in 50-set A/B: {n}   re-run tasks substituted: {len(swapped)}")
    print(f"\nbaseline 50 total:        ${base_tot:7.2f}")
    print(f"atelier 50 (final_5rep):  ${old_tot:7.2f}   ({pct(old_tot, base_tot):+.1f}% vs baseline)")
    print(f"atelier 50 (w/ re-runs):  ${new_tot:7.2f}   ({pct(new_tot, base_tot):+.1f}% vs baseline)")
    print(f"\nper-task swaps (task: old_atelier -> new_atelier | baseline):")
    swapped.sort(key=lambda x: x[1] - x[2], reverse=True)
    for t, o, nw, b in swapped:
        print(f"  {t[:34]:34} ${o:6.3f} -> ${nw:6.3f}  (saved ${o - nw:+6.3f}) | base ${b:6.3f}")
    sub_old = sum(o for _, o, _, _ in swapped)
    sub_new = sum(nw for _, _, nw, _ in swapped)
    sub_base = sum(b for _, _, _, b in swapped)
    print(
        f"\nre-run subset ({len(swapped)} tasks): atelier ${sub_old:.2f} -> ${sub_new:.2f}  | baseline ${sub_base:.2f}"
    )
    print(f"  subset saving: was {pct(sub_old, sub_base):+.1f}% -> now {pct(sub_new, sub_base):+.1f}% vs baseline")


if __name__ == "__main__":
    sys.exit(main())
