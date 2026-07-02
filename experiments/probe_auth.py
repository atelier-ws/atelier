"""Authoritative per-repo zoekt webserver state + timing."""

import collections
import json
import os
import time

os.environ["FITNESS_LEAN"] = "1"
os.environ.setdefault("ATELIER_ZOEKT_MODE", "auto")
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt import server as S
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
repos = DATA["repos"]
pairs = DATA["pairs"]
by_prefix = collections.defaultdict(list)
for q, _tid, prefix in pairs:
    by_prefix[prefix].append(q)

PATHS = collections.Counter()
_orig_ws = S.ZoektServer._run_webserver_search
_orig_cli = S.ZoektServer._run_host_search
S.ZoektServer._run_webserver_search = lambda self, url, payload: (PATHS.update(["ws"]), _orig_ws(self, url, payload))[1]
S.ZoektServer._run_host_search = lambda self, payload: (PATHS.update(["cli"]), _orig_cli(self, payload))[1]

print(f"{'repo':<22}{'idx_root_exists':>16}{'shards':>8}{'state':>7}{'ens_started':>26}")
engines = {}
for prefix, meta in repos.items():
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    engines[prefix] = eng
    srv = get_zoekt_supervisor(eng.repo_root).server
    ir = srv.index_root
    shards = len(list(ir.glob("*.zoekt"))) if ir.exists() else 0
    state_ok = srv.state_path.exists()
    try:
        srv.ensure_started()
        es = "OK"
    except Exception as e:  # noqa: BLE001
        es = type(e).__name__ + ": " + str(e)[:40]
    print(f"{prefix:<22}{ir.exists()!s:>16}{shards:>8}{state_ok!s:>7}  {es}")

print("\n--- warming webservers 20s, then 3 timed zoekt calls/repo ---")
for prefix, eng in engines.items():
    qs = by_prefix.get(prefix) or []
    if qs:
        with __import__("contextlib").suppress(Exception):
            eng._zoekt_candidate_files(qs[0], max_files=10)
time.sleep(20)
PATHS.clear()
rows = []
for prefix, eng in engines.items():
    qs = by_prefix.get(prefix) or []
    ts = []
    for q in qs[1:4]:
        t = time.perf_counter()
        with __import__("contextlib").suppress(Exception):
            eng._zoekt_candidate_files(q, max_files=10)
        ts.append((time.perf_counter() - t) * 1000)
    srv = get_zoekt_supervisor(eng.repo_root).server
    rows.append((prefix, getattr(srv, "_webserver_failed", "?"), sum(ts) / max(len(ts), 1)))
print(f"{'repo':<22}{'ws_failed':>11}{'avg_ms':>10}")
for prefix, failed, avg in rows:
    print(f"{prefix:<22}{failed!s:>11}{avg:>10.1f}")
print("\nPATH COUNTS (post-warm):", dict(PATHS))
