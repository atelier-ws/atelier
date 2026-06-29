"""Reproduce the pylint regex-query timeout in lexical+zoekt mode (zoekt ON, warmed)."""

import json
import os
import time

os.environ["FITNESS_LEAN"] = "1"
os.environ["ATELIER_ZOEKT_MODE"] = "auto"
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
meta = DATA["repos"]["pylint-dev__pylint"]
Q = "regexp_csv|bad.name.rgxs|_regexp_csv_transfomer|regex.*csv"

eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
eng._schema_ready = True

# warm centrality + webserver
eng._symbol_centrality_map()
srv = get_zoekt_supervisor(eng.repo_root).server
print("webserver ready:", srv.wait_until_searchable(30.0))

# time the main zoekt call alone
for i in range(3):
    t = time.perf_counter()
    try:
        files = eng._zoekt_candidate_files(Q, max_files=10)
        n = len(files)
    except Exception as e:  # noqa: BLE001
        n = f"ERR {e!r}"
    print(f"_zoekt_candidate_files run{i}: {(time.perf_counter() - t) * 1000:.1f}ms n={n}")

# time the full explore (lexical+zoekt)
for i in range(3):
    t = time.perf_counter()
    r = eng.tool_explore(Q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
    print(f"tool_explore run{i}: {(time.perf_counter() - t) * 1000:.1f}ms files={len(r.get('files', []))}")
