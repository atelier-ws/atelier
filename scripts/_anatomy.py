import json
from collections import defaultdict
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
rows = [r for r in rows if r.get("ok")]

# price per token (opus-4-8)
P = {"in": 5e-6, "out": 25e-6, "cr": 0.5e-6, "cw": 6.25e-6}

# only overlap tasks (atelier ran)
by = defaultdict(list)
for r in rows:
    by[r["arm"]].append(r)
atel_tasks = {r["task"] for r in by["atelier"]}

for arm in ("baseline", "atelier"):
    rs = [r for r in by[arm] if r["task"] in atel_tasks]
    n = len(rs)
    tin = sum(r.get("input_tokens", 0) for r in rs)
    tout = sum(r.get("output_tokens", 0) for r in rs)
    tcr = sum(r.get("cache_read_tokens", 0) for r in rs)
    tcw = sum(r.get("cache_creation_tokens", 0) for r in rs)
    cin, cout, ccr, ccw = tin * P["in"], tout * P["out"], tcr * P["cr"], tcw * P["cw"]
    tot = cin + cout + ccr + ccw
    print(f"=== {arm} (n={n}, overlap tasks) ===")
    print(
        f"  per-rep tokens:  out={tout // n:>7,}  cache_read={tcr // n:>9,}  cache_write={tcw // n:>7,}  input={tin // n:>6,}"
    )
    print(
        f"  per-rep $ split: out=${cout / n:.3f} ({100 * cout / tot:.0f}%)  cacheRead=${ccr / n:.3f} ({100 * ccr / tot:.0f}%)  cacheWrite=${ccw / n:.3f} ({100 * ccw / tot:.0f}%)  input=${cin / n:.3f} ({100 * cin / tot:.0f}%)"
    )
    print(f"  per-rep TOTAL ~${tot / n:.3f}   avg turns={sum(r.get('num_turns', 0) for r in rs) / n:.1f}")
    print()
