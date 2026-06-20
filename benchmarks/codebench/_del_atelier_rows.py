"""Delete atelier rows for the costlier-than-baseline instances from swe20's
results.jsonl so a --resume rerun re-runs them (here: under the bare persona).
Baseline rows are left intact and reused on resume.
"""

from __future__ import annotations

import json
import pathlib

RESULTS = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl")
# Higher-cost tasks to rerun (atelier arm only) with the index pre-build fix.
TARGETS = {
    "django__django-11138",
    "django__django-12155",
    "django__django-13344",
    "django__django-14376",
    "pylint-dev__pylint-6528",
    "scikit-learn__scikit-learn-12682",
    "scikit-learn__scikit-learn-25102",
    "sphinx-doc__sphinx-8120",
    "sphinx-doc__sphinx-8551",
    "sphinx-doc__sphinx-10673",
    "sympy__sympy-13091",
    "sympy__sympy-14248",
    # also: atelier cost > baseline (marginal), per request
    "pydata__xarray-3095",
    "pydata__xarray-3993",
}


def main() -> None:
    kept: list[str] = []
    dropped = 0
    for ln in RESULTS.read_text().splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        iid = r.get("instance_id") or r.get("task")
        if r.get("arm") == "atelier" and iid in TARGETS:
            dropped += 1
            continue
        kept.append(ln)
    RESULTS.write_text("\n".join(kept) + "\n")
    print(f"dropped {dropped} atelier rows; kept {len(kept)} rows")


if __name__ == "__main__":
    main()
