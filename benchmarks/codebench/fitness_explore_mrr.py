"""Multi-repo offline fitness: tool_explore MRR over mined (query, gold-file)
pairs across the diverse-6 SWE-bench repos. Optimizes the SHIPPED tool (explore,
the only advertised retrieval tool), scored by rank-of-gold-true-file.

Routing: /tmp/bench_pairs_multi.json (scripts/_provision_repos.py) maps each
(query, tid, repo-prefix) and each repo-prefix to a prebuilt read-only index
(ws, db). One engine per repo.

Isolation without copies: explore caches results keyed by query (NOT code
version), so we stub the cache (force-miss + no-op set). Each candidate's OWN
ranking is measured, candidates never read each other's results, and the shared
per-repo index DBs stay effectively read-only (any engine_state writes are
code-independent and harmless). This is the cheap multi-repo equivalent of a
per-worktree DB copy -- same no-contamination guarantee, no 8GB of copies.

Multi-repo guards against Django-overfit: a change must lift MRR across repos.
Deterministic (no reps). Set FITNESS_SAMPLE=N to cap unique queries/repo for a
faster signal. Emits one JSON line:
  {"mrr":float,"hit1":float,"hit3":float,"n":int,"by_repo":{prefix:{mrr,n}}}
"""

import contextlib
import datetime as _dt
import json
import multiprocessing
import os
import subprocess as _sp
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

try:
    from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
except Exception:
    get_zoekt_supervisor = None

import argparse as _ap

_parser = _ap.ArgumentParser(description="Explore MRR benchmark")
_parser.add_argument(
    "--full",
    action="store_true",
    help="Run all available query pairs (no cap).",
)
_parser.add_argument(
    "--sample",
    nargs="?",
    const=50,
    type=int,
    default=None,
    metavar="N",
    help="Total queries to sample across repos (default 50 when flag given).",
)
_parser.add_argument(
    "--repo",
    default=os.environ.get("FITNESS_REPO", ""),
    metavar="SUBSTR",
    help="Filter to repos whose prefix contains SUBSTR.",
)
_args, _ = _parser.parse_known_args()

with open(os.environ.get("FITNESS_PAIRS", "/tmp/bench_pairs_multi.json")) as fh:
    data = json.load(fh)
pairs = data["pairs"]
true_map = data["true_map"]
repos = data["repos"]
# Backward-compat env vars; CLI flags take precedence.
_env_sample = int(os.environ.get("FITNESS_SAMPLE", "0"))
REPO = _args.repo
# Resolve final total-query cap:
#   --full  → 0 (no cap)
#   --sample N  → N  (or 50 if flag given without value)
#   default (no flags)  → 500
#   FITNESS_SAMPLE env var  → still honoured if no CLI flag given
if _args.full:
    SAMPLE = 0
elif _args.sample is not None:
    SAMPLE = _args.sample
elif _env_sample:
    SAMPLE = _env_sample
else:
    SAMPLE = 500  # default: 500 diverse queries across repos


def norm(p):
    return (p or "").replace("\\", "/")


def dedup(fs):
    seen = set()
    out = []
    for f in fs:
        f = norm(f)
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


engines = {}
for prefix, meta in repos.items():
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)  # force recompute (no cross-candidate cache)
    eng._cache_set = lambda *a, **k: None
    if get_zoekt_supervisor is not None:
        with contextlib.suppress(Exception):
            get_zoekt_supervisor(Path(meta["ws"]))
    engines[prefix] = eng

# unique queries per repo (deterministic optional sample)
uq = {}
for q, _tid, prefix in pairs:
    uq.setdefault(prefix, [])
    if q not in uq[prefix]:
        uq[prefix].append(q)
if REPO:
    uq = {p: qs for p, qs in uq.items() if REPO in p}
