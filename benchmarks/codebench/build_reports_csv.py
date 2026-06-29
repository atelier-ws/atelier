"""Build two CSVs from all results.jsonl under reports/benchmark/codebench/.

Outputs (written next to this script):
  reports_all_runs_flat.csv   -- every (run, task, arm, rep) row with all metrics
  reports_paired_pivoted.csv  -- runs that have both arms, baseline/atelier side-by-side
"""

import csv
import json
import statistics
from pathlib import Path

BASE = Path("reports/benchmark/codebench")
OUT_FLAT = BASE / "reports_all_runs_flat.csv"
OUT_PAIRED = BASE / "reports_paired_pivoted.csv"

FLAT_FIELDS = [
    "run",
    "task",
    "arm",
    "rep",
    "ok",
    "is_error",
    "timed_out",
    "correct",
    "score",
    "cost_usd",
    "duration_ms",
    "duration_api_ms",
    "num_turns",
    "input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "output_tokens",
    "thinking_tokens",
]

METRICS = [
    "cost_usd",
    "duration_ms",
    "duration_api_ms",
    "num_turns",
    "input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "output_tokens",
]

# ── collect all rows ──────────────────────────────────────────────────────────
all_rows: list[dict] = []
for jsonl_path in sorted(BASE.rglob("results.jsonl")):
    run_name = jsonl_path.parent.name
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        r["run"] = run_name
        all_rows.append(r)

print(f"Loaded {len(all_rows)} rows from {len(set(r['run'] for r in all_rows))} runs")

# ── flat CSV ──────────────────────────────────────────────────────────────────
with open(OUT_FLAT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=FLAT_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in all_rows:
        w.writerow(r)
print(f"Flat CSV: {OUT_FLAT}  ({len(all_rows)} rows)")

# ── paired-pivoted CSV (runs with both arms) ──────────────────────────────────
# group by run; keep only those with both arms present
from collections import defaultdict

by_run: dict[str, list[dict]] = defaultdict(list)
for r in all_rows:
    by_run[r["run"]].append(r)

paired_runs = {run: rows for run, rows in by_run.items() if {r["arm"] for r in rows} >= {"baseline", "atelier"}}
print(f"Paired runs (both arms): {sorted(paired_runs)}")

PAIRED_FIELDS = (
    ["run", "task", "rep"]
    + [f"baseline_{m}" for m in METRICS]
    + ["baseline_correct", "baseline_score", "baseline_ok", "baseline_is_error"]
    + [f"atelier_{m}" for m in METRICS]
    + ["atelier_correct", "atelier_score", "atelier_ok", "atelier_is_error"]
    + [f"delta_pct_{m}" for m in METRICS]
    + ["correctness_delta"]
)

paired_rows: list[dict] = []
summary_rows: list[dict] = []

for run, rows in sorted(paired_runs.items()):
    # index by (task, arm, rep)
    idx: dict[tuple, dict] = {}
    for r in rows:
        idx[(r["task"], r["arm"], r["rep"])] = r

    tasks = sorted({r["task"] for r in rows})
    reps = sorted({r["rep"] for r in rows})

    run_per_rep: list[dict] = []
    for task in tasks:
        for rep in reps:
            b = idx.get((task, "baseline", rep))
            a = idx.get((task, "atelier", rep))
            if b is None or a is None:
                continue
            row: dict = {"run": run, "task": task, "rep": rep}
            for m in METRICS:
                bv = b.get(m)
                av = a.get(m)
                row[f"baseline_{m}"] = round(bv, 6) if bv is not None else ""
                row[f"atelier_{m}"] = round(av, 6) if av is not None else ""
                if bv and av and bv != 0:
                    row[f"delta_pct_{m}"] = round((av - bv) / bv * 100, 1)
                else:
                    row[f"delta_pct_{m}"] = ""
            for arm_name, src in (("baseline", b), ("atelier", a)):
                row[f"{arm_name}_correct"] = src.get("correct", "")
                row[f"{arm_name}_score"] = src.get("score", "")
                row[f"{arm_name}_ok"] = src.get("ok", "")
                row[f"{arm_name}_is_error"] = src.get("is_error", "")
            # correctness delta: atelier_score - baseline_score (when both graded)
            bs = b.get("score")
            as_ = a.get("score")
            row["correctness_delta"] = round(as_ - bs, 3) if (bs is not None and as_ is not None) else ""
            paired_rows.append(row)
            run_per_rep.append(row)

    if not run_per_rep:
        continue

    # per-run summary (medians across all task*rep pairs)
    summary: dict = {"run": run, "task": "ALL", "rep": "MEDIAN"}
    for m in METRICS:
        bvals = [r[f"baseline_{m}"] for r in run_per_rep if r[f"baseline_{m}"] != ""]
        avals = [r[f"atelier_{m}"] for r in run_per_rep if r[f"atelier_{m}"] != ""]
        bmed = round(statistics.median(bvals), 6) if bvals else ""
        amed = round(statistics.median(avals), 6) if avals else ""
        summary[f"baseline_{m}"] = bmed
        summary[f"atelier_{m}"] = amed
        if bmed and amed and bmed != 0:
            summary[f"delta_pct_{m}"] = round((amed - bmed) / bmed * 100, 1)
        else:
            summary[f"delta_pct_{m}"] = ""
    # correctness: fraction correct
    bc = [r["baseline_correct"] for r in run_per_rep if r["baseline_correct"] != ""]
    ac = [r["atelier_correct"] for r in run_per_rep if r["atelier_correct"] != ""]
    summary["baseline_correct"] = f"{sum(1 for x in bc if x)}/{len(bc)}" if bc else ""
    summary["atelier_correct"] = f"{sum(1 for x in ac if x)}/{len(ac)}" if ac else ""
    bscores = [float(r["baseline_score"]) for r in run_per_rep if r["baseline_score"] not in ("", None)]
    ascores = [float(r["atelier_score"]) for r in run_per_rep if r["atelier_score"] not in ("", None)]
    summary["baseline_score"] = round(statistics.mean(bscores), 3) if bscores else ""
    summary["atelier_score"] = round(statistics.mean(ascores), 3) if ascores else ""
    summary["baseline_ok"] = ""
    summary["baseline_is_error"] = ""
    summary["atelier_ok"] = ""
    summary["atelier_is_error"] = ""
    cd = [r["correctness_delta"] for r in run_per_rep if r["correctness_delta"] != ""]
    summary["correctness_delta"] = round(statistics.mean(cd), 3) if cd else ""
    summary_rows.append(summary)

with open(OUT_PAIRED, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=PAIRED_FIELDS, extrasaction="ignore")
    w.writeheader()
    current_run = None
    for row in paired_rows:
        if row["run"] != current_run:
            if current_run is not None:
                # write summary for previous run
                prev = next(s for s in summary_rows if s["run"] == current_run)
                w.writerow(prev)
                fh.write("\n")
            current_run = row["run"]
        w.writerow(row)
    # last run summary
    if current_run:
        prev = next(s for s in summary_rows if s["run"] == current_run)
        w.writerow(prev)

print(f"Paired CSV: {OUT_PAIRED}  ({len(paired_rows)} rows + {len(summary_rows)} summaries)")
