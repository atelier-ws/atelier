"""Delete all rows (both arms, all reps) for the flagged/outlier tasks so --resume re-runs them fresh."""

import json
import pathlib
import shutil
from collections import Counter

AFFECTED = {
    "django__django-13344",
    "scikit-learn__scikit-learn-25102",
    "pylint-dev__pylint-6386",
    "sphinx-doc__sphinx-8120",
    "django__django-11333",
    "django__django-14376",
    "sympy__sympy-13877",
    "sphinx-doc__sphinx-10673",
    "pylint-dev__pylint-6528",
    "sympy__sympy-14248",
    "sphinx-doc__sphinx-8551",
    "pydata__xarray-3993",
}

P = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl")
# Note: .bak_before_outlier_rerun already holds the GOOD pre-rerun snapshot; do not clobber it.
bak = P.with_suffix(".jsonl.bak_sessionlimit_partial")
if not bak.exists():
    shutil.copy(P, bak)

kept: list[str] = []
dropped: Counter = Counter()
for line in P.read_text().splitlines(keepends=True):
    if not line.strip():
        continue
    r = json.loads(line)
    if r["task"] in AFFECTED:
        dropped[r["task"].split("__")[1]] += 1
        continue
    kept.append(line)
P.write_text("".join(kept))
print("dropped per task:", dict(dropped))
print("total dropped:", sum(dropped.values()), "| remaining rows:", len(kept))
