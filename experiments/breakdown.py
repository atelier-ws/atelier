"""Per-channel latency breakdown across a real benchmark sample, single-thread."""

import collections
import functools
import json
import os
import random
import time

os.environ["FITNESS_LEAN"] = "1"
os.environ.setdefault("ATELIER_ZOEKT_MODE", "auto")
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
repos = DATA["repos"]
pairs = DATA["pairs"]

# group queries by repo prefix
by_prefix = collections.defaultdict(list)
for q, tid, prefix in pairs:
    by_prefix[prefix].append(q)

SAMPLE_PER_REPO = int(os.environ.get("SAMPLE_PER_REPO", "12"))
rnd = random.Random(7)

TIMINGS = collections.defaultdict(float)
COUNTS = collections.defaultdict(int)

METHODS = [
    "_zoekt_candidate_files",
    "_hef_anchor_zoekt_candidates",
    "_hef_line_fts_candidates",
    "_hef_exact_symbol_candidates",
    "search_symbols",
    "_semantic_candidate_files",
    "_fused_explore_hybrid",
    "_rerank_explore_result",
    "_tool_explore_impl",
]


def wrap(eng, name):
    orig = getattr(eng, name, None)
    if orig is None:
        return

    @functools.wraps(orig)
    def timed(*a, **k):
        t = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            TIMINGS[name] += (time.perf_counter() - t) * 1000.0
            COUNTS[name] += 1

    setattr(eng, name, timed)


engines = {}
for prefix, meta in repos.items():
    try:
        eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
        eng._cache_get = lambda *a, **k: (False, None)
        eng._cache_set = lambda *a, **k: None
        engines[prefix] = eng
    except Exception as e:  # noqa: BLE001
        print("engine build failed", prefix, repr(e))

# warm ALL zoekt webservers to ready, in parallel, BEFORE timing (mirrors the
# benchmark parent prewarm). wait_until_searchable moves startup off the hot path.
from concurrent.futures import ThreadPoolExecutor as _TPE

from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor as _gzs


def _warm(prefix, eng):
    srv = _gzs(eng.repo_root).server
    t = time.perf_counter()
    ok = srv.wait_until_searchable(30.0)
    return prefix, ok, (time.perf_counter() - t)


print("warming webservers in parallel (wait_until_searchable)...")
with _TPE(max_workers=min(16, len(engines))) as _w:
    for prefix, ok, dt in _w.map(lambda kv: _warm(*kv), list(engines.items())):
        print(f"  warm {prefix:<24} ready={ok} in {dt:.1f}s")

# now wrap methods for timing and run the sample
for eng in engines.values():
    for m in METHODS:
        wrap(eng, m)

total_wall = 0.0
n = 0
per_query = []
for prefix, eng in engines.items():
    qs = by_prefix.get(prefix) or []
    rnd.shuffle(qs)
    for q in qs[:SAMPLE_PER_REPO]:
        t = time.perf_counter()
        try:
            eng.tool_explore(q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
        except Exception:  # noqa: BLE001
            pass
        dt = (time.perf_counter() - t) * 1000.0
        total_wall += dt
        per_query.append((dt, prefix, q))
        n += 1

print(
    f"\n=== {n} queries, mean wall {total_wall / max(n, 1):.1f}ms, implied q/s {1000 * n / max(total_wall, 1):.1f} ==="
)
print(f"{'channel':<32}{'total_ms':>10}{'calls':>8}{'ms/call':>10}{'ms/query':>10}")
for name in sorted(TIMINGS, key=lambda k: -TIMINGS[k]):
    tot = TIMINGS[name]
    c = COUNTS[name]
    print(f"{name:<32}{tot:>10.0f}{c:>8}{tot / max(c, 1):>10.2f}{tot / max(n, 1):>10.2f}")

per_query.sort(reverse=True)
print("\n=== slowest 12 queries ===")
for dt, prefix, q in per_query[:12]:
    print(f"  {dt:>8.0f}ms  {prefix:<20} {q[:50]!r}")
