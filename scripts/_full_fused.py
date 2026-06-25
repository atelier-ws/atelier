"""Scratch: full fused-3 (lexical+zoekt+semantic) explore-MRR across all 5 repos,
with index-time BGE embedding (batched). Also reports engine semantic-only (ANN).
Embeds into per-repo DB copies so the shared benchmark DBs are not mutated."""

import os

os.environ.setdefault("ATELIER_CODE_EMBEDDER", "bge")
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine  # noqa: E402

data = json.load(open("/tmp/bench_pairs_multi.json"))
pairs, true_map, repos = data["pairs"], data["true_map"], data["repos"]
REPOS = ["django__django", "astropy__astropy", "pydata__xarray", "pytest-dev__pytest", "scikit-learn__scikit-learn"]


def norm(x):
    return (x or "").replace("\\", "/")


def dedup(items):
    out, seen = [], set()
    for f in items:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out[:10]


def rank(files, trues):
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in trues):
            return i
    return None


agg = {"sem_rr": 0.0, "f_rr": 0.0, "f_h1": 0, "n": 0}
by_repo = {}
for prefix in REPOS:
    m = repos[prefix]
    dbc = "/tmp/fused_" + prefix.replace("/", "_") + ".db"
    if not Path(dbc).exists():  # reuse an already-embedded copy across runs
        for ext in ("", "-wal", "-shm"):
            p = Path(m["db"] + ext)
            if p.exists():
                shutil.copy(p, dbc + ext)
    eng = CodeContextEngine(Path(m["ws"]), db_path=Path(dbc), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    t0 = time.perf_counter()
    with eng._connect() as conn:
        eng._init_schema(conn)
        eng._build_symbol_embeddings(conn, eng._current_index_version())
    embed_s = time.perf_counter() - t0
    rs = {"sem_rr": 0.0, "f_rr": 0.0, "f_h1": 0, "n": 0}
    for q, tid, p in pairs:
        if p != prefix:
            continue
        trues = [norm(t) for t in (true_map.get(tid) or [])]
        if not trues:
            continue
        sem_files = dedup(s.file_path for s in eng.search_symbols(q, limit=10, mode="semantic", auto_index=False))
        exp = eng.tool_explore(q, max_files=10, auto_index=False)
        fused_files = dedup(f.get("path", "") for f in exp.get("files", []))
        sr, fr = rank(sem_files, trues), rank(fused_files, trues)
        rs["n"] += 1
        if sr:
            rs["sem_rr"] += 1.0 / sr
        if fr:
            rs["f_rr"] += 1.0 / fr
            rs["f_h1"] += int(fr == 1)
    for k in rs:
        agg[k] = agg.get(k, 0) + rs[k]
    by_repo[prefix] = {
        "semantic": round(rs["sem_rr"] / max(rs["n"], 1), 4),
        "fused": round(rs["f_rr"] / max(rs["n"], 1), 4),
        "n": rs["n"],
    }
    print(
        f"[{prefix}] embed={embed_s:.0f}s sem={by_repo[prefix]['semantic']} fused={by_repo[prefix]['fused']} n={rs['n']}",
        flush=True,
    )

out = {
    "semantic_mrr": round(agg["sem_rr"] / max(agg["n"], 1), 4),
    "fused_mrr": round(agg["f_rr"] / max(agg["n"], 1), 4),
    "fused_hit1": round(agg["f_h1"] / max(agg["n"], 1), 4),
    "n": agg["n"],
    "by_repo": by_repo,
}
print(json.dumps(out))
