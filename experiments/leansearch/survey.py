"""Survey ALL benchmark runs for cheap5 cost + CORRECTNESS + turns together.

The proven build was cheap but 2/5 correct -- cost alone is misleading. Find
runs that are both cheap AND correct, sorted by recency.
"""

import glob
import json
import os
from collections import defaultdict

ROOT = "/home/pankaj/Projects/leanchain/atelier/reports/benchmark/codebench"
CHEAP5 = {
    "django__django-12155",
    "django__django-11333",
    "pallets__flask-5014",
    "django__django-14376",
    "psf__requests-2931",
}


def tok(r):
    return sum(r.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))


rows = []
for jl in glob.glob(f"{ROOT}/**/results.jsonl", recursive=True):
    run = os.path.relpath(os.path.dirname(jl), ROOT)
    try:
        data = [json.loads(line) for line in open(jl) if line.strip()]
    except Exception:
        continue
    atel = [r for r in data if r["arm"] == "atelier" and r["task"] in CHEAP5 and r.get("cost_usd", 0) > 0]
    if not atel:
        continue
    tasks = {r["task"] for r in atel}
    by_task_correct = defaultdict(list)
    for r in atel:
        by_task_correct[r["task"]].append(1 if r.get("correct") else 0)
    # per-task mean correctness then average over tasks present
    corr = sum(sum(v) / len(v) for v in by_task_correct.values()) / len(by_task_correct)
    mc = sum(r["cost_usd"] for r in atel) / len(atel)
    mt = sum(r.get("num_turns", 0) for r in atel) / len(atel)
    rows.append((os.path.getmtime(jl), run, len(tasks), len(atel), mc, mt, corr))

rows.sort(reverse=True)  # recent first
print(f"{'run':30} {'tasks':>5} {'runs':>4} {'$/run':>7} {'turns':>5} {'correct':>7}")
print("-" * 66)
for _, run, nt, nr, mc, mt, corr in rows:
    star = "  <- cheap+correct" if (mc <= 0.20 and corr >= 0.8 and nt >= 4) else ""
    print(f"{run:30} {nt:5} {nr:4} {mc:7.4f} {mt:5.1f} {corr:6.0%}{star}")
print("\nbaseline cheap5: $0.1523/task, ~7 turns (frozen reference)")
