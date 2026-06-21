"""Per-task behavioral picture from harbor artifacts (no tool transcript exists,
so derive convergence signal from turns + cost + pass/fail + timeout)."""

import glob
import json
import os
import statistics
import sys

RUN = sys.argv[1]
rows = []
for task_dir in sorted(glob.glob(RUN + "/*/")):
    name = os.path.basename(task_dir.rstrip("/")).split("__")[0]
    cr = os.path.join(task_dir, "agent", "claude-run.json")
    reward_f = os.path.join(task_dir, "verifier", "reward.txt")
    d = {}
    if os.path.exists(cr):
        try:
            with open(cr) as fh:
                d = json.load(fh)
        except Exception:
            d = {}
    reward = None
    if os.path.exists(reward_f):
        try:
            with open(reward_f) as fh:
                reward = float(fh.read().strip())
        except Exception:
            reward = None
    rows.append(
        {
            "task": name,
            "pass": (reward == 1.0) if reward is not None else None,
            "reward": reward,
            "turns": d.get("num_turns") or 0,
            "cost": d.get("total_cost_usd") or 0.0,
            "dur_s": (d.get("duration_ms") or 0) / 1000,
            "err": d.get("is_error"),
            "stop": d.get("stop_reason") or d.get("terminal_reason"),
        }
    )

p = [r for r in rows if r["pass"] is True]
f = [r for r in rows if r["pass"] is False]
print(f"tasks: {len(rows)} | pass {len(p)} | fail {len(f)} | pass-rate {len(p) / max(len(rows), 1) * 100:.0f}%\n")

print("=== FAILED despite high effort (no convergence) — fail, sorted by turns ===")
for r in sorted(f, key=lambda r: -r["turns"])[:12]:
    print(f"  {r['task']:<34} {r['turns']:>3}t  ${r['cost']:6.2f}  {r['dur_s']:6.0f}s  stop={r['stop']}")

print("\n=== PASSED but expensive (inefficient convergence) — pass, sorted by turns ===")
for r in sorted(p, key=lambda r: -r["turns"])[:12]:
    print(f"  {r['task']:<34} {r['turns']:>3}t  ${r['cost']:6.2f}  {r['dur_s']:6.0f}s")

print("\n=== efficient passes (low turns) for contrast ===")
for r in sorted(p, key=lambda r: r["turns"])[:6]:
    print(f"  {r['task']:<34} {r['turns']:>3}t  ${r['cost']:6.2f}")

if p and f:
    print(
        f"\nmedian turns: pass {statistics.median(r['turns'] for r in p):.0f} | fail {statistics.median(r['turns'] for r in f):.0f}"
    )
    print(
        f"median cost:  pass ${statistics.median(r['cost'] for r in p):.2f} | fail ${statistics.median(r['cost'] for r in f):.2f}"
    )
