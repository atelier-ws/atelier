"""CodeGraph MRR eval on SWE-bench pairs.

Methodology mirrors ``eval_external_provider_mrr.py`` — iterate over all (query, tid,
prefix) pairs, run ``codegraph query`` once per unique query, then score each
pair independently via rank-of-gold-file.

Requires ``codegraph`` on PATH (``npm install -g @colbymchenry/codegraph``).
Per-repo index is auto-built on first query (``codegraph init``).

Environment variables (same as eval_external_provider_mrr):
  FITNESS_PAIRS     Path to pairs JSON  (default: benchmarks/codebench/data/bench_pairs_def_gold.json)
  FITNESS_SAMPLE    Cap total unique queries across all repos (default: 0 = all)
  FITNESS_REPO      Substring filter on repo prefix
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SAMPLE = int(os.environ.get("FITNESS_SAMPLE", "0"))
REPO_FILTER = os.environ.get("FITNESS_REPO", "")
# FITNESS_PAIRS may be a comma-separated list of gold files. Query each unique
# query once (the union across golds) and score it against EVERY gold, so all
# channels run the exact same query universe -> one combined entry (out["golds"]).
_gold_paths = [
    p.strip()
    for p in os.environ.get("FITNESS_PAIRS", "benchmarks/codebench/data/bench_pairs_def_gold.json").split(",")
    if p.strip()
]
_golds = []  # (gold_kind, pairs, true_map)
repos = None
for _gp in _gold_paths:
    with open(_gp) as _f:
        _d = json.load(_f)
    if repos is None:
        repos = _d["repos"]
    _golds.append((_d.get("gold_kind", "definition"), _d["pairs"], _d["true_map"]))
pairs = [row for _k, _p, _tm in _golds for row in _p]


def norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def rank_of_true(files: list, true_files: list[str]) -> int | None:
    """Return 1-indexed rank of the first true file, or None."""
    tn = [norm(t) for t in true_files]
    for i, f in enumerate(files, 1):
        nf = norm(f)
        if any(nf.endswith(t) or t.endswith(nf) for t in tn):
            return i
    return None


def parse_results(stdout: str) -> list[str]:
    """Parse CodeGraph query results into a ranked list of file paths."""
    try:
        results = json.loads(stdout)
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        if isinstance(results, dict):
            results = list(results.values()) if results else []
        if not isinstance(results, list):
            return []
    except json.JSONDecodeError:
        return []
    files: list[str] = []
    seen: set[str] = set()
    for r in results:
        if isinstance(r, dict):
            node = r.get("node", r)
            path = node.get("filePath", "") or node.get("path", "") or ""
        elif isinstance(r, str):
            path = r
        else:
            continue
        if path and path not in seen:
            seen.add(path)
            files.append(path)
    return files


# ── Phase 1: unique queries per repo ──────────────────────────────────

uq: dict[str, set[str]] = {}
for q, _tid, prefix in pairs:
    uq.setdefault(prefix, set()).add(q)

if REPO_FILTER:
    uq = {p: qs for p, qs in uq.items() if REPO_FILTER in p}
if SAMPLE:
    # Spread SAMPLE evenly across repos (matches eval_external_provider_mrr behavior),
    # so FITNESS_SAMPLE=N caps total unique queries to ~N, not N per repo.
    n_repos = max(len(uq), 1)
    per_repo = max(1, SAMPLE // n_repos)
    uq = {p: sorted(qs)[:per_repo] for p, qs in uq.items()}

runset = {p: set(qs) for p, qs in uq.items()}
total_unique = sum(len(qs) for qs in uq.values())
pair_count = sum(1 for q, _, p in pairs if q in runset.get(p, set()))

print(
    f"[cg] {total_unique} unique queries across {len(uq)} repos, scoring {pair_count} pairs",
    file=sys.stderr,
)


# ── Phase 2: run codegraph query for each unique query ─────────────────

filecache: dict[tuple[str, str], list[str]] = {}
done = 0
t0 = time.time()
last_progress_done = 0
last_progress_t = t0
latencies: list[float] = []

for prefix, queries in sorted(uq.items()):
    meta = repos[prefix]
    ws = meta["ws"]

    # Auto-init CodeGraph index if missing
    cg_dir = Path(ws) / ".codegraph"
    if not (cg_dir / "codegraph.db").exists():
        print(f"[cg] init {prefix}...", file=sys.stderr)
        t1 = time.time()
        r = subprocess.run(
            ["codegraph", "init", "-i", ws],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            print(f"[cg] init FAILED for {prefix}: {r.stderr[:500]}", file=sys.stderr)
            continue
        print(f"[cg] init {prefix} done in {time.time() - t1:.1f}s", file=sys.stderr)

    for query in sorted(queries):
        t1 = time.time()
        r = subprocess.run(
            ["codegraph", "query", "-p", ws, "-l", "20", "-j", query],
            capture_output=True,
            text=True,
            timeout=120,
        )
        latencies.append((time.time() - t1) * 1000)

        if r.returncode == 0:
            files = parse_results(r.stdout)
        else:
            print(f"[cg] FAIL query {prefix} {query[:50]}: {r.stderr[:200]}", file=sys.stderr)
            files = []

        filecache[(prefix, query)] = files
        done += 1
        if done % 50 == 0 or done == total_unique:
            now = time.time()
            elapsed_total = now - t0
            interval_done = done - last_progress_done
            interval_elapsed = now - last_progress_t
            rate = interval_done / interval_elapsed if interval_elapsed else 0
            eta = (total_unique - done) / rate if rate else 0
            print(
                f"[cg] queries {done}/{total_unique} elapsed={elapsed_total:.0f}s rate={rate:.1f}/s eta={eta:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            last_progress_done = done
            last_progress_t = now


# ── Phase 3: score each pair independently ─────────────────────────────


def _pct(vals: list[float], p: int) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int((p / 100.0) * (len(s) - 1)))]


def _score_gold(gpairs, gtm):
    agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
    by_repo: dict[str, dict] = {}
    for q, tid, prefix in gpairs:
        if q not in runset.get(prefix, set()):
            continue
        trues = [p.replace("\\", "/") for p in gtm.get(tid, []) if p]
        if not trues:
            continue
        r = rank_of_true(filecache.get((prefix, q), []), trues)
        br = by_repo.setdefault(prefix, {"rr": 0.0, "h1": 0, "h3": 0, "n": 0})
        for d in (agg, br):
            d["n"] += 1
            if r is not None:
                d["rr"] += 1.0 / r
                if r == 1:
                    d["h1"] += 1
                if r <= 3:
                    d["h3"] += 1
    return {
        "mrr": round(agg["rr"] / max(agg["n"], 1), 4),
        "hit1": round(agg["h1"] / max(agg["n"], 1), 4),
        "hit3": round(agg["h3"] / max(agg["n"], 1), 4),
        "n": agg["n"],
        "by_repo": {p: {"mrr": round(d["rr"] / max(d["n"], 1), 4), "n": d["n"]} for p, d in sorted(by_repo.items())},
    }


_lat = {
    "mean": round(sum(latencies) / max(len(latencies), 1), 1),
    "p50": round(_pct(latencies, 50), 1),
    "p95": round(_pct(latencies, 95), 1),
    "max": round(max(latencies), 1) if latencies else 0,
    "over_100ms": sum(1 for x in latencies if x > 100.0),
}
_gold_scores = {kind: _score_gold(gp, gtm) for kind, gp, gtm in _golds}
out = {**_gold_scores[_golds[0][0]], "latency_ms": _lat, "golds": _gold_scores}
print(json.dumps(out))
