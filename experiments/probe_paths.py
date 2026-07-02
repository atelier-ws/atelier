"""Per-repo: is zoekt using the webserver (fast) or CLI subprocess (slow) path?"""

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

# Count which path each zoekt call takes, globally.
PATHS = collections.Counter()
_orig_ws = S.ZoektServer._run_webserver_search
_orig_cli = S.ZoektServer._run_host_search


def ws(self, url, payload):
    PATHS["webserver"] += 1
    return _orig_ws(self, url, payload)


def cli(self, payload):
    PATHS["cli"] += 1
    return _orig_cli(self, payload)


S.ZoektServer._run_webserver_search = ws
S.ZoektServer._run_host_search = cli

engines = {}
for prefix, meta in repos.items():
    try:
        eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
        eng._cache_get = lambda *a, **k: (False, None)
        eng._cache_set = lambda *a, **k: None
        engines[prefix] = eng
    except Exception as e:  # noqa: BLE001
        print("engine build failed", prefix, repr(e))

# warm each repo once to trigger webserver spawn
for prefix, eng in engines.items():
    qs = by_prefix.get(prefix) or []
    if qs:
        try:
            eng.tool_explore(qs[0], max_files=10, auto_index=False, include_source=False, include_relationships=False)
        except Exception:  # noqa: BLE001
            pass
print("warming 18s...")
time.sleep(18)

print(f"\n{'repo':<24}{'ws_failed':>10}{'index?':>8}{'zoekt_ms(3x avg)':>18}")
for prefix, eng in engines.items():
    srv = get_zoekt_supervisor(eng.repo_root).server
    failed = getattr(srv, "_webserver_failed", "?")
    has_index = srv.index_root.exists() and any(srv.index_root.glob("*.zoekt"))
    qs = by_prefix.get(prefix) or []
    samples = []
    for q in qs[1:4]:
        t = time.perf_counter()
        try:
            eng._zoekt_candidate_files(q, max_files=10)
        except Exception:  # noqa: BLE001
            pass
        samples.append((time.perf_counter() - t) * 1000)
    avg = sum(samples) / max(len(samples), 1)
    print(f"{prefix:<24}{failed!s:>10}{has_index!s:>8}{avg:>18.1f}")

print("\nPATH COUNTS:", dict(PATHS))
