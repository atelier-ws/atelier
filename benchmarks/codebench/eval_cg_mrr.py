"""CodeGraph MRR eval on SWE-bench pairs.

Methodology mirrors ``fitness_explore_mrr.py`` — iterate over all (query, tid,
prefix) pairs, run ``codegraph query`` once per unique query, then score each
pair independently via rank-of-gold-file.

Requires ``codegraph`` on PATH (``npm install -g @colbymchenry/codegraph``).
Per-repo index is auto-built on first query (``codegraph init``).

Environment variables (same as fitness_explore_mrr):
  FITNESS_PAIRS     Path to pairs JSON  (default: benchmarks/codebench/data/bench_pairs_multi.json)
  FITNESS_SAMPLE    Cap unique queries per repo  (default: 0 = all)
  FITNESS_REPO      Substring filter on repo prefix
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

DATA = os.environ.get("FITNESS_PAIRS", "benchmarks/codebench/data/bench_pairs_multi.json")
SAMPLE = int(os.environ.get("FITNESS_SAMPLE", "0"))
REPO_FILTER = os.environ.get("FITNESS_REPO", "")

with open(DATA) as f:
    data = json.load(f)

pairs = data["pairs"]
repos = data["repos"]
true_map = data["true_map"]


def get_gold_files(tid: str) -> list[str]:
    paths = true_map.get(tid, [])
    return [p.replace("\\", "/") for p in paths if p]


def norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def rank_of_true(files: list, true_files: list[str]) -> int | None:
    """Return 1‑indexed rank of the first true file, or None."""
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
    uq = {p: sorted(qs)[:SAMPLE] for p, qs in uq.items()}

runset = {p: set(qs) for p, qs in uq.items()}
total_unique = sum(len(qs) for qs in uq.values())
pair_count = sum(1 for q, _, p in pairs if q in runset.get(p, set()))

print(
    f"[cg] {total_unique} unique queries across {len(uq)} repos, " f"scoring {pair_count} pairs",
    file=sys.stderr,
)


# ── Phase 2: run codegraph query for each unique query ─────────────────

filecache: dict[tuple[str, str], list[str]] = {}
done = 0
t0 = time.time()
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
        print(f"[cg] init {prefix} done in {time.time()-t1:.1f}s", file=sys.stderr)

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
            elapsed_total = time.time() - t0
            rate = done / elapsed_total if elapsed_total else 0
            eta = (total_unique - done) / rate if rate else 0
            print(
                f"[cg] queries {done}/{total_unique} " f"elapsed={elapsed_total:.0f}s rate={rate:.1f}/s eta={eta:.0f}s",
                file=sys.stderr,
                flush=True,
            )


# ── Phase 3: score each pair independently ─────────────────────────────

agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
by_repo: dict[str, dict] = {}
for q, tid, prefix in pairs:
    if q not in runset.get(prefix, set()):
        continue
    trues = get_gold_files(tid)
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


def mrr(d: dict) -> float:
    return d["rr"] / max(d["n"], 1)


def _pct(vals: list[float], p: int) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int((p / 100.0) * (len(s) - 1)))]


out = {
    "mrr": round(mrr(agg), 4),
    "hit1": round(agg["h1"] / max(agg["n"], 1), 4),
    "hit3": round(agg["h3"] / max(agg["n"], 1), 4),
    "n": agg["n"],
    "latency_ms": {
        "mean": round(sum(latencies) / max(len(latencies), 1), 1),
        "p50": round(_pct(latencies, 50), 1),
        "p95": round(_pct(latencies, 95), 1),
        "max": round(max(latencies), 1) if latencies else 0,
        "over_100ms": sum(1 for x in latencies if x > 100.0),
    },
    "by_repo": {p: {"mrr": round(mrr(d), 4), "n": d["n"]} for p, d in sorted(by_repo.items())},
}
print(json.dumps(out))
