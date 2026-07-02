import json
import re
from collections import defaultdict
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
rows = [r for r in rows if r.get("ok")]
grades = json.loads((OUT / "_grades.json").read_text())


def g(r):
    k = f"{r['task']}|{r['arm']}|{r['rep']}"
    return grades[k] if k in grades else r.get("correct")


TESTRE = re.compile(r"(^|/)(test_|conftest|testing/|/tests?/)")


def patch_props(task, arm, rep):
    pp = OUT / f"{task}_{arm}_rep{rep}.patch"
    if not pp.exists():
        return None
    txt = pp.read_text(errors="replace")
    files = set(re.findall(r"^\+\+\+ b/(.+)$", txt, re.M)) or set(re.findall(r"^diff --git a/.+ b/(.+)$", txt, re.M))
    return {
        "empty": len(txt.strip()) == 0,
        "uvlock": any("uv.lock" in f for f in files),
        "testonly": bool(files) and all(TESTRE.search(f) for f in files),
        "src": [f for f in files if not TESTRE.search(f) and "uv.lock" not in f],
    }


by = defaultdict(list)
for r in rows:
    by[(r["task"], r["arm"])].append(r)

tasks = sorted({t for (t, a) in by if a == "atelier"})
stat = []
for t in tasks:
    b = by.get((t, "baseline"), [])
    a = by.get((t, "atelier"), [])
    br = sum(1 for r in b if g(r))
    ar = sum(1 for r in a if g(r))
    brate = br / len(b) if b else 0
    arate = ar / len(a) if a else 0
    bt = sum(r.get("num_turns", 0) for r in b) / len(b) if b else 0
    at = sum(r.get("num_turns", 0) for r in a) / len(a) if a else 0
    ac = sum(r.get("cost_usd", 0) for r in a) / len(a) if a else 0
    bc = sum(r.get("cost_usd", 0) for r in b) / len(b) if b else 0
    props = [patch_props(t, "atelier", r["rep"]) for r in a]
    props = [p for p in props if p]
    empty = sum(1 for p in props if p["empty"])
    uvlock = sum(1 for p in props if p["uvlock"])
    testonly = sum(1 for p in props if p["testonly"])
    stat.append((arate - brate, t, br, len(b), ar, len(a), bt, at, bc, ac, empty, uvlock, testonly))

stat.sort()
print(f"{'task':28} | base | atel | Δrate | turns b/a | $rep b/a | empty uvlk testonly")
print("-" * 104)
for d, t, br, bn, ar, an, bt, at, bc, ac, em, uv, to in stat:
    focus = "  <<FOCUS" if d < 0 else ""
    print(
        f"{t.split('__')[-1]:28} | {br}/{bn}  | {ar}/{an}  | {d:+.2f} | {bt:4.0f}/{at:4.0f} | {bc:.2f}/{ac:.2f} | {em:5} {uv:4} {to:4}{focus}"
    )
print("-" * 104)
losers = [s for s in stat if s[0] < 0]
print(f"\nFOCUS tasks (atelier < baseline): {len(losers)}")
for d, t, br, bn, ar, an, *_ in losers:
    print(f"  {t.split('__')[-1]:26} atel {ar}/{an} vs base {br}/{bn}  (gap {d:+.2f})")
