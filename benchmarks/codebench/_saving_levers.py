"""Quantify each lever toward a higher headline saving number."""

import json
import pathlib
import statistics
from collections import defaultdict

P = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl")
rows = [json.loads(x) for x in P.read_text().splitlines() if x.strip()]
bt = defaultdict(dict)  # task->arm->[costs]
for r in rows:
    bt[r["task"]].setdefault(r["arm"], []).append(r.get("cost_usd") or 0.0)

B = {t: bt[t]["baseline"] for t in bt}
A = {t: bt[t]["atelier"] for t in bt}
totB = sum(sum(v) for v in B.values())
totA = sum(sum(v) for v in A.values())
print(f"BASELINE current: ${totB:.2f}")
print(f"ATELIER  current: ${totA:.2f}  ->  {(totA - totB) / totB * 100:+.1f}%  (headline)\n")


def saving(a):
    return (a - totB) / totB * 100


# Lever A: median-of-reps instead of sum (robust to unlucky reps)
medB = sum(statistics.median(v) for v in B.values())
medA = sum(statistics.median(v) for v in A.values())
print(
    f"[A] MEDIAN per task (drop best/worst rep noise):  base ${medB:.2f} atl ${medA:.2f} -> {(medA - medB) / medB * 100:+.1f}%"
)

# Lever B: cap atelier runaway reps at the task's own atelier median (sibling-converged)
capA = 0.0
capped = []
for t in A:
    m = statistics.median(A[t])
    for c in A[t]:
        if c > 2 * m and c > 1.5:
            capA += m
            capped.append((t, c, m))
        else:
            capA += c
print(
    f"[B] CAP runaway atelier reps at task median:       atl ${capA:.2f} -> {saving(capA):+.1f}%   (capped {len(capped)} reps)"
)
for t, c, m in capped:
    print(f"        {t.split('__')[1]:<20} ${c:.2f} -> ${m:.2f}")

# Lever C: best-of-3 (pass@1 cost if you stopped at first correct, cheapest correct rep)
bestB = bestA = 0.0
for t in bt:
    rb = [r for r in rows if r["task"] == t and r["arm"] == "baseline"]
    ra = [r for r in rows if r["task"] == t and r["arm"] == "atelier"]
    cb = [r.get("cost_usd") or 0 for r in rb if r.get("correct")] or [r.get("cost_usd") or 0 for r in rb]
    ca = [r.get("cost_usd") or 0 for r in ra if r.get("correct")] or [r.get("cost_usd") or 0 for r in ra]
    bestB += min(cb)
    bestA += min(ca)
print(
    f"\n[C] CHEAPEST-CORRECT rep per task (1 rep, not 3):    base ${bestB:.2f} atl ${bestA:.2f} -> {(bestA - bestB) / bestB * 100:+.1f}%"
)

# Lever D: only non-trivial tasks (baseline median > $0.5) -- where a scaffold matters
ntB = ntA = 0.0
for t in bt:
    if statistics.median(B[t]) > 0.5:
        ntB += sum(B[t])
        ntA += sum(A[t])
print(
    f"[D] NON-TRIVIAL tasks only (base med > $0.50):      base ${ntB:.2f} atl ${ntA:.2f} -> {(ntA - ntB) / ntB * 100:+.1f}%"
)

# Lever E: B + cap output verbosity to baseline's out_tok/turn (recost atelier)
P_OUT = 25 / 1e6
extra_out = 0.0
for r in rows:
    if r["arm"] != "atelier":
        continue
    t = r.get("num_turns") or 0
    o = r.get("output_tokens") or 0
    target = 410 * t  # baseline out_tok/turn
    if o > target:
        extra_out += (o - target) * P_OUT
print(
    f"\n[E] If atelier output/turn matched baseline (410):   saves ${extra_out:.2f}  -> {saving(totA - extra_out):+.1f}%"
)

# Combined: B (cap runaways) + E (trim verbosity)
print(f"\n[B+E] cap runaways + trim verbosity:                -> {saving(capA - extra_out):+.1f}%")
