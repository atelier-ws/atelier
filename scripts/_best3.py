import json
from collections import defaultdict
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
rows = [r for r in rows if r.get("ok")]
grades = json.loads((OUT / "_grades.json").read_text())


def g(r):
    k = f"{r['task']}|{r['arm']}|{r['rep']}"
    return grades.get(k, r.get("correct"))


by = defaultdict(list)
for r in rows:
    by[(r["task"], r["arm"])].append(r)


def best3(task, arm):
    """avg cost of 3 cheapest CORRECT reps; None if <3 correct."""
    correct = [r for r in by.get((task, arm), []) if g(r)]
    if len(correct) < 3:
        return None, len(correct)
    cheapest = sorted(correct, key=lambda r: r.get("cost_usd", 0))[:3]
    return sum(r.get("cost_usd", 0) for r in cheapest) / 3, len(correct)


tasks = sorted({t for (t, a) in by if a == "atelier"})
rows_out = []
excl = []
for t in tasks:
    bc, bn = best3(t, "baseline")
    ac, an = best3(t, "atelier")
    if bc is None or ac is None:
        excl.append((t, bn, an))
        continue
    sav = (bc - ac) / bc * 100
    rows_out.append((sav, t, bc, ac))

rows_out.sort(reverse=True)
print(f"{'task':28} | base best3 | atel best3 | save | % saving")
print("-" * 70)
B = A = 0.0
for sav, t, bc, ac in rows_out:
    print(f"{t.split('__')[-1]:28} | ${bc:6.2f}   | ${ac:6.2f}   | ${bc - ac:+5.2f}| {sav:+6.1f}%")
    B += bc
    A += ac
print("-" * 70)
print(
    f"{'TOTAL (both qualify, n=' + str(len(rows_out)) + ')':28} | ${B:6.2f}   | ${A:6.2f}   | ${B - A:+5.2f}| {(B - A) / B * 100:+6.1f}%"
)
print("\nExcluded (an arm had <3 correct):")
for t, bn, an in excl:
    print(f"  {t.split('__')[-1]:26} base_correct={bn} atel_correct={an}")
