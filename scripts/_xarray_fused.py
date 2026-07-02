"""Scratch: verify the index-time-embed refactor on xarray.
Embeds symbols via the index-time pass, then measures engine semantic-only (ANN)
vs the exact ceiling, plus the fused-3 (lexical+zoekt+semantic) explore MRR."""

import os

os.environ.setdefault("ATELIER_CODE_EMBEDDER", "bge")
os.environ.setdefault("ATELIER_ANN_CANDIDATE_CAP", "20000")
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

data = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
m = data["repos"]["pydata__xarray"]
pairs, true_map = data["pairs"], data["true_map"]
src = m["db"]
dbc = "/tmp/xarray_sem_test.db"
for ext in ("", "-wal", "-shm"):
    p = Path(src + ext)
    if p.exists():
        shutil.copy(p, dbc + ext)
eng = CodeContextEngine(Path(m["ws"]), db_path=Path(dbc), autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
print("semantic_ranker.available:", eng._semantic_ranker.available, "embedder:", eng._semantic_ranker.embedder.name)

t0 = time.perf_counter()
with eng._connect() as conn:
    eng._init_schema(conn)
    iv = eng._current_index_version()
    eng._build_symbol_embeddings(conn, iv)
print(f"[index-time embed] {time.perf_counter() - t0:.1f}s", flush=True)


def norm(x):
    return (x or "").replace("\\", "/")


def score(rankfn, label):
    rr = h1 = n = 0
    t = time.perf_counter()
    for q, tid, p in pairs:
        if p != "pydata__xarray":
            continue
        trues = [norm(x) for x in (true_map.get(tid) or [])]
        if not trues:
            continue
        files = rankfn(q)
        n += 1
        for i, f in enumerate(files, 1):
            if any(norm(f).endswith(tt) for tt in trues):
                rr += 1 / i
                h1 += int(i == 1)
                break
    print(
        f"  {label:34s} mrr={rr / max(n, 1):.4f} hit1={h1 / max(n, 1):.4f} n={n} ({time.perf_counter() - t:.0f}s)",
        flush=True,
    )


def _dedup_files(items):
    out, seen = [], set()
    for f in items:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out[:10]


def sem_files(q):
    return _dedup_files(s.file_path for s in eng.search_symbols(q, limit=10, mode="semantic", auto_index=False))


def explore_files(q):
    r = eng.tool_explore(q, max_files=10, auto_index=False)
    return _dedup_files(f.get("path", "") for f in r.get("files", []))


score(sem_files, "semantic-only (engine ANN)")
score(explore_files, "FUSED (lexical+zoekt+semantic)")
