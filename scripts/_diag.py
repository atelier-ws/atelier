import json
import re
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
grades = json.loads((OUT / "_grades.json").read_text())


def g(r):
    k = f"{r['task']}|{r['arm']}|{r['rep']}"
    return grades[k] if k in grades else r.get("correct")


TASKS = [
    "pytest-dev__pytest-5787",
    "pytest-dev__pytest-5840",
    "pytest-dev__pytest-6197",
    "pytest-dev__pytest-7490",
    "pytest-dev__pytest-8399",
    "pylint-dev__pylint-8898",
    "scikit-learn__scikit-learn-12682",
]

TESTRE = re.compile(r"(^|/)(test_|conftest|testing/|/tests?/)")


def classify(patch_text):
    files = set(re.findall(r"^\+\+\+ b/(.+)$", patch_text, re.M))
    if not files:
        files = set(re.findall(r"^diff --git a/.+ b/(.+)$", patch_text, re.M))
    src = [f for f in files if not TESTRE.search(f)]
    test = [f for f in files if TESTRE.search(f)]
    return src, test


for t in TASKS:
    print(f"\n=== {t} ===")
    for arm in ("baseline", "atelier"):
        for r in sorted(
            [x for x in rows if x["task"] == t and x["arm"] == arm and x.get("ok")], key=lambda x: x["rep"]
        ):
            pp = OUT / f"{t}_{arm}_rep{r['rep']}.patch"
            if not pp.exists():
                continue
            txt = pp.read_text(errors="replace")
            src, test = classify(txt)
            nlines = txt.count("\n")
            srcstr = ",".join(s.split("/")[-1] for s in src[:3]) or "NONE"
            print(
                f"  {arm:8} rep{r['rep']} resolved={g(r)!s:5} bytes={len(txt):5} src_files=[{srcstr}] test_files={len(test)}"
            )
