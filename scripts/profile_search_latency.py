"""Profile search latency: measure where time is spent in _search_symbols_local.

Runs real queries against real indices. Breaks down:
  - ProcessPoolExecutor overhead vs actual SQL time
  - ThreadPoolExecutor comparison on same queries/same DB
  - Per-channel SQL timing
  - IPC serialization (pickle round-trip) cost

Usage:  uv run python scripts/profile_search_latency.py
"""

from __future__ import annotations

import concurrent.futures
import json
import pickle
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

import atelier.core.capabilities.code_context.engine as _eng_mod
from atelier.core.capabilities.code_context.engine import (
    _SEARCH_CHANNEL_EXECUTOR,
    CodeContextEngine,
    _default_db_path,
    _run_search_channel,
)

# ── Load pairs + engines ─────────────────────────────────────────────────────
with open("benchmarks/codebench/data/bench_pairs_multi.json") as f:
    _data = json.load(f)
pairs = _data["pairs"]
repos = _data["repos"]

TARGET_REPOS = ["django__django", "astropy__astropy", "pydata__xarray"]
N_QUERIES = 30


def get_engine(prefix: str) -> CodeContextEngine:
    info = repos[prefix]
    ws = Path(info["ws"])
    db = _default_db_path(ws)
    return CodeContextEngine(repo_root=ws, db_path=db)


engines = {p: get_engine(p) for p in TARGET_REPOS}
print(f"Loaded {len(engines)} engines", flush=True)

sample_tasks: list[tuple[str, str]] = []
for prefix in TARGET_REPOS:
    seen: set[str] = set()
    for q, _tid, p in pairs:
        if p != prefix:
            continue
        if q not in seen:
            seen.add(q)
            sample_tasks.append((prefix, q))
        if sum(1 for t in sample_tasks if t[0] == prefix) >= N_QUERIES:
            break

print(f"Sampled {len(sample_tasks)} queries across {len(TARGET_REPOS)} repos\n", flush=True)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _pct(vals: list[float], p: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, int(p / 100.0 * (len(s) - 1)))]


def _stats(lats: list[float], label: str) -> None:
    print(
        f"  {label:<30s} n={len(lats):3d}  mean={statistics.mean(lats):6.1f}ms  "
        f"p50={statistics.median(lats):6.1f}ms  "
        f"p95={_pct(lats, 95):6.1f}ms  "
        f"max={max(lats):6.1f}ms",
        flush=True,
    )


