"""Merge expand run results into published/results.jsonl and copy run dirs."""

import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2]

dirs = [
    "20260630T061714Z",
    "20260630T075525Z",
    "20260630T075717Z",
    "20260630T075924Z",
    "20260630T083157Z",
]

rows: dict = {}
for d in dirs:
    p = ROOT / "reports" / "benchmark" / "codebench" / d / "results.jsonl"
    if not p.exists():
        continue
    with open(p) as f:
        for line in f:
            r = json.loads(line)
            key = (r["task"], r["arm"])
            if key not in rows:
                rows[key] = r

out = ROOT / "benchmarks" / "codebench" / "results" / "published" / "results.jsonl"
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w") as f:
    for r in rows.values():
        f.write(json.dumps(r) + "\n")
print(f"Wrote {len(rows)} rows to {out}")

pub = ROOT / "reports" / "public" / "benchmark" / "codebench"
pub.mkdir(parents=True, exist_ok=True)
for label, d in [("cg_expand_t1", "20260630T075525Z"), ("cg_expand_t2", "20260630T075924Z"), ("cg_linux", "20260630T083157Z")]:
    src = ROOT / "reports" / "benchmark" / "codebench" / d
    dst = pub / label
    if src.exists() and not dst.exists():
        shutil.copytree(src, dst)
        print(f"Copied {d} -> {label}")
    else:
        print(f"Skip {label} (already exists or src missing)")
