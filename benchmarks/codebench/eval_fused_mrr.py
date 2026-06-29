"""Fused retrieval MRR: lexical+zoekt (tool_explore) vs semantic (symbol_vectors)
vs RRF-fused -- apples-to-apples with fitness_explore_mrr.py.

The "measure the semantic ceiling first" probe. For each mined (query, gold-file)
pair it computes THREE file rankings and scores rank-of-gold-file exactly like
fitness_explore_mrr.py (endswith match, top-10):

  * lexzoekt : engine.tool_explore() -- the shipped lexical+zoekt fusion, UNCHANGED
                (this arm reproduces the published baseline; no engine edit).
  * semantic : cosine over the prebuilt per-symbol BGE vectors (symbol_vectors),
                projected symbol->file (best symbol rank wins the file).
  * fused    : file-level weighted RRF of the two rankings (engine defaults k=60,
                w_lex=w_sem=1.0; all tunable).

Semantic lift = fused.mrr - lexzoekt.mrr.

Single process by design: one shared BGE model on the GPU, queries embedded in
one batch per repo. (A fork pool would reload the 1.5B model per worker and OOM
the 24 GB card; the explore arm is cheap enough sequentially.) Only repos whose
DB already carries bge:BAAI/bge-code-v1 vectors are scored -- others are reported
as skipped so every arm sees the same query set.

Run:
    uv run --no-sync python benchmarks/codebench/eval_fused_mrr.py [--sample 600] \
        [--repo django] [--rrf-k 60] [--w-lex 1.0] [--w-sem 1.0] [--sem-symbols 50]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.embeddings.bge import BgeEmbedder

WANT_NAME = "bge:BAAI/bge-code-v1"
WANT_DIM = 1536


def _on_alarm(signum: int, frame: object) -> None:
    raise TimeoutError


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def _dedup(files: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        f = _norm(f)
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _rank_true(files: list[str], trues: list[str]) -> int | None:
    tn = [_norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(_norm(f).endswith(t) for t in tn):
            return i
    return None


def _vec_dbs_for(main_db: str) -> list[str]:
    """Candidate DB files that may hold this repo's bge vectors.

    symbol_vectors lands in the MAIN db for the originally-provisioned repos, but
    in the engine's attached `vectors` db (db_path.parent/vectors.sqlite -- shared
    /tmp/vectors.sqlite for the bench /tmp dbs) for repos embedded via the engine
    path. Search both, keyed by repo_id, so the arm sees vectors wherever they are.
    """
    cands = [main_db, str(Path(main_db).parent / "vectors.sqlite")]
    seen: set[str] = set()
    return [c for c in cands if os.path.isfile(c) and not (c in seen or seen.add(c))]


def _load_repo_vectors(main_db: str, repo_id: str) -> tuple[list[str], np.ndarray, dict[str, str]]:
    """Return (symbol_ids, matrix[n,dim] float32, symbol_id->file_path) for bge vectors."""
    conn = sqlite3.connect(f"file:{main_db}?mode=ro", uri=True)
    file_of = {r[0]: r[1] for r in conn.execute("SELECT symbol_id, file_path FROM symbols")}
    conn.close()
    ids: list[str] = []
    vecs: list[list[float]] = []
    for vdb in _vec_dbs_for(main_db):
        c = sqlite3.connect(f"file:{vdb}?mode=ro", uri=True)
        try:
            rows = c.execute(
                "SELECT symbol_id, vector_json FROM symbol_vectors "
                "WHERE repo_id=? AND embedder_name=? AND embedding_dim=?",
                (repo_id, WANT_NAME, WANT_DIM),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        c.close()
        if rows:
            for sid, vj in rows:
                if sid in file_of:
                    ids.append(sid)
                    vecs.append(json.loads(vj))
            break  # first db that has this repo_id wins
    matrix = np.asarray(vecs, dtype=np.float32) if vecs else np.zeros((0, WANT_DIM), np.float32)
    return ids, matrix, file_of


def _semantic_files(qv: np.ndarray, ids: list[str], matrix: np.ndarray, file_of: dict[str, str], k: int) -> list[str]:
    if matrix.shape[0] == 0:
        return []
    scores = matrix @ qv
    order = np.argsort(-scores)
    out: list[str] = []
    seen: set[str] = set()
    for i in order:
        f = _norm(file_of.get(ids[int(i)], ""))
        if f and f not in seen:
            seen.add(f)
            out.append(f)
        if len(out) >= k:
            break
    return out


def _rrf(rankings: list[tuple[list[str], float]], k: float, limit: int) -> list[str]:
    """Weighted reciprocal-rank fusion over file-path lists. rankings = [(files, weight)]."""
    score: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    for files, w in rankings:
        for rank, f in enumerate(files, 1):
            score[f] = score.get(f, 0.0) + w / (k + rank)
            if f not in best_rank or rank < best_rank[f]:
                best_rank[f] = rank
    return sorted(score, key=lambda f: (-score[f], best_rank[f], f))[:limit]


def _qbucket(q: str) -> str:
    """Query shape: the gate signal. single-token & alternation are exact-lexical's
    turf; multiword (composite/NL) is where semantic can complement."""
    if "|" in q:
        return "alternation"
    if " " not in q.strip():
        return "single-token"
    return "multiword"


def _agg() -> dict:
    return {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}


def _add(d: dict, rank: int | None) -> None:
    d["n"] += 1
    if rank:
        d["rr"] += 1.0 / rank
        d["h1"] += int(rank == 1)
        d["h3"] += int(rank <= 3)


def _mrr(d: dict) -> dict:
    n = max(d["n"], 1)
    return {"mrr": round(d["rr"] / n, 4), "hit1": round(d["h1"] / n, 4), "hit3": round(d["h3"] / n, 4), "n": d["n"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="benchmarks/codebench/data/bench_pairs_def_gold.json")
    ap.add_argument("--repo", default="", help="only repos whose prefix contains this substring")
    ap.add_argument("--sample", type=int, default=0, help="max unique queries per repo (0 = all)")
    ap.add_argument("--max-files", type=int, default=10)
    ap.add_argument("--sem-symbols", type=int, default=50, help="symbol depth before file projection")
    ap.add_argument("--rrf-k", type=float, default=60.0)
    ap.add_argument("--w-lex", type=float, default=1.0)
    ap.add_argument("--w-sem", type=float, default=1.0)
    ap.add_argument("--model", default="BAAI/bge-code-v1", help="HF model id or local path (finetuned dir)")
    ap.add_argument(
        "--no-explore",
        action="store_true",
        help="skip tool_explore (lexical arm); fast path to compare the semantic arm only",
    )
    ap.add_argument(
        "--sweep", default="",
        help="comma-sep w_sem values fused+scored in ONE explore pass (e.g. 1.0,0.5,0.3,0.2,0.1)",
    )
    ap.add_argument("--explore-timeout", type=float, default=5.0,
                    help="per-query tool_explore timeout (s); a slow/hanging query yields empty lex, like fitness")
    args = ap.parse_args()
    global WANT_NAME
    WANT_NAME = f"bge:{args.model}"  # match the N5 stamp of the vectors built with this model

    with open(args.pairs) as fh:
        data = json.load(fh)
    pairs, true_map, repos = data["pairs"], data["true_map"], data["repos"]

    # Candidate repos = db + ws present (vectors presence is checked per-repo below,
    # since they may live in the main db OR the shared vectors.sqlite).
    candidates: dict[str, dict] = {}
    skipped: list[str] = []
    for prefix, meta in sorted(repos.items()):
        if args.repo and args.repo not in prefix:
            continue
        db = meta.get("db")
        ws = meta.get("ws")
        if not db or not ws or not os.path.isfile(db) or not os.path.isdir(ws):
            skipped.append(prefix)
            continue
        candidates[prefix] = meta
    if not candidates:
        print(json.dumps({"error": "no candidate repos", "skipped": skipped}))
        return 1

    uq: dict[str, list[str]] = {}
    for q, _tid, prefix in pairs:
        if prefix in candidates:
            uq.setdefault(prefix, [])
            if q not in uq[prefix]:
                uq[prefix].append(q)
    if args.sample:
        uq = {p: sorted(qs)[: args.sample] for p, qs in uq.items()}
    runset = {p: set(qs) for p, qs in uq.items()}

    print(f"[fused] loading {WANT_NAME} on GPU ...", file=sys.stderr, flush=True)
    t0 = time.perf_counter()
    model = BgeEmbedder(args.model)
    model.embed(["warmup"])
    print(f"[fused] model ready in {time.perf_counter() - t0:.1f}s", file=sys.stderr, flush=True)

    # rankings[(prefix, q)] = {"lex": [...], "sem": [...], "fused": [...]}
    rankings: dict[tuple[str, str], dict[str, list[str]]] = {}
    for prefix in sorted(uq):
        meta = candidates[prefix]
        queries = uq[prefix]
        eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
        eng._cache_get = lambda *a, **k: (False, None)
        eng._cache_set = lambda *a, **k: None
        eng._schema_ready = True
        ids, matrix, file_of = _load_repo_vectors(meta["db"], eng.repo_id)
        if matrix.shape[0] == 0:
            skipped.append(prefix)
            runset.pop(prefix, None)
            print(f"[fused] {prefix:28s} no bge vectors -> skip", file=sys.stderr, flush=True)
            continue
        t1 = time.perf_counter()
        qmat = np.asarray(model.embed_queries(queries), dtype=np.float32)  # one GPU batch / repo
        for qi, q in enumerate(queries):
            sem = _semantic_files(qmat[qi], ids, matrix, file_of, args.sem_symbols)
            lex: list[str] = []
            if not args.no_explore:
                prev = signal.signal(signal.SIGALRM, _on_alarm)
                signal.setitimer(signal.ITIMER_REAL, args.explore_timeout)
                try:
                    r = eng.tool_explore(
                        q,
                        max_files=args.max_files,
                        auto_index=False,
                        include_source=False,
                        include_relationships=False,
                    )
                    lex = _dedup([f.get("path", "") for f in r.get("files", [])])
                except Exception:  # noqa: BLE001 -- timeout or explore error -> empty lex (miss), continue
                    lex = []
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, prev)
            fused = _rrf([(lex, args.w_lex), (sem[: args.max_files], args.w_sem)], args.rrf_k, args.max_files)
            rankings[(prefix, q)] = {
                "lex": lex[: args.max_files],
                "sem": sem[: args.max_files],
                "fused": fused,
            }
        print(
            f"[fused] {prefix:28s} {len(queries):4d} q  vecs={matrix.shape[0]:6d}  ({time.perf_counter() - t1:.1f}s)",
            file=sys.stderr,
            flush=True,
        )

    list_arms = ("lex", "sem", "fused")
    all_arms = ("lex", "sem", "fused", "oracle")
    agg = {a: _agg() for a in all_arms}
    by_repo: dict[str, dict] = {}
    rescued = 0  # gold missed by lex top-10 but found by sem top-3
    sweep_w = [float(x) for x in args.sweep.split(",") if x.strip()]
    sweep_agg = {w: _agg() for w in sweep_w}
    # shape-gated fusion: fuse semantic only where it helps; lexical-only elsewhere.
    gated_agg = {"gate_multiword": _agg(), "gate_nonsingle": _agg()}
    by_bucket: dict[str, dict] = {}
    for q, tid, prefix in pairs:
        if q not in runset.get(prefix, ()):
            continue
        trues = true_map.get(tid)
        if not trues:
            continue
        rk = rankings.get((prefix, q))
        if rk is None:
            continue
        br = by_repo.setdefault(prefix, {a: _agg() for a in all_arms})
        ranks = {}
        for a in list_arms:
            ranks[a] = _rank_true(rk[a], trues)
            _add(agg[a], ranks[a])
            _add(br[a], ranks[a])
        # oracle = best achievable from lex+sem (upper bound a perfect fuser could reach)
        cand = [r for r in (ranks["lex"], ranks["sem"]) if r]
        orank = min(cand) if cand else None
        _add(agg["oracle"], orank)
        _add(br["oracle"], orank)
        if not ranks["lex"] and ranks["sem"] and ranks["sem"] <= 3:
            rescued += 1
        # weight sweep: re-fuse the SAME lex+sem rankings at each w_sem (no re-explore)
        for w in sweep_w:
            fr = _rrf([(rk["lex"], args.w_lex), (rk["sem"], w)], args.rrf_k, args.max_files)
            _add(sweep_agg[w], _rank_true(fr, trues))
        # shape-gated fusion (uses the already-computed equal-weight fused ranking)
        bk = _qbucket(q)
        _add(gated_agg["gate_multiword"], _rank_true(rk["fused"] if bk == "multiword" else rk["lex"], trues))
        _add(gated_agg["gate_nonsingle"], _rank_true(rk["lex"] if bk == "single-token" else rk["fused"], trues))
        bb = by_bucket.setdefault(bk, {a: _agg() for a in ("lex", "sem", "fused")})
        for a in ("lex", "sem", "fused"):
            _add(bb[a], ranks[a])

    out = {
        "lexzoekt": _mrr(agg["lex"]),
        "semantic": _mrr(agg["sem"]),
        "fused": _mrr(agg["fused"]),
        "oracle": _mrr(agg["oracle"]),
        "lift_mrr": round(_mrr(agg["fused"])["mrr"] - _mrr(agg["lex"])["mrr"], 4),
        "oracle_ceiling_mrr": round(_mrr(agg["oracle"])["mrr"] - _mrr(agg["lex"])["mrr"], 4),
        "gate_multiword": _mrr(gated_agg["gate_multiword"]),
        "gate_nonsingle": _mrr(gated_agg["gate_nonsingle"]),
        "gate_multiword_lift": round(_mrr(gated_agg["gate_multiword"])["mrr"] - _mrr(agg["lex"])["mrr"], 4),
        "gate_nonsingle_lift": round(_mrr(gated_agg["gate_nonsingle"])["mrr"] - _mrr(agg["lex"])["mrr"], 4),
        "by_bucket": {bk: {a: _mrr(v[a]) for a in ("lex", "sem", "fused")} for bk, v in sorted(by_bucket.items())},
        "sweep": [
            {
                "w_sem": w,
                "fused_mrr": _mrr(sweep_agg[w])["mrr"],
                "lift": round(_mrr(sweep_agg[w])["mrr"] - _mrr(agg["lex"])["mrr"], 4),
            }
            for w in sweep_w
        ],
        "sem_rescued_gold": rescued,
        "params": {"rrf_k": args.rrf_k, "w_lex": args.w_lex, "w_sem": args.w_sem, "sem_symbols": args.sem_symbols},
        "by_repo": {p: {a: _mrr(d[a]) for a in all_arms} for p, d in sorted(by_repo.items())},
        "skipped": skipped,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
