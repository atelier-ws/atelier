"""Run ONE explore of the pathological query under ablation, for py-spy profiling."""

import os

os.environ["ABLATE_A"] = "1"
os.environ["ABLATE_B"] = "1"
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

d = json.load(open("/tmp/bench_pairs_multi.json"))
meta = d["repos"]["django__django"]
eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
eng._symbol_centrality_map()
Q = "decimal|DecimalField|CAST|NUMERIC|output_field"
print("running query #121 under ablation...", flush=True)
t = time.perf_counter()
r = eng.tool_explore(Q, max_files=10, auto_index=False)
print(f"done in {(time.perf_counter() - t) * 1000:.0f}ms files={len(r.get('files', []))}", flush=True)
