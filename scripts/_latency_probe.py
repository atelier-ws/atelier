"""Scratch: per-query latency (mean / p50 / p95 / max) of _search_symbols_local
over the full explore-benchmark query set, per repo + overall, with the slowest
queries surfaced. Confirms the <100ms goal and exposes any tail outliers."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

data = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
pairs, repos = data["pairs"], data["repos"]

uniq = {}
for q, _tid, prefix in pairs:
    uniq.setdefault(prefix, [])
    if q not in uniq[prefix]:
        uniq[prefix].append(q)


def pct(vals, p):
    s = sorted(vals)
    return s[min(len(s) - 1, round((p / 100.0) * (len(s) - 1)))]


all_lat = []
slowest = []  # (ms, repo, query)
print(f"{'repo':28s} {'n':>4} {'mean':>7} {'p50':>7} {'p95':>7} {'max':>7}")
for prefix, meta in repos.items():
    qs = uniq.get(prefix)
    if not qs:
        continue
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    eng._search_symbols_local("warmup", limit=20)  # prime caches (centrality, fts count)
    lat = []
    for q in qs:
        t0 = time.perf_counter()
        eng._search_symbols_local(q, limit=20)
        ms = (time.perf_counter() - t0) * 1000.0
        lat.append(ms)
        all_lat.append(ms)
        slowest.append((ms, prefix, q))
    print(
        f"{prefix:28s} {len(lat):>4} {sum(lat) / len(lat):>7.1f} "
        f"{pct(lat, 50):>7.1f} {pct(lat, 95):>7.1f} {max(lat):>7.1f}"
    )

print(
    f"\n{'OVERALL':28s} {len(all_lat):>4} {sum(all_lat) / len(all_lat):>7.1f} "
    f"{pct(all_lat, 50):>7.1f} {pct(all_lat, 95):>7.1f} {max(all_lat):>7.1f}"
)
over = [x for x in all_lat if x > 100.0]
print(f"queries >100ms: {len(over)}/{len(all_lat)} ({100.0 * len(over) / len(all_lat):.1f}%)")
print("\nslowest 8 queries:")
for ms, prefix, q in sorted(slowest, reverse=True)[:8]:
    print(f"  {ms:7.1f}ms  {prefix:24s} {q[:60]!r}")
