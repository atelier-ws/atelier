import json
from collections import defaultdict
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
rows = [r for r in rows if r.get("ok")]

by = defaultdict(list)
for r in rows:
    by[(r["task"], r["arm"])].append(r)

tasks = sorted({t for (t, a) in by if a == "atelier"})
stat = []
for t in tasks:
    b = by.get((t, "baseline"), [])
    a = by.get((t, "atelier"), [])
    if not b or not a:
        continue
    bpr = sum(r.get("cost_usd", 0) for r in b) / len(b)
    apr = sum(r.get("cost_usd", 0) for r in a) / len(a)
    sav = (bpr - apr) / bpr * 100
    stat.append((sav, t, bpr, apr, len(b), len(a)))

stat.sort(reverse=True)
print(f"{'task':28} | base $/rep | atel $/rep | save/rep | % saving")
print("-" * 74)
for sav, t, bpr, apr, _bn, _an in stat:
    print(f"{t.split('__')[-1]:28} | ${bpr:6.2f}    | ${apr:6.2f}    | ${bpr - apr:+6.2f}  | {sav:+6.1f}%")
print("-" * 74)
# weighted (matched per-rep average across overlap)
bt = sum(r.get("cost_usd", 0) for r in rows if r["arm"] == "baseline" and r["task"] in tasks)
bn = len([r for r in rows if r["arm"] == "baseline" and r["task"] in tasks])
at = sum(r.get("cost_usd", 0) for r in rows if r["arm"] == "atelier")
an = len([r for r in rows if r["arm"] == "atelier"])
print(
    f"{'WEIGHTED (all overlap reps)':28} | ${bt / bn:6.2f}    | ${at / an:6.2f}    | ${bt / bn - at / an:+6.2f}  | {(bt / bn - at / an) / (bt / bn) * 100:+6.1f}%"
)
