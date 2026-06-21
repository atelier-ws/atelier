"""Per-RUN cost breakdown: every rep of every task, both arms, side by side."""

import json
import pathlib
from collections import defaultdict

P = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl")

# task -> arm -> rep -> row
data: dict = defaultdict(lambda: defaultdict(dict))
for line in P.read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    data[r["task"]][r["arm"]][r.get("rep")] = r


def cell(row):
    if not row:
        return "      -      "
    c = row.get("cost_usd") or 0.0
    t = row.get("num_turns") or 0
    ok = "✓" if row.get("correct") is True else ("✗" if row.get("correct") is False else "?")
    return f"{c:6.3f}/{t:>3}t/{ok}"


hdr = (
    f"{'task':<22}"
    + "".join(f"{'B r' + str(i):>13}" for i in (1, 2, 3))
    + "".join(f"{'A r' + str(i):>13}" for i in (1, 2, 3))
)
print(hdr)
print("(cost / turns / correct✓✗)")
print("-" * len(hdr))
totB = totA = 0.0
for task in sorted(data):
    b = data[task].get("baseline", {})
    a = data[task].get("atelier", {})
    line = f"{task.split('__')[1]:<22}"
    for i in (1, 2, 3):
        line += f"{cell(b.get(i)):>13}"
    for i in (1, 2, 3):
        line += f"{cell(a.get(i)):>13}"
    print(line)
    totB += sum((b.get(i, {}) or {}).get("cost_usd") or 0.0 for i in (1, 2, 3))
    totA += sum((a.get(i, {}) or {}).get("cost_usd") or 0.0 for i in (1, 2, 3))
print("-" * len(hdr))
print(f"baseline total cost (60 runs): ${totB:.2f}    atelier total cost (60 runs): ${totA:.2f}")
print(f"atelier vs baseline: {(totA - totB) / totB * 100:+.1f}%  (sum of all reps)")
