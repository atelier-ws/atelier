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
    # Schema is already initialised; skip the CREATE TABLE IF NOT EXISTS write on
    # first use so the benchmark never acquires a write lock on live DBs (e.g.
    # atelier's own DB which autosync may be writing to concurrently).
    eng._schema_ready = True
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
# Soft timeout per explore call (seconds). Prevents a single slow FTS query from
# blocking a worker slot. 0 = no timeout. Tune with FITNESS_TIMEOUT.
_TIMEOUT_S = float(os.environ.get("FITNESS_TIMEOUT", "3.0"))

# Pre-warm per-repo centrality once (compute+persist) so concurrent workers share
# the cached map instead of racing to recompute the power iteration.
for _prefix in list(uq):
    _eng = engines.get(_prefix)
    if _eng is not None:
        with contextlib.suppress(Exception):
            _eng._symbol_centrality_map()

_tasks = [(prefix, q) for prefix, qs in uq.items() for q in qs]
# Shuffle so diverse repos interleave — avoids all-django at the front, which
# causes the rate monitor to show a misleadingly low initial rate.
import random as _random  # noqa: E402

_random.seed(42)
_random.shuffle(_tasks)
_total = len(_tasks)


def _worker_init() -> None:
    """Prepare each forked worker for benchmark use.

    Thread pools do NOT survive fork() safely: the inherited
    _SEARCH_CHANNEL_EXECUTOR has dead parent threads and potentially locked
    internal state, causing silent deadlocks on submit().  Replace it with a
    fresh pool in each child process before any task runs.
    """
    import concurrent.futures as _cf
    import atelier.core.capabilities.code_context.engine as _eng_mod

    _eng_mod._SEARCH_CHANNEL_EXECUTOR = _cf.ThreadPoolExecutor(
        max_workers=5, thread_name_prefix="atelier-fts-channel"
    )
    for eng in engines.values():
        with contextlib.suppress(Exception):
            eng._symbol_centrality_map()


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
    lat = (time.perf_counter() - _ts) * 1000.0
    # Per-query wall-clock of the explore call. Accurate only with FITNESS_WORKERS=1
    # (parallel workers contend on CPU and inflate each call's measured duration).
    return prefix, q, files, lat


filecache = {}
latencies: list[float] = []
repo_latencies: dict[str, list[float]] = {}
_done = 0
print(f"[fitness] start: {_total} explores across {len(uq)} repos, {_WORKERS} workers", file=sys.stderr, flush=True)
# Processes, not threads: explores are CPU-bound (GIL-serialized under threads) and
# share one engine instance per repo -- a process pool gives true parallelism and
# isolates each worker's sqlite connections (fork inherits the pre-warmed engines).
# _t0 is set AFTER the executor is created and workers have finished their
# _worker_init warmup, so the progress rate reflects only benchmark task time.
with ProcessPoolExecutor(
    max_workers=_WORKERS,
    mp_context=multiprocessing.get_context("fork"),
    initializer=_worker_init,
) as _ex:
    _t0 = time.perf_counter()
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

# ── Pretty summary: current run + delta vs previous ─────────────────────────
try:
    _runs = [json.loads(line) for line in _HISTORY.read_text().splitlines() if line.strip()]
except Exception:
    _runs = [_record]

_cur = _runs[-1]
# Only compare against a previous run of the same mode (type) — cross-mode
# comparisons (e.g. full vs default) are meaningless since different sample
# sizes and selection skew the MRR baseline.
_prev = None
if len(_runs) >= 2:
    for r in reversed(_runs[:-1]):
        if r.get("mode") == _cur.get("mode"):
            _prev = r
            break
_L = "latency_ms"


def _glat(rec: dict) -> dict:
    return rec.get(_L) or {}


def _p50(rec: dict) -> float:
    g = _glat(rec)
    return g.get("p50") or rec.get("lat_p50") or 0.0


