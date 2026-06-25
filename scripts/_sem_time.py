"""Scratch: prove engine semantic per-query latency on the already-embedded django copy.
First query pays the one-time matrix load+cache; the rest are warm matmuls."""

import os

os.environ.setdefault("ATELIER_CODE_EMBEDDER", "bge")
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine  # noqa: E402

data = json.load(open("/tmp/bench_pairs_multi.json"))
ws = data["repos"]["django__django"]["ws"]
qs = [q for q, _, p in data["pairs"] if p == "django__django"][:16]

eng = CodeContextEngine(Path(ws), db_path=Path("/tmp/fused_django__django.db"), autosync_enabled=False)
print("available:", eng._semantic_ranker.available, "dim:", eng._semantic_ranker.embedder.dim, flush=True)
for i, q in enumerate(qs):
    te = time.perf_counter()
    _ = eng._semantic_ranker.embed_query(q)
    embed_ms = (time.perf_counter() - te) * 1000
    t0 = time.perf_counter()
    res = eng.search_symbols(q, limit=10, mode="semantic", auto_index=False)
    dt = (time.perf_counter() - t0) * 1000
    tag = "COLD" if i == 0 else "warm"
    print(f"[{i:2d}] total={dt:7.1f}ms  embed={embed_ms:6.1f}ms  rank+hydrate={dt - embed_ms:6.1f}ms  {tag}  hits={len(res)}", flush=True)
