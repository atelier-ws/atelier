"""Delete incomplete/failed reps (ok != True) from a results.jsonl so a
--resume rerun re-runs them (here: at the raised timeout/max-turns caps).
Clean successes (ok=True) are kept and reused.
"""

from __future__ import annotations

import collections
import json
import pathlib

RESULTS = pathlib.Path("reports/benchmark/codebench/expensive12_run1/results.jsonl")


def main() -> None:
    kept: list[str] = []
    dropped: collections.Counter = collections.Counter()
    for ln in RESULTS.read_text().splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get("ok") is True:
            kept.append(ln)
        else:
            dropped[r.get("task")] += 1
    RESULTS.write_text("\n".join(kept) + "\n")
    print(f"kept {len(kept)} ok rows; dropped {sum(dropped.values())} not-ok reps:")
    for t, n in sorted(dropped.items()):
        print(f"  {t}: {n}")


if __name__ == "__main__":
    main()
