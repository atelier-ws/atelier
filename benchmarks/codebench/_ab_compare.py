"""Compare edit-verify ON (A/B) vs OFF (main run) for the 3 probed tasks."""

import json
import pathlib
import statistics
from collections import defaultdict

MAIN = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl")
AB = pathlib.Path("reports/benchmark/codebench/_ab_editverify/results.jsonl")
TASKS = {"sympy__sympy-14248", "pylint-dev__pylint-6528", "django__django-11138"}


def load(p):
    d = defaultdict(list)
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["task"] in TASKS and r["arm"] == "atelier":
            d[r["task"]].append(r)
    return d


off = load(MAIN)
on = load(AB)


def med(rs, k):
    v = [r.get(k) or 0 for r in rs]
    return statistics.median(v) if v else 0


def corr(rs):
    return sum(1 for r in rs if r.get("correct") is True)


print(f"{'task':<22}{'verify':>7}{'$/med':>8}{'turns':>7}{'correct':>9}   per-rep cost/turns")
print("-" * 86)
for t in sorted(TASKS):
    for label, d in (("OFF", off), ("ON", on)):
        rs = sorted(d[t], key=lambda r: r.get("rep") or 0)
        detail = "  ".join(f"{r.get('cost_usd') or 0:.2f}/{r.get('num_turns') or 0}t" for r in rs)
        print(
            f"{t.split('__')[1]:<22}{label:>7}{med(rs, 'cost_usd'):>8.3f}{med(rs, 'num_turns'):>7.0f}{corr(rs)}/{len(rs):<7}   {detail}"
        )
    print()

print("=== aggregate over the 3 tasks (sum of per-rep medians) ===")
for label, d in (("OFF", off), ("ON", on)):
    c = sum(med(d[t], "cost_usd") for t in TASKS)
    tn = sum(med(d[t], "num_turns") for t in TASKS)
    cc = sum(corr(d[t]) for t in TASKS)
    print(f"  verify {label}: ${c:.2f} median-cost-sum | {tn:.0f} median-turns-sum | {cc}/9 correct")