def _mrr_icon(m: float) -> str:
    if m >= 0.80:
        return "✓"
    if m >= 0.60:
        return "~"
    return "✗"


def _delta_str(new: float, old: float) -> str:
    d = new - old
    return f"+{d:.3f}" if d >= 0 else f"{d:.3f}"


_W = 60
_sep = "─" * _W
print("", file=sys.stderr)
print(_sep, file=sys.stderr)

# ── Current run ──
_cl = _glat(_cur)
print(
    f"  {_cur['ts'][:16]}  {_cur['sha']}  [{_cur['mode']}]  n={_cur['n']}",
    file=sys.stderr,
)
print(
    f"  MRR {_cur['mrr']:.4f}   hit@1 {_cur['hit1']:.4f}   hit@3 {_cur['hit3']:.4f}",
    file=sys.stderr,
)
if _cl:
    print(
        f"  lat  mean={_cl.get('mean', 0):.0f}ms  p50={_cl.get('p50', 0):.0f}ms"
        f"  p95={_cl.get('p95', 0):.0f}ms  max={_cl.get('max', 0):.0f}ms  >100ms={_cl.get('over_100ms', 0)}",
        file=sys.stderr,
    )

# ── Per-repo highlights ──
_by = _cur.get("by_repo") or {}
if _by:
    print("", file=sys.stderr)
    # sort: worst MRR first so problems are visible
    for _rname, _rd in sorted(
        _by.items(), key=lambda kv: kv[1].get("mrr", kv[1]) if isinstance(kv[1], dict) else kv[1]
    ):
        _rm = _rd.get("mrr", _rd) if isinstance(_rd, dict) else _rd
        _rl = _rd.get(_L, {}) if isinstance(_rd, dict) else {}
        _rn = _rd.get("n", "") if isinstance(_rd, dict) else ""
        _short = _rname.split("__")[-1]  # drop org prefix
        _p95 = _rl.get("p95", 0)
        _max = _rl.get("max", 0)
        _lat_note = ""
        if _p95 or _max:
            _warn = " ⚠" if _p95 > 300 else ""
            _lat_note = f"  p95={_p95:.0f}ms  p100={_max:.0f}ms{_warn}"
        print(
            f"  {_mrr_icon(_rm)}  {_short:<22}  n={_rn:<4}  MRR={_rm:.3f}{_lat_note}",
            file=sys.stderr,
        )

# ── Delta vs previous ──
if _prev:
    print("", file=sys.stderr)
    _pmrr = _prev["mrr"]
    _dmrr = _cur["mrr"] - _pmrr
    _sign = "+" if _dmrr >= 0 else ""
    print(
        f"  vs {_prev['ts'][:16]} [{_prev['mode']}]  MRR {_pmrr:.4f} → {_cur['mrr']:.4f}  ({_sign}{_dmrr:.4f})",
        file=sys.stderr,
    )
    # per-repo deltas — only show movers
    _pby = _prev.get("by_repo") or {}
    _movers = []
    for _rname in set(list(_by.keys()) + list(_pby.keys())):
        _cm = (_by.get(_rname) or {}).get("mrr", 0) if isinstance(_by.get(_rname), dict) else (_by.get(_rname) or 0)
        _pm = (_pby.get(_rname) or {}).get("mrr", 0) if isinstance(_pby.get(_rname), dict) else (_pby.get(_rname) or 0)
        if _cm != _pm:
            _movers.append((_rname.split("__")[-1], _pm, _cm, _cm - _pm))
    if _movers:
        _movers.sort(key=lambda x: x[3])
        for _rn, _pm, _cm, _dd in _movers:
            _sign2 = "+" if _dd >= 0 else ""
            print(f"    {_rn:<22}  {_pm:.3f} → {_cm:.3f}  ({_sign2}{_dd:.3f})", file=sys.stderr)

print(_sep, file=sys.stderr)
print("", file=sys.stderr)
