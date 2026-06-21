"""Per-rep cost table (baseline vs atelier) with sum and % delta for phase0_verdict."""

import json
from pathlib import Path

RESULTS = Path("reports/benchmark/codebench/phase0_verdict/results.jsonl")

TASKS = [
    "django__django-13344",
    "scikit-learn__scikit-learn-25102",
    "sympy__sympy-13091",
    "django__django-14376",
    "sympy__sympy-13877",
    "django__django-11138",
    "pydata__xarray-3305",
]

# cost[task][arm][rep] = cost_usd
cost: dict[str, dict[str, dict[int, float]]] = {t: {"baseline": {}, "atelier": {}} for t in TASKS}

with RESULTS.open() as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        task = row.get("task")
        arm = row.get("arm")
        rep = row.get("rep")
        c = row.get("cost_usd")
        if task in cost and arm in ("baseline", "atelier") and rep in (1, 2, 3) and c is not None:
            cost[task][arm][int(rep)] = float(c)


def fmt_pct(base_sum: float, atel_sum: float) -> str:
    if base_sum == 0:
        return "n/a"
    pct = (atel_sum - base_sum) / base_sum * 100.0
    r = round(pct)
    if r < 0:
        return f"-{abs(r)}% cheaper"
    if r > 0:
        return f"+{r}% costlier"
    return "0% (even)"


def reps(d: dict[int, float]) -> tuple[float, float, float, float]:
    r1, r2, r3 = d.get(1, 0.0), d.get(2, 0.0), d.get(3, 0.0)
    return r1, r2, r3, r1 + r2 + r3


print("| task | base r1 | base r2 | base r3 | base sum | atel r1 | atel r2 | atel r3 | atel sum | % |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

tot_b = [0.0, 0.0, 0.0]
tot_a = [0.0, 0.0, 0.0]

for t in TASKS:
    br1, br2, br3, bsum = reps(cost[t]["baseline"])
    ar1, ar2, ar3, asum = reps(cost[t]["atelier"])
    for i, v in enumerate((br1, br2, br3)):
        tot_b[i] += v
    for i, v in enumerate((ar1, ar2, ar3)):
        tot_a[i] += v
    print(
        f"| {t} | {br1:.2f} | {br2:.2f} | {br3:.2f} | {bsum:.2f} "
        f"| {ar1:.2f} | {ar2:.2f} | {ar3:.2f} | {asum:.2f} | {fmt_pct(bsum, asum)} |"
    )

bsum_all = sum(tot_b)
asum_all = sum(tot_a)
print(
    f"| **TOTAL** | {tot_b[0]:.2f} | {tot_b[1]:.2f} | {tot_b[2]:.2f} | {bsum_all:.2f} "
    f"| {tot_a[0]:.2f} | {tot_a[1]:.2f} | {tot_a[2]:.2f} | {asum_all:.2f} "
    f"| {fmt_pct(bsum_all, asum_all)} |"
)
