"""Seed a fresh dir for the final 45-task x 5-rep atelier-vs-baseline comparison,
then --resume fills only the gaps.

Reuse:
  baseline  <- swe50_final_v2        (45 tasks, good grade, 208 rows+patches)
  atelier   <- swe50_clean_3rep_2tok (8 tasks x 3 reps, fixed build, 24 rows+patches)

After seeding, a --resume run with arms=[atelier,baseline] reps=5 over all 45
tasks reuses everything present and runs only the missing jobs:
  baseline: top up the 5 under-rep'd tasks to 5 reps (~15 runs)
  atelier:  8 tasks rep4-5 (reuse 3 + 2 fresh, incl. django-13344) + 37 tasks x5
"""

import json
import shutil
from pathlib import Path

ROOT = Path("/home/pankaj/Projects/leanchain/atelier/reports/benchmark/codebench")
BASE_DIR = ROOT / "swe50_final_v2"
ATEL_DIR = ROOT / "swe50_clean_3rep_2tok"
TGT = ROOT / "swe50_final_5rep"
TGT.mkdir(exist_ok=True)


def rows(d: Path, arm: str) -> list[dict]:
    out = []
    for line in (d / "results.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("arm") == arm:
            out.append(r)
    return out


base = rows(BASE_DIR, "baseline")
atel = rows(ATEL_DIR, "atelier")

nb = na = 0
for p in BASE_DIR.glob("*_baseline_rep*.patch"):
    shutil.copy(p, TGT / p.name)
    nb += 1
for p in ATEL_DIR.glob("*_atelier_rep*.patch"):
    shutil.copy(p, TGT / p.name)
    na += 1

with (TGT / "results.jsonl").open("w") as f:
    for r in base + atel:
        f.write(json.dumps(r) + "\n")

ids = sorted({r["task"] for r in base})
(TGT / "instance_ids.txt").write_text(" ".join(ids) + "\n")

# sanity: every reused row must have a patch present (else resume re-runs it)
missing = 0
for r in base + atel:
    pp = TGT / f"{r['task']}_{r['arm']}_rep{r['rep']}.patch"
    if not pp.exists():
        missing += 1
print(f"seeded -> {TGT.name}")
print(f"  baseline rows={len(base)} patches_copied={nb}")
print(f"  atelier  rows={len(atel)} patches_copied={na}")
print(f"  tasks={len(ids)}  rows_without_patch={missing}")
