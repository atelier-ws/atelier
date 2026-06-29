"""Build benchmark_full.csv — per-rep and per-task-summary view of baseline vs atelier."""

import csv
import json
import statistics
from pathlib import Path

results_jsonl = Path("benchmarks/codebench/results/published/results.jsonl")
out_path = Path("benchmarks/codebench/results/published/benchmark_full.csv")

rows = [json.loads(l) for l in results_jsonl.read_text().splitlines() if l.strip()]

# Index by (task, arm, rep)
idx = {}
for r in rows:
    key = (r["task"], r["arm"], r["rep"])
    idx[key] = r

tasks = sorted(set(r["task"] for r in rows))
reps = sorted(set(r["rep"] for r in rows))

FIELDS = [
    "cost_usd",
    "duration_ms",
    "num_turns",
    "input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "output_tokens",
]

# ── per-rep rows ──────────────────────────────────────────────────────────────
per_rep_rows = []
for task in tasks:
    for rep in reps:
        b = idx.get((task, "baseline", rep))
        a = idx.get((task, "atelier", rep))
        if b is None and a is None:
            continue
        row: dict = {"task": task, "rep": rep}
        for f in FIELDS:
            bv = b[f] if b and b.get(f) is not None else None
            av = a[f] if a and a.get(f) is not None else None
            row[f"baseline_{f}"] = round(bv, 6) if bv is not None else ""
            row[f"atelier_{f}"] = round(av, 6) if av is not None else ""
            if bv and av and bv != 0:
                row[f"delta_pct_{f}"] = round((av - bv) / bv * 100, 1)
            else:
                row[f"delta_pct_{f}"] = ""
        per_rep_rows.append(row)

# ── per-task summary (medians) ────────────────────────────────────────────────
summary_rows = []
for task in tasks:
    task_b = [idx[(task, "baseline", r)] for r in reps if (task, "baseline", r) in idx]
    task_a = [idx[(task, "atelier", r)] for r in reps if (task, "atelier", r) in idx]
    row = {"task": task, "rep": "MEDIAN"}
    for f in FIELDS:
        bvals = [x[f] for x in task_b if x.get(f) is not None]
        avals = [x[f] for x in task_a if x.get(f) is not None]
        bmed = round(statistics.median(bvals), 6) if bvals else ""
        amed = round(statistics.median(avals), 6) if avals else ""
        row[f"baseline_{f}"] = bmed
        row[f"atelier_{f}"] = amed
        if bmed and amed and bmed != 0:
            row[f"delta_pct_{f}"] = round((amed - bmed) / bmed * 100, 1)
        else:
            row[f"delta_pct_{f}"] = ""
    summary_rows.append(row)

# grand total
all_b = [r for r in rows if r["arm"] == "baseline"]
all_a = [r for r in rows if r["arm"] == "atelier"]
grand: dict = {"task": "ALL_TASKS", "rep": "MEDIAN"}
for f in FIELDS:
    bvals = [x[f] for x in all_b if x.get(f) is not None]
    avals = [x[f] for x in all_a if x.get(f) is not None]
    bmed = round(statistics.median(bvals), 6) if bvals else ""
    amed = round(statistics.median(avals), 6) if avals else ""
    grand[f"baseline_{f}"] = bmed
    grand[f"atelier_{f}"] = amed
    if bmed and amed and bmed != 0:
        grand[f"delta_pct_{f}"] = round((amed - bmed) / bmed * 100, 1)
    else:
        grand[f"delta_pct_{f}"] = ""
summary_rows.append(grand)

# ── write ─────────────────────────────────────────────────────────────────────
cols = (
    ["task", "rep"]
    + [f"baseline_{f}" for f in FIELDS]
    + [f"atelier_{f}" for f in FIELDS]
    + [f"delta_pct_{f}" for f in FIELDS]
)

with open(out_path, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in per_rep_rows:
        w.writerow(r)
    fh.write("\n")  # blank line separating per-rep from summaries
    for r in summary_rows:
        w.writerow(r)

print(f"Written {len(per_rep_rows)} per-rep rows + {len(summary_rows)} summary rows")
print(f"Output: {out_path}")
