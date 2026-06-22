#!/usr/bin/env python3
"""Sample a held-out validation split disjoint from the swe30 set.

Guards against overfitting: a cost change must also improve on tasks the loop
never iterated against. Samples from an on-disk SWE-bench Verified pool (no
network), excluding verified.txt (the swe30 target).

    uv run python benchmarks/self_opt/make_holdout.py [N] [SEED]

Writes benchmarks/self_opt/tasks/holdout.txt. Freeze its baseline once before use:
run the baseline arm on holdout.txt, then
    uv run python benchmarks/self_opt/freeze_baseline.py freeze <run_dir> --out benchmarks/self_opt/baseline/holdout.json
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
POOL = REPO_ROOT / "benchmarks" / "codebench" / "data" / "opus45_verified_resolved.txt"
SWE30 = REPO_ROOT / "benchmarks" / "codebench" / "data" / "verified.txt"
OUT = Path(__file__).resolve().parent / "tasks" / "holdout.txt"


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    swe30 = {line.strip() for line in SWE30.read_text().splitlines() if line.strip()}
    pool = [
        line.strip()
        for line in POOL.read_text().splitlines()
        if line.strip() and not line.startswith("#") and line.strip() not in swe30
    ]
    if not pool:
        print(f"empty pool at {POOL}")
        return 1
    pick = sorted(random.Random(seed).sample(pool, min(n, len(pool))))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        f"# held-out validation split: {len(pick)} tasks, seed={seed}, disjoint from verified.txt\n"
        f"# pool: {POOL.name} ({len(pool)} eligible). Freeze its baseline once before use.\n" + "\n".join(pick) + "\n"
    )
    print(f"wrote {OUT} ({len(pick)} tasks, seed={seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
