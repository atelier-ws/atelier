"""Does the benchmark's centrality pre-warm actually stick? Mimic its exact stubs."""

import json
import os
import time

os.environ["FITNESS_LEAN"] = "1"
os.environ["ATELIER_ZOEKT_MODE"] = "off"
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
meta = DATA["repos"]["atelier__atelier"]

eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
eng._schema_ready = True  # benchmark sets this -> _init_schema becomes a no-op

for i in range(4):
    t = time.perf_counter()
    m = eng._symbol_centrality_map()
    print(
        f"centrality call {i}: {(time.perf_counter() - t) * 1000:.1f}ms  size={len(m)}  cache={getattr(eng, '_centrality_name_map', None) is not None}"
    )

# Now does a tool_explore reuse it?
for i in range(3):
    t = time.perf_counter()
    eng.tool_explore(
        "background process tracking pid session bash execution",
        max_files=10,
        auto_index=False,
        include_source=False,
        include_relationships=False,
    )
    print(f"explore {i}: {(time.perf_counter() - t) * 1000:.1f}ms")
