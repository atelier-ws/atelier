"""Build 10-task ground truth: gold true file + concept query per django task.
Keeps only tasks whose gold non-test file exists in the shared checkout."""

import json
import re
from pathlib import Path

from benchmarks.codebench import swebench_data

DJ = Path(open("/tmp/djroot.txt").read().strip())
TESTRE = re.compile(r"(^|/)(test_|tests?/|conftest)")

CANDIDATES = [
    "django__django-11138",
    "django__django-11333",
    "django__django-12155",
    "django__django-12708",
    "django__django-13128",
    "django__django-13344",
    "django__django-13449",
    "django__django-14376",
    "django__django-15128",
    "django__django-15268",
    "django__django-15503",
    "django__django-15957",
    "django__django-16560",
    "django__django-14007",
    "django__django-14631",
]

insts = swebench_data.load_instances(dataset=None, instances=CANDIDATES)
by_id = {i.instance_id: i for i in insts}
out = []
for tid in CANDIDATES:
    i = by_id.get(tid)
    if not i:
        continue
    patch = getattr(i, "patch", "") or ""
    files = [f for f in re.findall(r"^\+\+\+ b/(.+)$", patch, re.M) if not TESTRE.search(f)]
    files = [f for f in files if (DJ / f).exists()]  # must exist in shared checkout
    if not files:
        continue
    stmt = re.sub(r"\s+", " ", (getattr(i, "problem_statement", "") or "")).strip()
    first = stmt.split(".")[0]
    title = (first if len(first) >= 25 else stmt[:90])[:90]  # concept query
    out.append({"task": tid, "true_files": files, "query": title})
    if len(out) >= 10:
        break

Path("/tmp/tasks10.json").write_text(json.dumps(out, indent=2))
print(f"selected {len(out)} tasks:")
for t in out:
    print(f"  {t['task'][:24]:24} true={t['true_files']}  q={t['query'][:60]!r}")
