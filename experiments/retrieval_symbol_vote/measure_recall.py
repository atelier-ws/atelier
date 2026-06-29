"""Measure V6 retrieval recall@K over the benchmark pairs (the reranking ceiling).

Reranking can only reorder already-retrieved candidates, so recall@K — how often
the gold file appears in explore's top-K — is the hard ceiling on what any
reranker can achieve. This runs explore at depth 50 with the reranker disabled
and buckets the rank of the gold file.

Run:
  PYTHONPATH=src uv run python experiments/retrieval_symbol_vote/measure_recall.py --full
"""

from __future__ import annotations

import argparse
import contextlib
import json
import multiprocessing
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, "src")
os.environ.setdefault("ATELIER_EXPLORE_RERANKER_ENABLED", "0")  # measure raw retrieval

from atelier.core.capabilities.code_context.engine import CodeContextEngine

try:
    from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
except Exception:  # noqa: BLE001
    get_zoekt_supervisor = None

_KS = [1, 3, 5, 10, 20, 50]

_parser = argparse.ArgumentParser(description="V6 retrieval recall@K")
_parser.add_argument("--full", action="store_true", help="All pairs (no cap).")
_parser.add_argument("--sample", type=int, default=None, metavar="N", help="Cap total queries across repos.")
_parser.add_argument("--repo", default="", help="Filter to repos whose prefix contains this substring.")
_parser.add_argument("--depth", type=int, default=50, help="Candidate depth to retrieve (max recall@K).")
_parser.add_argument(
    "--dump-missed", type=int, default=0, help="Print N missed (query -> gold) cases to find patterns."
)
_parser.add_argument(
    "--dump-lowrank", type=int, default=0, help="Print N cases (rank None or >3) with gold, rank, top retrieved."
)
_parser.add_argument(
    "--symbol-queries-only", action="store_true", help="Keep only clean single-symbol queries (drop NL/regex/content)."
)
_args = _parser.parse_args()
_DEPTH = max(_KS[-1], _args.depth)

with open(os.environ.get("FITNESS_PAIRS", "benchmarks/codebench/data/bench_pairs_multi.json")) as _fh:
    _data = json.load(_fh)
pairs = _data["pairs"]
true_map = _data["true_map"]
repos = _data["repos"]


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/")


engines: dict[str, CodeContextEngine] = {}
for _prefix, _meta in repos.items():
    if _args.repo and _args.repo not in _prefix:
        continue
    _db = Path(_meta["db"]) if _meta.get("db") else None
    _eng = CodeContextEngine(Path(_meta["ws"]), db_path=_db, autosync_enabled=False)
    _eng._cache_get = lambda *a, **k: (False, None)
    _eng._cache_set = lambda *a, **k: None
    _eng._schema_ready = True
    if get_zoekt_supervisor is not None:
        with contextlib.suppress(Exception):
            get_zoekt_supervisor(Path(_meta["ws"]))
    engines[_prefix] = _eng

uq: dict[str, list[str]] = {}
for _q, _tid, _prefix in pairs:
    if _args.repo and _args.repo not in _prefix:
        continue
    uq.setdefault(_prefix, [])
    if _q not in uq[_prefix]:
        uq[_prefix].append(_q)
if _args.symbol_queries_only:
    _clean = re.compile(r"^(?:def |class )?[A-Za-z_][A-Za-z0-9_]{2,}$")
    uq = {p: [q for q in qs if _clean.match(q)] for p, qs in uq.items()}
    uq = {p: qs for p, qs in uq.items() if qs}
if _args.full:
    pass