def _run_seq(db_path: Path, sql: str, params: tuple) -> list[dict]:
    """Direct SQLite call — no pool, no IPC."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


class _SyncExecutor:
    """Drop-in replacement that runs submit() synchronously (measures pure SQL, no parallelism)."""

    def submit(self, fn, *args):  # type: ignore[override]
        f: concurrent.futures.Future[object] = concurrent.futures.Future()
        try:
            f.set_result(fn(*args))
        except Exception as exc:  # noqa: BLE001
            f.set_exception(exc)
        return f


# ── A: WARMUP ────────────────────────────────────────────────────────────────
print("=== WARMUP (first 15 queries, discarded) ===", flush=True)
for prefix, q in sample_tasks[:15]:
    engines[prefix]._search_symbols_local(q, limit=20)
time.sleep(0.3)

# ── B: ProcessPool baseline ──────────────────────────────────────────────────
print("\n=== A: ProcessPool (current) — _search_symbols_local ===", flush=True)
pp_lats: list[float] = []
for prefix, q in sample_tasks:
    t0 = time.perf_counter()
    engines[prefix]._search_symbols_local(q, limit=20)
    pp_lats.append((time.perf_counter() - t0) * 1000)
_stats(pp_lats, "ProcessPool")

# ── C: ProcessPool submit round-trip overhead ────────────────────────────────
print("\n=== B: ProcessPool submit overhead (identity fn) ===", flush=True)


def _identity(x: int) -> int:
    return x


submit_lats: list[float] = []
for _ in range(40):
    t0 = time.perf_counter()
    f = _SEARCH_CHANNEL_EXECUTOR.submit(_identity, 42)
    f.result(timeout=5)
    submit_lats.append((time.perf_counter() - t0) * 1000)
_stats(submit_lats, "ProcessPool identity round-trip")

# ── D: Pickle cost estimate ──────────────────────────────────────────────────
print("\n=== C: IPC pickle overhead ===", flush=True)
# Capture one real set of channel args
captured_channels: list[tuple] = []
_orig_submit = _SEARCH_CHANNEL_EXECUTOR.submit


def _capture(fn, db, sql, params):  # type: ignore[misc]
    captured_channels.append((db, sql, params))
    return _orig_submit(fn, db, sql, params)


_SEARCH_CHANNEL_EXECUTOR.submit = _capture  # type: ignore[method-assign]
engines[TARGET_REPOS[0]]._search_symbols_local(sample_tasks[0][1], limit=20)
_SEARCH_CHANNEL_EXECUTOR.submit = _orig_submit  # type: ignore[method-assign]

print(f"  Channels per query: {len(captured_channels)}", flush=True)
if captured_channels:
    arg_pickle_ms: list[float] = []
    for db, sql, params in captured_channels:
        t0 = time.perf_counter()
        raw = pickle.dumps((db, sql, params))
        pickle.loads(raw)
        arg_pickle_ms.append((time.perf_counter() - t0) * 1000)
    mean_arg = statistics.mean(arg_pickle_ms)
    print(f"  Args pickle round-trip:   mean={mean_arg:.3f}ms per channel", flush=True)

    db, sql, params = captured_channels[0]
    rows = _run_seq(db, sql, params)
    t0 = time.perf_counter()
    raw2 = pickle.dumps(rows)
    pickle.loads(raw2)
    res_pickle_ms = (time.perf_counter() - t0) * 1000
    print(f"  Result pickle round-trip: {res_pickle_ms:.3f}ms ({len(rows)} rows)", flush=True)
    n_ch = len(captured_channels)
    total_ipc = (mean_arg + res_pickle_ms) * n_ch
    print(f"  Estimated IPC total/query ({n_ch} ch): ~{total_ipc:.2f}ms", flush=True)

# ── E: ThreadPoolExecutor ────────────────────────────────────────────────────
print("\n=== D: ThreadPool (same SQL, thread workers) ===", flush=True)
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=5, thread_name_prefix="profile-fts")
_eng_mod._SEARCH_CHANNEL_EXECUTOR = _thread_pool  # type: ignore[assignment]
_eng_mod._run_search_channel = _run_seq  # type: ignore[assignment]

tp_lats: list[float] = []
for prefix, q in sample_tasks:
    t0 = time.perf_counter()
    engines[prefix]._search_symbols_local(q, limit=20)
    tp_lats.append((time.perf_counter() - t0) * 1000)

_eng_mod._SEARCH_CHANNEL_EXECUTOR = _SEARCH_CHANNEL_EXECUTOR  # type: ignore[assignment]
_eng_mod._run_search_channel = _run_search_channel  # type: ignore[assignment]
_thread_pool.shutdown(wait=False)
_stats(tp_lats, "ThreadPool")

# ── F: Sequential (no parallelism) ──────────────────────────────────────────
print("\n=== E: Sequential (no executor, pure SQL sum) ===", flush=True)
_eng_mod._SEARCH_CHANNEL_EXECUTOR = _SyncExecutor()  # type: ignore[assignment]
_eng_mod._run_search_channel = _run_seq  # type: ignore[assignment]

seq_lats: list[float] = []
for prefix, q in sample_tasks:
    t0 = time.perf_counter()
    engines[prefix]._search_symbols_local(q, limit=20)
    seq_lats.append((time.perf_counter() - t0) * 1000)

_eng_mod._SEARCH_CHANNEL_EXECUTOR = _SEARCH_CHANNEL_EXECUTOR  # type: ignore[assignment]
_eng_mod._run_search_channel = _run_search_channel  # type: ignore[assignment]
_stats(seq_lats, "Sequential")

# ── G: Per-channel SQL breakdown ─────────────────────────────────────────────
print("\n=== F: Per-channel SQL timing (15 queries on django) ===", flush=True)
channel_rows: list[dict] = []


class _TimingExecutor:
    def submit(self, fn, db, sql, params):  # type: ignore[misc]
        t0 = time.perf_counter()
        result = _run_seq(db, sql, params)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        ch_type = (
            "fts_and"
            if "symbol_fts" in sql and "OR" not in sql[:120]
            else "fts_or"
            if "symbol_fts" in sql
            else "trigram_sym"
            if "symbol_trigram" in sql and "file_path" not in sql[:80]
            else "trigram_path"
            if "symbol_trigram" in sql
            else "direct_sym"
            if "FROM symbols" in sql and "file_path" not in sql[-80:]
            else "direct_path"
        )
        channel_rows.append({"ch": ch_type, "n_rows": len(result), "ms": elapsed_ms})
        f: concurrent.futures.Future[object] = concurrent.futures.Future()
        f.set_result(result)
        return f


_eng_mod._SEARCH_CHANNEL_EXECUTOR = _TimingExecutor()  # type: ignore[assignment]
_eng_mod._run_search_channel = _run_seq  # type: ignore[assignment]

for prefix, q in [t for t in sample_tasks if t[0] == "django__django"][:15]:
    engines[prefix]._search_symbols_local(q, limit=20)

_eng_mod._SEARCH_CHANNEL_EXECUTOR = _SEARCH_CHANNEL_EXECUTOR  # type: ignore[assignment]
_eng_mod._run_search_channel = _run_search_channel  # type: ignore[assignment]

by_ch: dict[str, list[float]] = {}
for row in channel_rows:
    by_ch.setdefault(row["ch"], []).append(row["ms"])
for ch, times in sorted(by_ch.items()):
    _stats(times, ch)

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("SUMMARY")
print("=" * 65)
_stats(pp_lats, "A  ProcessPool (current)")
_stats(tp_lats, "D  ThreadPool")
_stats(seq_lats, "E  Sequential")
pp_mean = statistics.mean(pp_lats)
tp_mean = statistics.mean(tp_lats)
seq_mean = statistics.mean(seq_lats)
print(
    f"\n  ThreadPool vs ProcessPool:  {pp_mean / tp_mean:.2f}x faster"
    if tp_mean < pp_mean
    else f"\n  ProcessPool vs ThreadPool:  {tp_mean / pp_mean:.2f}x faster"
)
print(f"  Sequential vs ThreadPool:   parallelism saves {(seq_mean - tp_mean):.1f}ms/query ({seq_mean / tp_mean:.2f}x)")
print(f"  Est. IPC overhead/query:    ~{total_ipc:.1f}ms" if captured_channels else "")
