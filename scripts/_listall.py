import json
from collections import defaultdict
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
grades = json.loads((OUT / "_grades.json").read_text())


def g(r):
    k = f"{r['task']}|{r['arm']}|{r['rep']}"
    return grades.get(k, r.get("correct"))


def empty(task, arm, rep):
    pp = OUT / f"{task}_{arm}_rep{rep}.patch"
    return pp.exists() and len(pp.read_text(errors="replace").strip()) == 0


by = defaultdict(list)
for r in rows:
    if r.get("ok"):
        by[(r["task"], r["arm"])].append(r)

tasks = sorted({t for (t, a) in by})
for t in tasks:
    print(f"\n{t}")
    for arm in ("baseline", "atelier"):
        reps = sorted(by.get((t, arm), []), key=lambda r: r["rep"])
        if not reps:
            print(f"  {arm:8} (none)")
            continue
        cells = []
        nres = 0
        for r in reps:
            res = g(r)
            mark = "OK" if res else ("--" if res is False else "??")
            nres += 1 if res else 0
            flag = "∅" if empty(t, arm, r["rep"]) else ""
            cells.append(f"r{r['rep']}:{mark}{flag} ${r.get('cost_usd', 0):4.2f}/{r.get('num_turns', 0):>3}t")
        print(f"  {arm:8} {nres}/{len(reps)}  " + " | ".join(cells))
