import json
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
ag = json.loads((OUT / "_atel_grades.json").read_text())

def res(r):
    if r["arm"] == "atelier":
        return ag.get(f"{r['task']}|{r['rep']}")
    return r.get("correct")

for t in ("astropy__astropy-13398", "django__django-13344", "mwaskom__seaborn-3187", "astropy__astropy-8707"):
    print(f"=== {t} ===")
    for r in sorted([x for x in rows if x["task"] == t], key=lambda x: (x["arm"], x["rep"])):
        print(f"  {r['arm']:8} rep{r['rep']}  turns={r.get('num_turns'):3}  ${r.get('cost_usd',0):5.2f}  resolved={res(r)}")

# correlation: among graded reps, does hitting >=40 turns mean lower resolve?
print("\n=== resolve rate by turn bucket (all graded reps, both arms) ===")
bk = {"<20": [0, 0], "20-39": [0, 0], ">=40": [0, 0]}
for r in rows:
    rr = res(r)
    if rr is None:
        continue
    tn = r.get("num_turns", 0)
    k = "<20" if tn < 20 else ("20-39" if tn < 40 else ">=40")
    bk[k][0] += 1 if rr else 0
    bk[k][1] += 1
for k, (good, tot) in bk.items():
    print(f"  {k:6}: {good}/{tot} resolved ({100*good/tot if tot else 0:.0f}%)")
