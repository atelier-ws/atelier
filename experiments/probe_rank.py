"""Compare gold-file rank in _zoekt_candidate_files top-10: current vs worktree.
Run the SAME file from both trees (paths are absolute)."""

import json
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

ROOT = "/home/pankaj/Projects/leanchain/atelier"
d = json.load(open(f"{ROOT}/benchmarks/codebench/data/bench_pairs_multi.json"))
repos, pairs, true_map = d["repos"], d["pairs"], d["true_map"]
PFX = [x for x in repos if "astropy" in x][0]
WS = Path(repos[PFX]["ws"])
DB = Path(repos[PFX]["db"]) if repos[PFX].get("db") else None

eng = CodeContextEngine(WS, db_path=DB, autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
eng._schema_ready = True

sup = get_zoekt_supervisor(WS)
sup.server.wait_until_searchable(30.0)


def norm(p):
    return (p or "").replace("\\", "/")


astro = [(q, tid) for (q, tid, pfx) in pairs if pfx == PFX]
seen = set()
rr_sum = 0.0
n = 0
misses = []
for q, tid in astro:
    if q in seen:
        continue
    seen.add(q)
    golds = {norm(g) for g in true_map.get(tid, [])}
    if not golds:
        continue
    files = [norm(f) for f in eng._zoekt_candidate_files(q, max_files=10)]
    rank = next((i + 1 for i, f in enumerate(files) if f in golds), 0)
    rr = 1.0 / rank if rank else 0.0
    rr_sum += rr
    n += 1
    if rank == 0 and len(misses) < 10:
        misses.append((q, list(golds)[:1], files[:3]))
print(f"astropy zoekt-channel MRR over {n} unique queries = {rr_sum / n:.4f}")
print("sample misses (gold not in top-10):")
for q, g, top3 in misses:
    print(f"  Q={q[:42]!r:44} gold={g}  top3={top3}")
