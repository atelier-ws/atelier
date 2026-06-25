import collections
import json
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
all_rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
rows = [r for r in all_rows if r.get("ok")]
bad = len([r for r in all_rows if not r.get("ok")])

# 1) grand per-arm totals across ALL ok=true reps (different task coverage)
print("=== ALL ok=true reps, per arm (full coverage; mixes task sets) ===")
for arm in ("baseline", "atelier"):
    rs = [r for r in rows if r["arm"] == arm]
    tasks = len({r["task"] for r in rs})
    tot = sum(r.get("cost_usd", 0) for r in rs)
    print(f"  {arm:9}: {len(rs):3} reps over {tasks:2} tasks  total=${tot:7.2f}  $/rep=${tot/len(rs):.2f}")

# 2) cost matched on identical (task,rep) cells present in BOTH arms
bycell = collections.defaultdict(dict)
for r in rows:
    bycell[(r["task"], r["rep"])][r["arm"]] = r.get("cost_usd", 0)
B = A = 0.0
n = 0
for (t, rep), d in bycell.items():
    if "baseline" in d and "atelier" in d:
        B += d["baseline"]; A += d["atelier"]; n += 1
print(f"\n=== MATCHED on identical (task,rep) cells [{n} cells, fair] ===")
print(f"  baseline ${B:7.2f}   vs   atelier ${A:7.2f}   ->   atelier {(A-B)/B*100:+.1f}%  (${A-B:+.2f})")

print(f"\n(results.jsonl: {len(all_rows)} rows, {bad} ok=False not yet pruned; live run still writing)")
