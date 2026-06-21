"""Aggregate harbor (Terminal-Bench) rep token composition from claude-run.json."""

import glob
import json
import sys

RUN = sys.argv[1]
P_IN, P_OUT, P_CW, P_CR = 5 / 1e6, 25 / 1e6, 6.25 / 1e6, 0.5 / 1e6

files = sorted(glob.glob(RUN + "/*/agent/claude-run.json"))
rows = []
for f in files:
    try:
        with open(f) as fh:
            d = json.load(fh)
    except Exception:
        continue
    u = d.get("usage") or {}
    task = f.split("/")[-3].split("__")[0]
    rows.append(
        {
            "task": task,
            "cost": d.get("total_cost_usd") or 0.0,
            "turns": d.get("num_turns") or 0,
            "in": u.get("input_tokens") or 0,
            "out": u.get("output_tokens") or 0,
            "cw": u.get("cache_creation_input_tokens") or 0,
            "cr": u.get("cache_read_input_tokens") or 0,
            "err": d.get("is_error"),
        }
    )

n = len(rows)
ci = sum(r["in"] for r in rows)
co = sum(r["out"] for r in rows)
cw = sum(r["cw"] for r in rows)
cr = sum(r["cr"] for r in rows)
c_in, c_out, c_cw, c_cr = ci * P_IN, co * P_OUT, cw * P_CW, cr * P_CR
tot = c_in + c_out + c_cw + c_cr
turns = sum(r["turns"] for r in rows)
cost_sum = sum(r["cost"] for r in rows)

print(f"harbor rep: {n} tasks with claude-run.json | total turns {turns} | reported cost ${cost_sum:.2f}")
print(f"recomputed token cost ${tot:.2f}  ({turns} turns, ${tot / max(turns, 1):.4f}/turn)")
print(f"  input       ${c_in:7.2f} ({c_in / tot * 100:4.1f}%)  {ci / 1e6:7.2f}M")
print(f"  output      ${c_out:7.2f} ({c_out / tot * 100:4.1f}%)  {co / 1e6:7.2f}M  ({co / max(turns, 1):.0f}/turn)")
print(f"  cache_write ${c_cw:7.2f} ({c_cw / tot * 100:4.1f}%)  {cw / 1e6:7.2f}M")
print(
    f"  cache_read  ${c_cr:7.2f} ({c_cr / tot * 100:4.1f}%)  {cr / 1e6:7.2f}M  ({cr / max(turns, 1) / 1000:.1f}K/turn)"
)
print(f"\navg turns/task {turns / max(n, 1):.1f} | avg cost/task ${cost_sum / max(n, 1):.2f}")
print("\n=== top 8 tasks by cost ===")
for r in sorted(rows, key=lambda r: -r["cost"])[:8]:
    print(f"  {r['task']:<34} ${r['cost']:6.2f}  {r['turns']:>3}t  cr={r['cr'] / 1e6:.1f}M")
zeros = [r for r in rows if r["cost"] == 0]
print(f"\nzero-cost rows (timeout/crash, cost not captured): {len(zeros)}")
