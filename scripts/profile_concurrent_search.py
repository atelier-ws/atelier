"""Concurrent load profile: simulate the benchmark's nested-pool architecture.

Measures latency when N outer workers each run queries while also maintaining
their own inner ProcessPoolExecutor(max_workers=5) for FTS channels.
Compares vs ThreadPool inner channel executor under the same concurrent load.

Usage:  uv run python scripts/profile_concurrent_search.py
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import statistics
import sys
import time

sys.path.insert(0, "src")

with open("benchmarks/codebench/data/bench_pairs_multi.json") as f:
    _data = json.load(f)
pairs = _data["pairs"]
repos = _data["repos"]

TARGET_REPOS = ["django__django", "astropy__astropy", "pydata__xarray"]
N_QUERIES = 40  # per repo

_WORKERS = int(os.environ.get("FITNESS_WORKERS", "0")) or max(1, min(8, (os.cpu_count() or 4) // 4))
print(f"cpu_count={os.cpu_count()}  outer_workers={_WORKERS}  inner_pool_workers=5", flush=True)
print(f"total processes under ProcessPool: {_WORKERS} + {_WORKERS * 5} = {_WORKERS + _WORKERS * 5}", flush=True)
print(f"total processes under ThreadPool:  {_WORKERS} (threads are free)\n", flush=True)


# ── Worker entry-points (must be module-level to be picklable) ────────────────


def _init_process_pool() -> None:
    """Outer worker init: replace inherited executor with fresh ProcessPool."""
    import concurrent.futures as _cf

    import atelier.core.capabilities.code_context.engine as _eng_mod

    _eng_mod._SEARCH_CHANNEL_EXECUTOR.shutdown(wait=False)
    _eng_mod._SEARCH_CHANNEL_EXECUTOR = _cf.ProcessPoolExecutor(max_workers=5)  # type: ignore[assignment]


def _init_thread_pool() -> None:
    """Outer worker init: replace inherited executor with ThreadPool."""
    import concurrent.futures as _cf

    import atelier.core.capabilities.code_context.engine as _eng_mod

    _eng_mod._SEARCH_CHANNEL_EXECUTOR.shutdown(wait=False)
    _eng_mod._SEARCH_CHANNEL_EXECUTOR = _cf.ThreadPoolExecutor(  # type: ignore[assignment]
        max_workers=5, thread_name_prefix="fts-ch"
    )


def _run_one_task(task: tuple[str, str, str]) -> float:
    """Run one (prefix, query, ws_path) and return latency ms."""
    import sys
    import time

    sys.path.insert(0, "src")
    from pathlib import Path

    from atelier.core.capabilities.code_context.engine import CodeContextEngine, _default_db_path

    _prefix, q, ws_str = task
    ws = Path(ws_str)
    db = _default_db_path(ws)
    eng = CodeContextEngine(repo_root=ws, db_path=db)
    t0 = time.perf_counter()
    eng._search_symbols_local(q, limit=20)
    return (time.perf_counter() - t0) * 1000


# ── Build task list ───────────────────────────────────────────────────────────
tasks: list[tuple[str, str, str]] = []
for prefix in TARGET_REPOS:
    info = repos[prefix]
    ws_str = info["ws"]
    seen: set[str] = set()
    for q, _tid, p in pairs:
        if p != prefix:
            continue
        if q not in seen:
            seen.add(q)
            tasks.append((prefix, q, ws_str))
        if sum(1 for t in tasks if t[0] == prefix) >= N_QUERIES:
            break

print(f"Tasks: {len(tasks)} total\n", flush=True)


def _pct(vals: list[float], p: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, int(p / 100.0 * (len(s) - 1)))]


def _stats(lats: list[float], label: str) -> None:
    n = len(lats)
    qps = n / (sum(lats) / 1000.0) if lats else 0
    print(
        f"  {label:<35s} n={n:3d}  mean={statistics.mean(lats):6.1f}ms "
        f" p50={statistics.median(lats):6.1f}ms "
        f" p95={_pct(lats, 95):6.1f}ms "
        f" max={max(lats):6.1f}ms  "
        f"({qps:.1f} q/s sequential-equiv)",
        flush=True,
    )


# ── Run A: Concurrent with ProcessPool inner (current) ─────────────────────
print(f"=== A: Concurrent ProcessPool inner ({_WORKERS} outer x 5 inner) ===", flush=True)
wall_t0 = time.perf_counter()
with concurrent.futures.ProcessPoolExecutor(
    max_workers=_WORKERS,
    initializer=_init_process_pool,
) as pool:
    pp_lats = list(pool.map(_run_one_task, tasks))
wall_pp = time.perf_counter() - wall_t0
print(f"  Wall time: {wall_pp:.2f}s  throughput: {len(pp_lats) / wall_pp:.1f} q/s", flush=True)
_stats(pp_lats, "ProcessPool inner (current)")

# ── Run B: Concurrent with ThreadPool inner ────────────────────────────
print(f"\n=== B: Concurrent ThreadPool inner ({_WORKERS} outer processes, 5 threads each) ===", flush=True)
wall_t0 = time.perf_counter()
with concurrent.futures.ProcessPoolExecutor(
    max_workers=_WORKERS,
    initializer=_init_thread_pool,
) as pool:
    tp_lats = list(pool.map(_run_one_task, tasks))
wall_tp = time.perf_counter() - wall_t0
print(f"  Wall time: {wall_tp:.2f}s  throughput: {len(tp_lats) / wall_tp:.1f} q/s", flush=True)
_stats(tp_lats, "ThreadPool inner")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("SUMMARY (concurrent load, simulates real benchmark conditions)")
print("=" * 65)
print("  Wall-clock throughput:")
print(f"    ProcessPool inner: {len(pp_lats) / wall_pp:.1f} q/s")
print(f"    ThreadPool inner:  {len(tp_lats) / wall_tp:.1f} q/s")
print(f"    Speedup: {len(tp_lats) / wall_tp / (len(pp_lats) / wall_pp):.2f}x" if wall_pp > 0 else "")
print()
_stats(pp_lats, "A  ProcessPool (current)")
_stats(tp_lats, "B  ThreadPool")
