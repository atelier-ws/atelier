import json
from pathlib import Path

OUT = Path("reports/benchmark/codebench/swe50_stress_run1")
rf = OUT / "results.jsonl"
rows = [json.loads(x) for x in rf.read_text().splitlines() if x.strip()]

ok = [r for r in rows if r.get("ok")]
bad = [r for r in rows if not r.get("ok")]

# backup once (don't clobber an existing backup)
bak = OUT / "results.jsonl.pre_failclean.bak"
if not bak.exists():
    bak.write_text(rf.read_text())
    print(f"backed up -> {bak.name}")
else:
    print(f"backup already exists: {bak.name} (left as-is)")

# rewrite results.jsonl with only ok=True rows
rf.write_text("".join(json.dumps(r) + "\n" for r in ok))
print(f"kept {len(ok)} ok rows; dropped {len(bad)} failed rows")

# remove patch/flow artifacts for dropped slots so --resume re-runs them
removed = 0
kept_slots = {(r["task"], r["arm"], r["rep"]) for r in ok}
for r in bad:
    slot = (r["task"], r["arm"], r["rep"])
    if slot in kept_slots:
        continue  # a good row exists for this slot; never delete its artifacts
    for ext in (".patch", ".flow"):
        f = OUT / f"{r['task']}_{r['arm']}_rep{r['rep']}{ext}"
        if f.exists():
            f.unlink()
            removed += 1
print(f"removed {removed} stale patch/flow artifacts")
print(f"results.jsonl now: {sum(1 for _ in rf.read_text().splitlines())} rows")
