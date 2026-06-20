"""Drop the crashed sphinx-8120 atelier rep2 row so --resume re-runs it."""

import json
import pathlib
import shutil

P = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl")
shutil.copy(P, P.with_suffix(".jsonl.bak_before_turncap_rerun"))
kept: list[str] = []
dropped = 0
for line in P.read_text().splitlines(keepends=True):
    if not line.strip():
        continue
    r = json.loads(line)
    if r["task"] == "sphinx-doc__sphinx-8120" and r["arm"] == "atelier" and r.get("rep") == 2:
        dropped += 1
        continue
    kept.append(line)
P.write_text("".join(kept))
print("dropped sphinx-8120 atelier rep2:", dropped, "| remaining rows:", len(kept))
