"""Profile a COLD first lexical query (zoekt OFF) to find the multi-second hang."""

import cProfile
import io
import os
import pstats
import sys
import time

os.environ["FITNESS_LEAN"] = "1"
os.environ["ATELIER_ZOEKT_MODE"] = "off"
import json
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
repos = DATA["repos"]

TARGET = sys.argv[1] if len(sys.argv) > 1 else "atelier__atelier"
Q = sys.argv[2] if len(sys.argv) > 2 else "background process tracking pid session bash execution"
meta = repos[TARGET]

eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
eng._schema_ready = True

# COLD: profile the very first call, no warm-up.
pr = cProfile.Profile()
t = time.perf_counter()
pr.enable()
r = eng.tool_explore(Q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
pr.disable()
dt = (time.perf_counter() - t) * 1000
print(f"COLD first call: {dt:.1f}ms  files={len(r.get('files', []))}  repo={TARGET}  q={Q!r}")

s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(28)
print(s.getvalue())

# second call (warm) for contrast
t = time.perf_counter()
eng.tool_explore(Q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
print(f"WARM second call: {(time.perf_counter() - t) * 1000:.1f}ms")
