"""Restore the session-limit partial state and delete ONLY failed rows (ok != True) so
--resume re-runs just the failures, keeping every succeeded run."""

import json
import pathlib
from collections import Counter

D = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z")
P = D / "results.jsonl"
PARTIAL = D / "results.jsonl.bak_sessionlimit_partial"

# Restore the full partial snapshot (48 clean + 72 affected: 13 ok, 59 failed).
lines = PARTIAL.read_text().splitlines(keepends=True)

kept: list[str] = []
dropped: Counter = Counter()
kept_ok: Counter = Counter()
for line in lines:
    if not line.strip():
        continue
    r = json.loads(line)
    if r.get("ok") is True:
        kept.append(line)
        kept_ok[r["arm"]] += 1
    else:
        dropped[r["task"].split("__")[1] + "/" + r["arm"]] += 1
P.write_text("".join(kept))
print("restored from:", PARTIAL.name)
print("kept ok rows:", dict(kept_ok), "total kept:", len(kept))
print("dropped failed rows:", sum(dropped.values()))
for k, v in sorted(dropped.items()):
    print(f"   {k}: {v}")
