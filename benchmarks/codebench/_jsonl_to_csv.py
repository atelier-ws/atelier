"""One-off: derive results.csv from results.jsonl so _signals.py can run on a dir
that only has the jsonl (e.g. phase0_verdict, where judging is incomplete).

Does NOT touch analyzer logic; only produces the input CSV the analyzer expects.
Usage: python _jsonl_to_csv.py <report_dir>
"""

import csv
import json
import sys

FD = sys.argv[1]
src = f"{FD}/results.jsonl"
dst = f"{FD}/results.csv"
with open(src) as fh:
    rows = [json.loads(line) for line in fh]
cols = [
    "task",
    "arm",
    "rep",
    "ok",
    "cost_usd",
    "duration_ms",
    "duration_api_ms",
    "num_turns",
    "input_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "thinking_tokens",
    "output_tokens",
    "models",
    "is_error",
    "timed_out",
    "result_excerpt",
    "flow_path",
    "valid",
    "validity_reason",
    "correct",
    "score",
    "judge_model",
    "judge_reason",
    "saved_usd",
    "saved_tokens",
]
with open(dst, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        rr = dict(r)
        if rr.get("score") is None:
            rr["score"] = ""
        if rr.get("correct") is None:
            rr["correct"] = ""
        w.writerow(rr)
print(f"wrote {dst} rows={len(rows)}")