elif _args.sample:
    _per = max(1, _args.sample // max(len(uq), 1))
    uq = {p: sorted(qs)[:_per] for p, qs in uq.items()}
runset = {p: set(qs) for p, qs in uq.items()}

_WORKERS = int(os.environ.get("FITNESS_WORKERS", "0")) or max(1, min(16, (os.cpu_count() or 4) // 2))
_tasks = [(p, q) for p, qs in uq.items() for q in qs]


def _worker_init() -> None:
    import concurrent.futures as _cf

    import atelier.core.capabilities.code_context.engine as _eng_mod

    _eng_mod._SEARCH_CHANNEL_EXECUTOR.shutdown(wait=False)
    _eng_mod._SEARCH_CHANNEL_EXECUTOR = _cf.ThreadPoolExecutor(max_workers=16)
    for _eng in engines.values():
        with contextlib.suppress(Exception):
            _eng._symbol_centrality_map()


def _run(task: tuple[str, str]) -> tuple[str, str, list[str]]:
    prefix, q = task
    eng = engines.get(prefix)
    if eng is None:
        return prefix, q, []
    try:
        r = eng.tool_explore(q, max_files=_DEPTH, auto_index=False)
        files = [_norm(f.get("path", "")) for f in r.get("files", [])]
    except Exception:  # noqa: BLE001
        files = []
    return prefix, q, files


def _rank_true(files: list[str], trues: list[str]) -> int | None:
    tn = [_norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(_norm(f).endswith(t) for t in tn):
            return i
    return None


if get_zoekt_supervisor is not None:
    for _prefix in list(uq):
        _eng = engines.get(_prefix)
        with contextlib.suppress(Exception):
            get_zoekt_supervisor(_eng.repo_root).server.wait_until_searchable(30.0)

print(
    f"[recall] {len(_tasks)} queries across {len(uq)} repos, depth={_DEPTH}, workers={_WORKERS}",
    file=sys.stderr,
    flush=True,
)
_filecache: dict[tuple[str, str], list[str]] = {}
with ProcessPoolExecutor(
    max_workers=_WORKERS, mp_context=multiprocessing.get_context("fork"), initializer=_worker_init
) as _ex:
    _t0 = time.perf_counter()
    _done = 0
    for prefix, q, files in _ex.map(_run, _tasks, chunksize=1):
        _filecache[(prefix, q)] = files
        _done += 1
        if _done % 100 == 0 or _done == len(_tasks):
            print(f"[recall] {_done}/{len(_tasks)} {time.perf_counter() - _t0:.0f}s", file=sys.stderr, flush=True)


def _bucket() -> dict[str, int]:
    return {"n": 0, "missed": 0, **{f"r{k}": 0 for k in _KS}}


agg = _bucket()
by_repo: dict[str, dict[str, int]] = defaultdict(_bucket)
_missed: list[tuple[str, str, list[str]]] = []
_lowrank: list[tuple[str, int | None, list[str], list[str]]] = []
for q, tid, prefix in pairs:
    if q not in runset.get(prefix, ()):
        continue
    trues = true_map.get(tid)
    if not trues:
        continue
    rank = _rank_true(_filecache.get((prefix, q), []), trues)
    for d in (agg, by_repo[prefix]):
        d["n"] += 1
        if rank is None:
            d["missed"] += 1
        else:
            for k in _KS:
                if rank <= k:
                    d[f"r{k}"] += 1
    if rank is None and _args.dump_missed:
        _missed.append((prefix, q, trues))
    if _args.dump_lowrank and (rank is None or rank > 3):
        _lowrank.append((q, rank, trues, _filecache.get((prefix, q), [])[:5]))


def _fmt(d: dict[str, int]) -> str:
    n = max(d["n"], 1)
    cells = "  ".join(f"@{k}={d[f'r{k}'] / n:.3f}" for k in _KS)
    return f"n={d['n']:<4} {cells}  missed={d['missed'] / n:.3f}"


print("\n=== V6 retrieval recall@K (reranker OFF) ===")
print(f"OVERALL  {_fmt(agg)}")
print("\nby repo (sorted by recall@50, worst first):")
for prefix, d in sorted(by_repo.items(), key=lambda kv: kv[1][f"r{_KS[-1]}"] / max(kv[1]["n"], 1)):
    print(f"  {prefix.split('__')[-1]:<22} {_fmt(d)}")
if _args.dump_missed and _missed:
    print(f"\n=== {min(_args.dump_missed, len(_missed))} of {len(_missed)} MISSED (gold not in top-{_DEPTH}) ===")
    for prefix, q, trues in _missed[: _args.dump_missed]:
        print(f"  [{prefix.split('__')[-1]}] query={q!r}")
        print(f"      gold: {', '.join(trues)}")
if _args.dump_lowrank and _lowrank:
    print(f"\n=== {min(_args.dump_lowrank, len(_lowrank))} of {len(_lowrank)} LOW-RANK (rank None or >3) ===")
    for q, rank, trues, top in _lowrank[: _args.dump_lowrank]:
        print(f"  rank={rank} query={q!r}")
        print(f"      gold: {', '.join(trues)}")
        print(f"      got : {', '.join(top) or '(none)'}")
print(
    json.dumps(
        {
            "overall": {**{f"recall@{k}": round(agg[f"r{k}"] / max(agg["n"], 1), 4) for k in _KS}, "n": agg["n"]},
            "depth": _DEPTH,
        }
    )
)
