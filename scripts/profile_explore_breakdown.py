"""Profile the full tool_explore pipeline broken into sub-stages.

For each query measures wall time for:
  1. _tool_explore_impl  (baseline: symbol search + Zoekt + pack)
  2. _hef_exact_symbol_candidates  (V6 exact-symbol SQL)
  3. _hef_anchor_zoekt_candidates  (V6 anchor Zoekt HTTP calls)
  4. _hef_line_fts_candidates      (V6 line FTS, LIMIT 700 + 2600)
  5. _fused_explore_hybrid scoring  (pure Python after above)
  6. _rerank_explore_result         (linear reranker)

Usage: uv run python scripts/profile_explore_breakdown.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from atelier.core.capabilities.code_context.engine import (
    CodeContextEngine,
    _default_db_path,
)

with open("benchmarks/codebench/data/bench_pairs_multi.json") as f:
    _data = json.load(f)
pairs = _data["pairs"]
repos = _data["repos"]

TARGET_REPOS = ["django__django", "astropy__astropy", "pydata__xarray"]
N_QUERIES = 25  # per repo


def get_engine(prefix: str) -> CodeContextEngine:
    info = repos[prefix]
    ws = Path(info["ws"])
    db = _default_db_path(ws)
    return CodeContextEngine(repo_root=ws, db_path=db)


engines = {p: get_engine(p) for p in TARGET_REPOS}

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

print(f"Profiling {len(sample_tasks)} queries across {len(TARGET_REPOS)} repos\n", flush=True)


# ── Patch tool_explore to record per-stage timings ──────────────────────────

timings: dict[str, list[float]] = {
    "impl": [],
    "hef_exact": [],
    "hef_anchor": [],
    "hef_line": [],
    "hef_fusion": [],
    "rerank": [],
    "total": [],
}

_orig_impl = CodeContextEngine._tool_explore_impl
_orig_fused = CodeContextEngine._fused_explore_hybrid
_orig_exact = CodeContextEngine._hef_exact_symbol_candidates
_orig_anchor = CodeContextEngine._hef_anchor_zoekt_candidates
_orig_line = CodeContextEngine._hef_line_fts_candidates
_orig_rerank = CodeContextEngine._rerank_explore_result


def _timed_exact(self, plan):  # type: ignore[misc]
    t0 = time.perf_counter()
    r = _orig_exact(self, plan)
    timings["hef_exact"].append((time.perf_counter() - t0) * 1000)
    return r


def _timed_anchor(self, plan):  # type: ignore[misc]
    t0 = time.perf_counter()
    r = _orig_anchor(self, plan)
    timings["hef_anchor"].append((time.perf_counter() - t0) * 1000)
    return r


def _timed_line(self, plan):  # type: ignore[misc]
    t0 = time.perf_counter()
    r = _orig_line(self, plan)
    timings["hef_line"].append((time.perf_counter() - t0) * 1000)
    return r


_line_row_counts: list[int] = []


def _timed_line_with_count(self, plan):  # type: ignore[misc]
    """Timed wrapper that also records how many rows file_line_fts returns."""
    # Patch the connection to count rows

    if not plan.terms:
        timings["hef_line"].append(0.0)
        return [], {}

    terms = [t.lower() for t in plan.terms]
    from atelier.core.capabilities.code_context.engine import _hef_fts_phrase

    or_query = " OR ".join(_hef_fts_phrase(t) for t in terms)
    and_query = " AND ".join(_hef_fts_phrase(t) for t in terms[: min(8, len(terms))])

    t0 = time.perf_counter()
    total_rows = 0
    try:
        with self._connect(readonly=True) as conn:
            if len(terms) >= 2:
                and_rows = conn.execute(
                    "SELECT file_path, line, text, bm25(file_line_fts) AS rank "
                    "FROM file_line_fts WHERE file_line_fts MATCH ? AND repo_id = ? "
                    "ORDER BY rank ASC, file_path ASC, line ASC LIMIT 700",
                    (and_query, self.repo_id),
                ).fetchall()
                total_rows += len(and_rows)
            or_rows = conn.execute(
                "SELECT file_path, line, text, bm25(file_line_fts) AS rank "
                "FROM file_line_fts WHERE file_line_fts MATCH ? AND repo_id = ? "
                "ORDER BY rank ASC, file_path ASC, line ASC LIMIT 2600",
                (or_query, self.repo_id),
            ).fetchall()
            total_rows += len(or_rows)
    except Exception:  # noqa: BLE001
        pass
    elapsed = (time.perf_counter() - t0) * 1000
    timings["hef_line"].append(elapsed)
    _line_row_counts.append(total_rows)
    # Fall through to the real implementation for correctness
    return _orig_line(self, plan)


def _timed_fused(self, query, baseline_payload, max_files, precomputed_zoekt=None):  # type: ignore[misc]
    # Time only the fusion scoring (after hef_* calls inside it)
    # We'll instrument the sub-calls separately above
    t0 = time.perf_counter()
    r = _orig_fused(self, query, baseline_payload, max_files=max_files, precomputed_zoekt=precomputed_zoekt)
    timings["hef_fusion"].append((time.perf_counter() - t0) * 1000)
    return r


def _timed_rerank(self, query, payload):  # type: ignore[misc]
    t0 = time.perf_counter()
    r = _orig_rerank(self, query, payload)
    timings["rerank"].append((time.perf_counter() - t0) * 1000)
    return r


CodeContextEngine._hef_exact_symbol_candidates = _timed_exact  # type: ignore[method-assign]
CodeContextEngine._hef_anchor_zoekt_candidates = _timed_anchor  # type: ignore[method-assign]
CodeContextEngine._hef_line_fts_candidates = _timed_line_with_count  # type: ignore[method-assign]
CodeContextEngine._fused_explore_hybrid = _timed_fused  # type: ignore[method-assign]
CodeContextEngine._rerank_explore_result = _timed_rerank  # type: ignore[method-assign]

# ── Warmup ───────────────────────────────────────────────────────────────────
print("=== WARMUP ===", flush=True)
for prefix, q in sample_tasks[:6]:
    engines[prefix].tool_explore(q, max_files=10, auto_index=False)
for k in timings:
    timings[k].clear()
_line_row_counts.clear()

# ── Main run ─────────────────────────────────────────────────────────────────
print("Running...", flush=True)
total_lats: list[float] = []
for prefix, q in sample_tasks:
    eng = engines[prefix]
    t0 = time.perf_counter()
    eng.tool_explore(q, max_files=10, auto_index=False)  # full: include_source=True
    total_lats.append((time.perf_counter() - t0) * 1000)

# ── Report ───────────────────────────────────────────────────────────────────


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(p / 100.0 * (len(s) - 1)))]


def _row(label: str, vals: list[float], note: str = "") -> None:
    if not vals:
        print(f"  {label:<35s}  (no data)", flush=True)
        return
    pct_total = statistics.mean(vals) / statistics.mean(total_lats) * 100 if total_lats else 0
    print(
        f"  {label:<35s}"
        f"  mean={statistics.mean(vals):6.1f}ms"
        f"  p50={statistics.median(vals):6.1f}ms"
        f"  p95={_pct(vals, 95):6.1f}ms"
        f"  ({pct_total:.0f}% of total)" + (f"  {note}" if note else ""),
        flush=True,
    )


print("\n" + "=" * 75, flush=True)
print("PER-STAGE BREAKDOWN (tool_explore, include_source=True / full benchmark mode)")
print("=" * 75, flush=True)
_row("TOTAL tool_explore", total_lats)
print(flush=True)
_row("_fused_explore_hybrid (whole)", timings["hef_fusion"])
print("    ├─ of which:", flush=True)
_row("    _hef_exact_symbol_candidates", timings["hef_exact"])
if _line_row_counts:
    avg_rows = sum(_line_row_counts) / len(_line_row_counts)
    _row("    _hef_line_fts_candidates", timings["hef_line"], f"avg {avg_rows:.0f} rows fetched (limit 700+2600)")
else:
    _row("    _hef_line_fts_candidates", timings["hef_line"])
_row("    _hef_anchor_zoekt_candidates", timings["hef_anchor"])
print(flush=True)
_row("_rerank_explore_result", timings["rerank"])
print(flush=True)

impl_approx = [
    t - fus - rr
    for t, fus, rr in zip(
        total_lats,
        timings["hef_fusion"] or [0] * len(total_lats),
        timings["rerank"] or [0] * len(total_lats), strict=False,
    )
]
_row("_tool_explore_impl (approx=total-rest)", impl_approx)

print("\n" + "=" * 75, flush=True)
print(f"n={len(total_lats)}  qps={len(total_lats) / sum(t / 1000 for t in total_lats):.1f}", flush=True)