if SAMPLE:
    # Spread SAMPLE evenly across repos so each repo is represented.
    n_repos = max(len(uq), 1)
    per_repo = max(1, SAMPLE // n_repos)
    uq = {p: sorted(qs)[:per_repo] for p, qs in uq.items()}
runset = {p: set(qs) for p, qs in uq.items()}

# Parallel: explores are independent reads. The engine is thread-safe per call
# (per-thread connections via _reuse_connection's thread-local, stubbed cache,
# instance centrality cache pre-warmed below), so a thread pool gives near-linear
# speedup on the I/O+sqlite-bound work. Tune with FITNESS_WORKERS.
_WORKERS = int(os.environ.get("FITNESS_WORKERS", "0")) or max(1, min(8, (os.cpu_count() or 4) // 4))
_lean = os.environ.get("FITNESS_LEAN") == "1"

# Pre-warm per-repo centrality once (compute+persist) so concurrent workers share
# the cached map instead of racing to recompute the power iteration.
for _prefix in list(uq):
    _eng = engines.get(_prefix)
    if _eng is not None:
        with contextlib.suppress(Exception):
            _eng._symbol_centrality_map()

_tasks = [(prefix, q) for prefix, qs in uq.items() for q in qs]
_total = len(_tasks)


def _run_explore(task):
    prefix, q = task
    eng = engines.get(prefix)
    if eng is None:
        return prefix, q, [], 0.0
    _ts = time.perf_counter()
    try:
        r = eng.tool_explore(
            q,
            max_files=10,
            auto_index=False,
            **({"include_source": False, "include_relationships": False} if _lean else {}),
        )
        files = dedup([f.get("path", "") for f in r.get("files", [])])[:10]
    except Exception:
        files = []
    # Per-query wall-clock of the explore call. Accurate only with FITNESS_WORKERS=1
    # (parallel workers contend on CPU and inflate each call's measured duration).
    return prefix, q, files, (time.perf_counter() - _ts) * 1000.0


filecache = {}
latencies: list[float] = []
repo_latencies: dict[str, list[float]] = {}
_done = 0
_t0 = time.perf_counter()
print(f"[fitness] start: {_total} explores across {len(uq)} repos, {_WORKERS} workers", file=sys.stderr, flush=True)
# Processes, not threads: explores are CPU-bound (GIL-serialized under threads) and
# share one engine instance per repo -- a process pool gives true parallelism and
# isolates each worker's sqlite connections (fork inherits the pre-warmed engines).
with ProcessPoolExecutor(max_workers=_WORKERS, mp_context=multiprocessing.get_context("fork")) as _ex:
    for prefix, q, files, lat_ms in _ex.map(_run_explore, _tasks, chunksize=4):
        filecache[(prefix, q)] = files
        latencies.append(lat_ms)
        repo_latencies.setdefault(prefix, []).append(lat_ms)
        _done += 1
        if _done % 20 == 0 or _done == _total:
            _el = time.perf_counter() - _t0
            _rate = _done / _el if _el else 0.0
            _eta = (_total - _done) / _rate if _rate else 0.0
            print(
                f"[fitness] {_done}/{_total} elapsed={_el:.0f}s rate={_rate:.1f}/s eta={_eta:.0f}s",
                file=sys.stderr,
                flush=True,
            )


def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
by_repo = {}
for q, tid, prefix in pairs:
    if q not in runset.get(prefix, ()):
        continue
    trues = true_map.get(tid)
    if not trues:
        continue
    r = rank_true(filecache.get((prefix, q), []), trues)
    br = by_repo.setdefault(prefix, {"rr": 0.0, "h1": 0, "h3": 0, "n": 0})
    for d in (agg, br):
        d["n"] += 1
        if r:
            d["rr"] += 1.0 / r
            if r == 1:
                d["h1"] += 1
            if r <= 3:
                d["h3"] += 1


def mrr(d):
    return d["rr"] / max(d["n"], 1)


def _pct(vals, p):
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
        "max": round(max(latencies), 1) if latencies else 0.0,
        "over_100ms": sum(1 for x in latencies if x > 100.0),
    },
    "by_repo": {
        p: {
            "mrr": round(mrr(d), 4),
            "hit1": round(d["h1"] / max(d["n"], 1), 4),
            "hit3": round(d["h3"] / max(d["n"], 1), 4),
            "n": d["n"],
            "latency_ms": {
                "mean": round(sum(repo_latencies.get(p, [0])) / max(len(repo_latencies.get(p, [1])), 1), 1),
                "p50": round(_pct(repo_latencies.get(p, [0]), 50), 1),
                "p95": round(_pct(repo_latencies.get(p, [0]), 95), 1),
                "max": round(max(repo_latencies.get(p, [0])), 1),
                "over_100ms": sum(1 for x in repo_latencies.get(p, []) if x > 100.0),
            },
        }
        for p, d in sorted(by_repo.items())
    },
}
print(json.dumps(out))

# ── History: persist this run and show trend ──────────────────────────────────
_HISTORY = Path("reports/benchmark/mrr_history.jsonl")
_HISTORY.parent.mkdir(parents=True, exist_ok=True)

# Collect git SHA + dirty flag (best-effort)
try:
    _sha = _sp.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    _dirty = bool(_sp.check_output(["git", "status", "--porcelain"], text=True).strip())
    _sha_label = _sha + ("+" if _dirty else "")
except Exception:
    _sha_label = "unknown"

# Encode the CLI mode used
_mode = "full" if _args.full else (f"sample={_args.sample}" if _args.sample else "default")
if REPO:
    _mode += f" repo={REPO}"

_record = {
    "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
    "sha": _sha_label,
    "mode": _mode,
    "mrr": out["mrr"],
    "hit1": out["hit1"],
    "hit3": out["hit3"],
    "n": out["n"],
    "latency_ms": out["latency_ms"],
    "by_repo": out["by_repo"],
}
with _HISTORY.open("a") as _fh:
    _fh.write(json.dumps(_record) + "\n")

# Show last 8 runs as a comparison table
try:
    _runs = [json.loads(line) for line in _HISTORY.read_text().splitlines() if line.strip()]
except Exception:
    _runs = [_record]
_tail = _runs[-8:]
_ref_mrr = _tail[0]["mrr"] if len(_tail) > 1 else None

_LAT = "latency_ms"  # shorthand
_REPO_COL = 30
_RUN_HDR = (
    f"  {'repo':{_REPO_COL}}  {'n':>5}  {'MRR':>6}  {'hit1':>6}  {'hit3':>6}"
    f"  {'mean':>7}  {'p50':>7}  {'p95':>7}  {'max':>8}  {'>100ms':>6}"
)
_RUN_SEP = "-" * len(_RUN_HDR)


def _lat_row(lat: dict) -> str:
    p50 = lat.get("p50") or lat.get("lat_p50") or 0.0
    return (
        f"  {lat.get('mean', 0):>7.1f}  {p50:>7.1f}"
        f"  {lat.get('p95', 0):>7.1f}  {lat.get('max', 0):>8.1f}  {lat.get('over_100ms', 0):>6}"
    )


print("", file=sys.stderr)
for _i, _r in enumerate(_tail):
    _delta = ""
    if _ref_mrr is not None and _r is not _tail[0]:
        _d = _r["mrr"] - _ref_mrr
        _delta = f" ({_d:+.4f})"
    elif _r is _tail[0] and len(_tail) > 1:
        _delta = " (base)"
    _global_lat = _r.get(_LAT) or {}
    _p50g = _global_lat.get("p50") or _r.get("lat_p50") or 0.0
    # Run header line
    print(
        f"[{_i+1}/{len(_tail)}] {_r['ts']}  sha={_r['sha']}  mode={_r['mode']}"
        f"  n={_r['n']}  MRR={_r['mrr']:.4f}{_delta}"
        f"  hit1={_r['hit1']:.4f}  hit3={_r['hit3']:.4f}",
        file=sys.stderr,
    )
    # Global latency
    print(
        f"     latency (global):  mean={_global_lat.get('mean',0):.1f}ms"
        f"  p50={_p50g:.1f}ms  p95={_global_lat.get('p95',0):.1f}ms"
        f"  max={_global_lat.get('max',0):.1f}ms  >100ms={_global_lat.get('over_100ms',0)}",
        file=sys.stderr,
    )
    # Per-repo breakdown
    _by_repo = _r.get("by_repo") or {}
    if _by_repo:
        print(_RUN_HDR, file=sys.stderr)
        print(_RUN_SEP, file=sys.stderr)
        for _repo, _rd in sorted(_by_repo.items()):
            if isinstance(_rd, dict):
                _rlat = _rd.get(_LAT) or {}
                _rmrr = _rd.get("mrr", _rd) if isinstance(_rd, dict) else _rd
                print(
                    f"  {_repo:{_REPO_COL}}  {_rd.get('n',0):>5}"
                    f"  {_rd.get('mrr',0):>6.4f}  {_rd.get('hit1',0):>6.4f}  {_rd.get('hit3',0):>6.4f}"
                    + _lat_row(_rlat),
                    file=sys.stderr,
                )
            else:
                # old record: by_repo was {repo: mrr_float}
                print(f"  {_repo:{_REPO_COL}}  {'':>5}  {_rd:>6.4f}", file=sys.stderr)
    if _i < len(_tail) - 1:
        print("", file=sys.stderr)
print("", file=sys.stderr)
