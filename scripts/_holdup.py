import collections
import json
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
rows = [r for r in rows if r.get("ok")]
grades = json.loads((OUT / "_grades.json").read_text())

def g(r):
    k = f"{r['task']}|{r['arm']}|{r['rep']}"
    return grades[k] if k in grades else r.get("correct")

by = collections.defaultdict(list)
for r in rows:
    by[(r["task"], r["arm"])].append(r)

atel_tasks = sorted({t for (t, a) in by if a == "atelier"})
print(f"{'task':28} | base res/n | atel res/n | $/correct b->a")
print("-" * 74)
for t in atel_tasks:
    b = by.get((t, "baseline"), []); a = by.get((t, "atelier"), [])
    br = sum(1 for r in b if g(r)); ar = sum(1 for r in a if g(r))
    bc = sum(r.get("cost_usd", 0) for r in b); ac = sum(r.get("cost_usd", 0) for r in a)
    bcpc = f"${bc/br:5.2f}" if br else "  --  "
    acpc = f"${ac/ar:5.2f}" if ar else "  --  "
    mark = " atel+" if (ar/len(a) if a else 0) > (br/len(b) if b else 0) else (" base+" if (ar/len(a) if a else 0) < (br/len(b) if b else 0) else " tie")
    print(f"{t:28} | {br}/{len(b):<5} | {ar}/{len(a):<5} | {bcpc} -> {acpc}{mark}")
print("-" * 74)
B = [0, 0, 0.0]; A = [0, 0, 0.0]
for t in atel_tasks:
    for arm, T in (("baseline", B), ("atelier", A)):
        rs = by.get((t, arm), [])
        T[0] += len(rs); T[1] += sum(1 for r in rs if g(r)); T[2] += sum(r.get("cost_usd", 0) for r in rs)
for name, T in (("baseline", B), ("atelier", A)):
    n, r, c = T
    print(f"  {name:9} {r}/{n} resolved ({100*r/n:4.1f}%)  total=${c:7.2f}  $/rep=${c/n:.2f}  cost/correct=${c/r if r else 0:5.2f}")
print(f"\n  cost-per-correct: atelier is {(A[2]/A[1] - B[2]/B[1])/(B[2]/B[1])*100:+.0f}% vs baseline   (over {len(atel_tasks)} tasks atelier has run)")
