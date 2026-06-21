"""Decompose where atelier's cost goes vs baseline -> find the 50%-saving levers."""

import json
import pathlib
import statistics
from collections import defaultdict

P = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl")
P_IN, P_OUT, P_CW, P_CR = 5 / 1e6, 25 / 1e6, 6.25 / 1e6, 0.5 / 1e6

rows = [json.loads(x) for x in P.read_text().splitlines() if x.strip()]
by_arm = defaultdict(list)
for r in rows:
    by_arm[r["arm"]].append(r)


def g(r, k):
    return r.get(k) or 0


print("=== 1. TOKEN COMPOSITION per arm (summed over 60 runs) ===")
for arm in ("baseline", "atelier"):
    rs = by_arm[arm]
    ci = sum(g(r, "input_tokens") for r in rs)
    co = sum(g(r, "output_tokens") for r in rs)
    cw = sum(g(r, "cache_creation_tokens") for r in rs)
    cr = sum(g(r, "cache_read_tokens") for r in rs)
    c_in, c_out, c_cw, c_cr = ci * P_IN, co * P_OUT, cw * P_CW, cr * P_CR
    tot = c_in + c_out + c_cw + c_cr
    turns = sum(g(r, "num_turns") for r in rs)
    print(f"\n  {arm}:  ${tot:.2f}   turns={turns}   ${tot / turns:.4f}/turn")
    print(f"    input       ${c_in:6.2f} ({c_in / tot * 100:4.1f}%)  {ci / 1e6:7.2f}M tok")
    print(f"    output      ${c_out:6.2f} ({c_out / tot * 100:4.1f}%)  {co / 1e6:7.2f}M tok")
    print(f"    cache_write ${c_cw:6.2f} ({c_cw / tot * 100:4.1f}%)  {cw / 1e6:7.2f}M tok")
    print(f"    cache_read  ${c_cr:6.2f} ({c_cr / tot * 100:4.1f}%)  {cr / 1e6:7.2f}M tok")

print("\n=== 2. PER-TURN economics ===")
for arm in ("baseline", "atelier"):
    rs = by_arm[arm]
    tot = sum(
        g(r, "input_tokens") * P_IN
        + g(r, "output_tokens") * P_OUT
        + g(r, "cache_creation_tokens") * P_CW
        + g(r, "cache_read_tokens") * P_CR
        for r in rs
    )
    turns = sum(g(r, "num_turns") for r in rs)
    cr = sum(g(r, "cache_read_tokens") for r in rs)
    co = sum(g(r, "output_tokens") for r in rs)
    print(
        f"  {arm}: {turns} turns | ${tot / turns:.4f}/turn | {cr / turns / 1000:.1f}K cache_read/turn | {co / turns:.0f} out_tok/turn"
    )

print("\n=== 3. COST CONCENTRATION: top 8 atelier runs ===")
ai = sorted(by_arm["atelier"], key=lambda r: -g(r, "cost_usd"))
totA = sum(g(r, "cost_usd") for r in by_arm["atelier"])
acc = 0.0
for r in ai[:8]:
    c = g(r, "cost_usd")
    acc += c
    print(
        f"  {r['task'].split('__')[1]:<22} rep{r.get('rep')}  ${c:6.3f}  {g(r, 'num_turns'):>3}t  correct={r.get('correct')}"
    )
print(f"  -> top 8 runs = ${acc:.2f} of ${totA:.2f} ({acc / totA * 100:.0f}% of atelier spend)")

print("\n=== 4. WHERE ATELIER SPENDS MORE THAN BASELINE (per-task median delta) ===")


def med_cost(arm, task):
    v = [g(r, "cost_usd") for r in by_arm[arm] if r["task"] == task]
    return statistics.median(v) if v else 0


tasks = sorted({r["task"] for r in rows})
over = [(t, med_cost("atelier", t) - med_cost("baseline", t)) for t in tasks]
for t, d in sorted(over, key=lambda x: -x[1]):
    if d > 0:
        print(f"  {t.split('__')[1]:<22} +${d:.3f}/rep  (atl over baseline)")
print(f"  TOTAL atelier-OVER on losing tasks: +${sum(d for _, d in over if d > 0) * 3:.2f} (x3 reps)")
print(f"  TOTAL atelier-UNDER on winning tasks: -${-sum(d for _, d in over if d < 0) * 3:.2f} (x3 reps)")
