"""Where does 50%+ saving structurally live? Stratify by task cost + measure turn batching."""

import json
import pathlib
import statistics
from collections import defaultdict

P = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl")
rows = [json.loads(x) for x in P.read_text().splitlines() if x.strip()]
bt = defaultdict(lambda: defaultdict(list))
for r in rows:
    bt[r["task"]][r["arm"]].append(r)


def med(rs, k="cost_usd"):
    v = [r.get(k) or 0 for r in rs]
    return statistics.median(v) if v else 0


print("=== SAVING stratified by baseline task cost ===")
for lo, hi, label in [(0, 0.5, "trivial <$0.5"), (0.5, 1.5, "medium $0.5-1.5"), (1.5, 99, "heavy >$1.5")]:
    tb = ta = 0.0
    n = 0
    for t in bt:
        mb = med(bt[t]["baseline"])
        if lo <= mb < hi:
            tb += mb
            ta += med(bt[t]["atelier"])
            n += 1
    if tb:
        print(f"  {label:<18} {n:>2} tasks  base ${tb:5.2f} atl ${ta:5.2f}  -> {(ta - tb) / tb * 100:+.1f}%")

print("\n=== TURN BATCHING: tool_calls per turn (higher = fewer turns for same work) ===")
for arm in ("baseline", "atelier"):
    tc = sum(r.get("tool_calls") or 0 for r in rows if r["arm"] == arm)
    tn = sum(r.get("num_turns") or 0 for r in rows if r["arm"] == arm)
    print(f"  {arm}: {tc} tool_calls / {tn} turns = {tc / tn:.2f} calls/turn")

print("\n=== keys available on a row (find tool_calls / thinking fields) ===")
print(sorted(rows[0].keys()))

print("\n=== HEAVY tasks (>$1.5) per-task saving detail ===")
for t in sorted(bt, key=lambda t: -med(bt[t]["baseline"])):
    mb = med(bt[t]["baseline"])
    if mb < 1.5:
        continue
    ma = med(bt[t]["atelier"])
    bt_turns = med(bt[t]["baseline"], "num_turns")
    at_turns = med(bt[t]["atelier"], "num_turns")
    print(
        f"  {t.split('__')[1]:<22} base ${mb:5.2f}/{bt_turns:.0f}t  atl ${ma:5.2f}/{at_turns:.0f}t  -> {(ma - mb) / mb * 100:+.0f}%"
    )
