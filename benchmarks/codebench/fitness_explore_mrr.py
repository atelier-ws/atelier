"""Multi-repo offline fitness: tool_explore MRR over mined (query, gold-file)
pairs across the diverse-6 SWE-bench repos. Optimizes the SHIPPED tool (explore,
the only advertised retrieval tool), scored by rank-of-gold-true-file.

Routing: benchmarks/codebench/data/bench_pairs_def_gold.json (scripts/_provision_repos.py) maps each
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

# Cap native BLAS/OMP pools to 1 thread BEFORE numpy is imported (via the engine
# import below). Otherwise each of N process workers spawns ~ncpu OpenBLAS threads
# for `matrix @ query`, oversubscribing the cores: measured 100-250 runnable
# threads on 32 cores -> a context-switch storm with near-zero parallel speedup
# (8 workers ~= 1 worker). Capping these + single-threaded workers (below) gave a
# 2.4x throughput win. Overridable from the real environment.
for _thr_var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_thr_var, "1")

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
_parser.add_argument(
    "--reindex",
    action="store_true",
    help="Re-index all repos via 'atelier code index --reindex' before benchmarking.",
)
_parser.add_argument(
    "--channel",
    default=os.environ.get("FITNESS_CHANNEL", "lexical+zoekt"),
    choices=["lexical", "zoekt", "lexical+zoekt", "lexical+zoekt+semantic"],
    help="lexical = pure FTS5 symbol search (no Zoekt); "
    "zoekt = pure Zoekt trigram search; "
    "lexical+zoekt = explore pipeline with both FTS5 + Zoekt parallel (default); "
    "lexical+zoekt+semantic = adds semantic RRF fusion (requires ATELIER_CODE_EMBEDDER).",
)
_args, _ = _parser.parse_known_args()

# FITNESS_PAIRS may be a comma-separated list of gold files. ALL are scored in a
# single run: explore each query once, then score it against every gold. Reported
# as one combined entry (out["golds"][kind]). Latency is gold-independent.
_gold_paths = [
    p.strip()
    for p in os.environ.get("FITNESS_PAIRS", "benchmarks/codebench/data/bench_pairs_def_gold.json").split(",")
    if p.strip()
]
_golds: list[tuple[str, list, dict]] = []  # (gold_kind, pairs, true_map)
# Union of every gold's repos so a single run can score multiple gold sets whose
# repo sets differ (e.g. swebench adds atelier-dev on top of the 14 def-gold
# repos). First definition of a prefix wins; a query whose repo is absent is
# silently skipped by _run_explore, so a missing DB never aborts the run.
repos = {}
for _gp in _gold_paths:
    with open(_gp) as _fh:
        _d = json.load(_fh)
    for _rk, _rv in _d["repos"].items():
        repos.setdefault(_rk, _rv)
    _golds.append((_d.get("gold_kind", "definition"), _d["pairs"], _d["true_map"]))
# Union of all golds' queries drives the (gold-independent) explore phase.
pairs = [row for _k, _p, _tm in _golds for row in _p]
_gold_kind = "+".join(k for k, _p, _tm in _golds)
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


def _db_path_for(ws_path: Path) -> Path:
    from atelier.core.foundation.paths import workspace_key as _wk

    p = Path("/tmp") / _wk(ws_path.resolve()) / "code_context.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _index_one(prefix: str, meta: dict) -> tuple:
    ws_path = Path(meta["ws"])
    db_path = _db_path_for(ws_path)
    print(f"[indexing] {prefix} ...", file=sys.stderr, flush=True)
    t0 = time.perf_counter()
    result = _sp.run(
        [
            "uv",
            "run",
            "atelier",
            "code",
            "index",
            "--repo-root",
            str(ws_path),
            "--db-path",
            str(db_path),
            "--reindex",
            "--no-stats",
        ],
        stderr=sys.stderr,
        check=False,
    )
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        raise RuntimeError(f"{prefix}: atelier code index failed (rc={result.returncode})")
    print(f"[indexed]  {prefix} in {elapsed:.1f}s", file=sys.stderr, flush=True)
    return prefix, db_path


if _args.reindex:
    print(f"[discovering] indexing {len(repos)} repos ...", file=sys.stderr, flush=True)
    for _pfx, _meta in repos.items():
        if REPO and REPO not in _pfx:
            continue
        _index_one(_pfx, _meta)


# ── Channel ──────────────────────────────────────────────────────
CHANNEL = _args.channel
_TAG = f"[{CHANNEL}]"  # shown in progress lines so parallel runs are distinguishable

# Pre-warm the query embedding cache before the eval loop so every embed_query()
# call hits the file cache instead of running GPU inference per query.
if "semantic" in CHANNEL:
    import subprocess as _sp

    _prewarm = Path(__file__).parent / "prewarm_query_cache.py"
    if _prewarm.exists():
        print(f"{_TAG} pre-warming query embedding cache…", flush=True)
        _sp.run([sys.executable, str(_prewarm)], check=False)
        print(f"{_TAG} cache warm — starting eval", flush=True)

if CHANNEL not in ("lexical", "zoekt", "lexical+zoekt", "lexical+zoekt+semantic"):
    print(f"{_TAG} ERROR: unknown channel {CHANNEL!r}", file=sys.stderr, flush=True)
    sys.exit(1)
if CHANNEL == "zoekt" and get_zoekt_supervisor is None:
    print(
        f"{_TAG} WARNING: zoekt adapter not importable; zoekt channel will return empty results.",
        file=sys.stderr,
        flush=True,
    )

engines = {}
for prefix, meta in repos.items():
    if REPO and REPO not in prefix:
        continue
    if _args.reindex:
        _db = _db_path_for(Path(meta["ws"]))
    elif meta.get("db"):
        _db = Path(meta["db"])
    else:
        _db = None  # engine will use default db path for the workspace
    eng = CodeContextEngine(Path(meta["ws"]), db_path=_db, autosync_enabled=False)
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
#
# Worker count. The engine's channels and BLAS each spawn their own threads per
# query, so stacking inner parallelism under many process workers oversubscribes
# the cores (measured: r=180, cs>1M/s, ~no speedup). For batch throughput we run
# MANY single-threaded process workers instead -- inner fan-out off (below), BLAS
# pinned above -- filling the cores cleanly (~2.4x the old 8-worker default). Set
# FITNESS_WORKERS=1 for true single-query interactive latency (inner fan-out kept).
_WORKERS = int(os.environ.get("FITNESS_WORKERS", "0")) or max(1, min(24, int((os.cpu_count() or 4) * 0.6)))
if _WORKERS > 1:
    # Outer (process) parallelism instead of inner (thread) parallelism: each
    # explore runs its channels sequentially so N workers don't each fan out onto
    # the shared inner pools and thrash. MRR is unchanged (ordering-independent).
    os.environ.setdefault("ATELIER_EXPLORE_PARALLEL", "0")
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
    """Per-worker initializer for the fork-based process pool.

    A process pool gives true parallelism (no GIL) for the CPU-bound ranking
    pipeline -- a thread pool is ~1 core and runs ~7x slower here. The one hazard
    is fork-while-threaded: the engine's module-level channel executors are
    ThreadPoolExecutors created in the parent, and fork copies them with dead
    parent threads, so the first submit() in a child would hang. Replace them with
    fresh pools per worker. Centrality maps and ANN vector matrices are warmed in
    the PARENT before fork and inherited copy-on-write (read-only matmul never
    triggers a page copy), so they cost one physical copy across all workers and
    are NOT redone here.
    """
    import concurrent.futures as _cf

    import atelier.core.capabilities.code_context.engine as _eng_mod

    _eng_mod._SEARCH_CHANNEL_EXECUTOR.shutdown(wait=False)
    _eng_mod._SEARCH_CHANNEL_EXECUTOR = _cf.ThreadPoolExecutor(max_workers=16)
    _eng_mod._HEF_CHANNEL_EXECUTOR.shutdown(wait=False)
    _eng_mod._HEF_CHANNEL_EXECUTOR = _cf.ThreadPoolExecutor(max_workers=3, thread_name_prefix="atelier-hef")
    # Pure-lexical channel: turn Zoekt off so tool_explore skips the recall hook.
    if CHANNEL == "lexical":
        os.environ["ATELIER_ZOEKT_MODE"] = "off"
    # Non-semantic channels: turn the embedding recall hook OFF. Without this, a
    # channel like "lexical" silently fused semantic scores whenever
    # ATELIER_CODE_EMBEDDER was set (contaminating the pure-lexical measurement)
    # AND cold-loaded the repo's full vector matrix on every worker -- e.g.
    # linux's multi-GB matrix at ~11s/query -- on a channel that must not use it.
    if "semantic" not in CHANNEL:
        os.environ["ATELIER_EXPLORE_SEMANTIC"] = "0"


def _run_explore(task):
    import signal
    import threading as _threading

    prefix, q = task
    eng = engines.get(prefix)
    if eng is None:
        return prefix, q, [], 0.0
    _ts = time.perf_counter()
    timed_out = False

    # SIGALRM only fires on the main thread; the pool runs tasks on worker
    # threads, so the watchdog is a no-op there (and would raise "signal only
    # works in main thread"). It stays armed only for a 1-worker main-thread run.
    _use_alarm = _TIMEOUT_S > 0 and _threading.current_thread() is _threading.main_thread()
    if _use_alarm:

        def _on_alarm(signum, frame):
            raise TimeoutError

        _prev = signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(max(1, int(_TIMEOUT_S) + 1))

    try:
        if CHANNEL == "zoekt":
            # Pure Zoekt: call the Zoekt candidate channel directly.
            # Returns empty list when Zoekt is unavailable, avoiding
            # the ~0.8s timeout that tool_explore's parallel Zoekt
            # thread would incur.
            files = eng._zoekt_candidate_files(q, max_files=10)
            files = dedup(files)[:10]
        else:
            # lexical or lexical+zoekt: use the full explore pipeline.
            # For pure lexical, ATELIER_ZOEKT_MODE=off is set in
            # _worker_init so Zoekt is skipped internally.
            r = eng.tool_explore(
                q,
                max_files=10,
                auto_index=False,
                **({"include_source": False, "include_relationships": False} if _lean else {}),
            )
            files = dedup([f.get("path", "") for f in r.get("files", [])])[:10]
    except TimeoutError:
        files = []
        timed_out = True
    except Exception:
        files = []
    finally:
        if _use_alarm:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, _prev)

    lat = (time.perf_counter() - _ts) * 1000.0
    if timed_out:
        print(f"[timeout] {prefix} {q!r} {lat:.0f}ms", file=sys.stderr, flush=True)
    elif lat > 500:
        print(f"[slow] {lat:.0f}ms [{prefix}] {q!r}", file=sys.stderr, flush=True)
    return prefix, q, files, lat


filecache = {}
latencies: list[float] = []
repo_latencies: dict[str, list[float]] = {}
_done = 0

# ── Prewarm zoekt webservers in the PARENT (before fork) ──────────────────────
# Zoekt host search is webserver-only (no CLI fallback) and the hot query path
# never blocks on startup, so each repo's webserver must be live and searchable
# *before* the timed loop -- otherwise early queries get empty zoekt results and
# MRR drops.  Warm sequentially (not in parallel) so indexes mmap one at a time
# instead of an I/O storm that stalls every server past its readiness timeout.
# The forked worker inherits these ready servers and queries them over HTTP
# (ZoektServer tags the owner pid so the child never kills the parent's server).
if CHANNEL in ("zoekt", "lexical+zoekt") and get_zoekt_supervisor is not None:
    _wt0 = time.perf_counter()
    _wready = 0
    for _prefix in list(uq):
        _eng = engines.get(_prefix)
        if _eng is None:
            continue
        try:
            _srv = get_zoekt_supervisor(_eng.repo_root).server
            if _srv.wait_until_searchable(30.0):
                _wready += 1
        except Exception as _e:
            print(f"[zoekt-warm] {_prefix} failed: {_e!r}", file=sys.stderr, flush=True)
    print(
        f"[zoekt-warm] {_wready}/{len(uq)} webservers searchable in {time.perf_counter() - _wt0:.1f}s",
        file=sys.stderr,
        flush=True,
    )

# Pre-warm ANN matrices in the MAIN process before forking workers.
# Linux COW: workers share the physical pages as long as they only read
# (matrix @ query_vec is read-only) -- actual RAM = 1 copy, not N_WORKERS copies.
# Engines with > _ANN_VECTOR_CAP vectors are excluded from pre-warm AND have their
# semantic ranker nulled out, so workers never trigger a matrix load (OOM guard).
if "semantic" in CHANNEL:
    import sqlite3 as _sq

    from atelier.infra.embeddings.null_embedder import NullEmbedder as _NullEmb

    _ann_t0 = time.perf_counter()
    print(f"{_TAG} pre-warming ANN matrices…", file=sys.stderr, flush=True)
    _ANN_VECTOR_CAP = 200_000  # skip pre-warm for repos with too many vectors (avoids 7.5GB linux matrix)
    for _prefix, _eng in engines.items():
        _vec_cnt = 0
        try:
            with _sq.connect(_eng.db_path) as _c:
                _vec_cnt = _c.execute("SELECT COUNT(*) FROM symbol_vectors").fetchone()[0]
        except Exception:
            pass
        if _vec_cnt > _ANN_VECTOR_CAP:
            # Null the embedder so _semantic_ranker.available -> False: a store this
            # large uses the chunked streaming path (~2s/query), too slow to sweep
            # across the whole gold set. Excluding it keeps the benchmark fast; the
            # blob store means it would no longer OOM if you did include it.
            _eng._semantic_ranker.embedder = _NullEmb()
            print(
                f"  [ann-warm] {_prefix} DISABLED semantic ({_vec_cnt:,} vectors > {_ANN_VECTOR_CAP:,} cap)",
                file=sys.stderr,
                flush=True,
            )
            continue
        try:
            _eng.prewarm_semantic_matrix()  # loads matrix into the cross-call cache
            print(f"  [ann-warm] {_prefix} warmed", file=sys.stderr, flush=True)
        except Exception as _e:
            print(f"  [ann-warm] {_prefix} SKIP: {_e}", file=sys.stderr, flush=True)
    print(
        f"{_TAG} ANN warm done in {time.perf_counter() - _ann_t0:.1f}s",
        file=sys.stderr,
        flush=True,
    )

print(f"{_TAG} start: {_total} explores across {len(uq)} repos, {_WORKERS} workers", file=sys.stderr, flush=True)
# Process pool, not threads: the ranking pipeline is CPU-bound and GIL-serialized
# under threads (~1 core, ~7x slower). Fork inherits the parent's pre-warmed
# engines + ANN matrices copy-on-write (1 physical copy, read-only matmul), and
# _worker_init rebuilds the inner channel executors that fork leaves broken, so
# the semantic matrices no longer OOM or deadlock the pool.
with ProcessPoolExecutor(
    max_workers=_WORKERS,
    mp_context=multiprocessing.get_context("fork"),
    initializer=_worker_init,
) as _ex:
    _t0 = time.perf_counter()
    for prefix, q, files, lat_ms in _ex.map(_run_explore, _tasks, chunksize=1):
        filecache[(prefix, q)] = files
        latencies.append(lat_ms)
        repo_latencies.setdefault(prefix, []).append(lat_ms)
        _done += 1
        if _done % 20 == 0 or _done == _total:
            _el = time.perf_counter() - _t0
            _rate = _done / _el if _el else 0.0
            _eta = (_total - _done) / _rate if _rate else 0.0
            print(
                f"{_TAG} {_done}/{_total} elapsed={_el:.0f}s rate={_rate:.1f}/s eta={_eta:.0f}s",
                file=sys.stderr,
                flush=True,
            )


def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int((p / 100.0) * (len(s) - 1)))]


def _repo_lat(p):
    return {
        "mean": round(sum(repo_latencies.get(p, [0])) / max(len(repo_latencies.get(p, [1])), 1), 1),
        "p50": round(_pct(repo_latencies.get(p, [0]), 50), 1),
        "p95": round(_pct(repo_latencies.get(p, [0]), 95), 1),
        "max": round(max(repo_latencies.get(p, [0])), 1),
        "over_100ms": sum(1 for x in repo_latencies.get(p, []) if x > 100.0),
    }


def _score_gold(gpairs, gtm):
    agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
    by_repo = {}
    for q, tid, prefix in gpairs:
        if q not in runset.get(prefix, ()):
            continue
        trues = gtm.get(tid)
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
    return {
        "mrr": round(agg["rr"] / max(agg["n"], 1), 4),
        "hit1": round(agg["h1"] / max(agg["n"], 1), 4),
        "hit3": round(agg["h3"] / max(agg["n"], 1), 4),
        "n": agg["n"],
        "by_repo": {
            p: {
                "mrr": round(d["rr"] / max(d["n"], 1), 4),
                "hit1": round(d["h1"] / max(d["n"], 1), 4),
                "hit3": round(d["h3"] / max(d["n"], 1), 4),
                "n": d["n"],
                "latency_ms": _repo_lat(p),
            }
            for p, d in sorted(by_repo.items())
        },
    }


_lat = {
    "mean": round(sum(latencies) / max(len(latencies), 1), 1),
    "p50": round(_pct(latencies, 50), 1),
    "p95": round(_pct(latencies, 95), 1),
    "max": round(max(latencies), 1) if latencies else 0.0,
    "over_100ms": sum(1 for x in latencies if x > 100.0),
}
_gold_scores = {kind: _score_gold(gp, gtm) for kind, gp, gtm in _golds}
# Top-level fields mirror the first gold (back-compat for the summary/history
# code); out["golds"] carries every gold scored this run.
out = {**_gold_scores[_golds[0][0]], "latency_ms": _lat, "golds": _gold_scores}
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
_base_mode = "full" if _args.full else (f"sample={_args.sample}" if _args.sample else "default")
_mode = f"{_base_mode}[{CHANNEL}]"
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
    "golds": out["golds"],
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
for _gk, _gs in (_cur.get("golds") or {_gold_kind: _cur}).items():
    print(
        f"  gold={_gk:<18} MRR {_gs['mrr']:.4f}   hit@1 {_gs['hit1']:.4f}   hit@3 {_gs['hit3']:.4f}   n={_gs['n']}",
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
_golds_data = _cur.get("golds") or {}
if _by:
    print("", file=sys.stderr)
    # sort: worst primary-gold MRR first so problems are visible
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
        # Build def/con MRR string
        _mrr_parts = []
        for _gk in ("definition", "content"):
            _gk_repo = (_golds_data.get(_gk) or {}).get("by_repo", {}).get(_rname)
            if _gk_repo and isinstance(_gk_repo, dict):
                _mrr_parts.append(f"{_gk_repo['mrr']:.3f}")
        _mrr_str = "/".join(_mrr_parts) if len(_mrr_parts) > 1 else f"{_rm:.3f}"
        print(
            f"  {_mrr_icon(_rm)}  {_short:<22}  n={_rn:<4}  MRR={_mrr_str}{_lat_note}",
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
