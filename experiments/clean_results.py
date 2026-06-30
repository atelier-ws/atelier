"""Remove ok=False (errored / $0 crash) rows from a run's results.jsonl and
delete their stale artifacts so --resume re-runs them cleanly.

Usage: uv run --project benchmarks python experiments/clean_results.py <run_dir>
"""

import json
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path


def main(run_dir: str) -> None:
    d = Path(run_dir)
    src = d / "results.jsonl"
    rows = [json.loads(line) for line in src.read_text().splitlines() if line.strip()]

    keep, drop = [], []
    for r in rows:
        (drop if not r.get("ok") else keep).append(r)

    # Survey before mutating.
    print(f"total rows: {len(rows)}  keep(ok=True): {len(keep)}  remove(ok=False): {len(drop)}")
    none_by_arm = defaultdict(int)
    for r in keep:
        if r.get("correct") is None:
            none_by_arm[r["arm"]] += 1
    print(f"ungraded (correct=None) among kept rows: {dict(none_by_arm)}")
    by_arm = defaultdict(int)
    for r in drop:
        by_arm[r["arm"]] += 1
    print(f"removing by arm: {dict(by_arm)}")

    # Backup, then rewrite results.jsonl with only ok=True rows.
    bak = d / f"results.jsonl.bak.{int(time.time())}"
    shutil.copy2(src, bak)
    src.write_text("".join(json.dumps(r) + "\n" for r in keep))
    print(f"backed up -> {bak.name}; rewrote results.jsonl with {len(keep)} rows")

    # Delete stale artifacts for the dropped (task,arm,rep) so resume sees a gap.
    removed = 0
    for r in drop:
        stem = f"{r['task']}_{r['arm']}_rep{r['rep']}"
        for suf in (".patch", ".flow", ".flow_dump.txt", ".prompt.txt"):
            p = d / f"{stem}{suf}"
            if p.exists():
                p.unlink()
                removed += 1
    print(f"deleted {removed} stale artifact file(s) for {len(drop)} dropped rep(s)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
