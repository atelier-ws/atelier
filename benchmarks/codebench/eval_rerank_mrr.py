"""Offline cross-encoder reranking MRR: does reranking the candidate pool lift
MRR/hit@1 over the shipped fused explore order?

For each gold (query, gold-file) pair:
  1. Run the shipped ``tool_explore`` to get the top-``--pool`` candidate files
     (the RETRIEVAL pool -- reranking can only reorder this, never add to it).
  2. Render each candidate file to a passage (its top definition symbols, the
     same text the embedder indexed), cap length.
  3. Re-score every (query, passage) with the BGE cross-encoder and reorder.
  4. Score rank-of-gold-file (endswith match, top-10) for THREE orders:
       explore   -- the shipped fused order (baseline)
       reranked  -- cross-encoder order
       recall    -- gold anywhere in the pool (the reranking CEILING)

Needs torch + sentence_transformers (GPU strongly preferred). Query embeddings
for the explore arm come from the persistent cache, so only the reranker needs
the GPU.

Run:
    uv run python benchmarks/codebench/eval_rerank_mrr.py \
        --pairs benchmarks/codebench/data/bench_pairs_semantic_gold.json \
        --pool 25 --sample 100 [--repo sympy] [--model BAAI/bge-reranker-v2-m3]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
os.environ.setdefault("ATELIER_CODE_EMBEDDER", "bge")
from atelier.core.capabilities.code_context.embedding import render_embedding_text
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.embeddings.reranker import BgeReranker

_DEFINITION_KINDS = {"function", "method", "class"}


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/")


def _rank(files: list[str], trues: list[str]) -> int | None:
    tn = [_norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(_norm(f).endswith(t) for t in tn):
            return i
    return None


def _passage(eng: CodeContextEngine, file_path: str, max_chars: int) -> str:
    """Render a candidate file to reranker text: its top definition symbols
    (name/signature/docstring), matching what the embedder indexed."""
    syms = [s for s in eng._symbols_for_files([file_path], limit=40) if (s.kind or "").lower() in _DEFINITION_KINDS]
    parts: list[str] = [file_path]
    for s in syms[:6]:
        src = None
        try:
            src = eng._read_file_slice(s.file_path, s.start_byte, s.end_byte)[:600]
        except Exception:
            src = None
        parts.append(render_embedding_text(s, source_text=src))
        if sum(len(p) for p in parts) > max_chars:
            break
    return "\n".join(parts)[:max_chars]


def _agg() -> dict:
    return {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}


def _add(d: dict, rank: int | None) -> None:
    d["n"] += 1
    if rank:
        d["rr"] += 1.0 / rank
        d["h1"] += int(rank == 1)
        d["h3"] += int(rank <= 3)


def _fmt(d: dict) -> str:
    n = max(d["n"], 1)
    return f"MRR={d['rr'] / n:.4f}  hit@1={d['h1'] / n:.4f}  hit@3={d['h3'] / n:.4f}  n={d['n']}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="benchmarks/codebench/data/bench_pairs_semantic_gold.json")
    ap.add_argument("--repo", default="")
    ap.add_argument("--sample", type=int, default=0, help="max queries per repo (0 = all)")
    ap.add_argument("--pool", type=int, default=25, help="candidate files retrieved before rerank")
    ap.add_argument("--max-chars", type=int, default=1500, help="passage length cap per candidate")
    ap.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
    args = ap.parse_args()

    with open(args.pairs) as fh:
        data = json.load(fh)
    pairs, true_map, repos = data["pairs"], data["true_map"], data["repos"]

    reranker = BgeReranker(args.model)
    if not BgeReranker.is_available():
        print("[rerank] ERROR: torch/sentence_transformers unavailable", file=sys.stderr)
        return 1

    uq: dict[str, list[str]] = {}
    for q, _tid, prefix in pairs:
        if args.repo and args.repo not in prefix:
            continue
        if prefix in repos and repos[prefix].get("db") and os.path.isfile(repos[prefix]["db"]):
            uq.setdefault(prefix, [])
            if q not in uq[prefix]:
                uq[prefix].append(q)
    if args.sample:
        uq = {p: qs[: args.sample] for p, qs in uq.items()}

    explore_agg, rerank_agg, recall_agg = _agg(), _agg(), _agg()
    by_repo: dict[str, dict] = {}
    t0 = time.perf_counter()
    n_done = 0
    for prefix in sorted(uq):
        meta = repos[prefix]
        eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
        eng._schema_ready = True
        eng._cache_get = lambda *a, **k: (False, None)
        eng._cache_set = lambda *a, **k: None
        with __import__("contextlib").suppress(Exception):
            eng.prewarm_semantic_matrix()
        br = by_repo.setdefault(prefix, {"explore": _agg(), "rerank": _agg(), "recall": _agg()})
        # map query -> its gold trues (first matching pair)
        qtrues = {}
        for q, tid, p in pairs:
            if p == prefix and q in uq.get(prefix, ()) and q not in qtrues:
                qtrues[q] = true_map.get(tid) or []
        for q in uq[prefix]:
            trues = qtrues.get(q) or []
            if not trues:
                continue
            # Shipped explore order (baseline, top-10 -- internally capped at 8 files).
            r = eng.tool_explore(q, max_files=10, auto_index=False)
            explore_files = [f.get("path", "") for f in r.get("files", [])][:10]
            # Widen the RERANK pool with the semantic recall tail (top files by cosine):
            # explore caps at 8, so without this the reranker has no headroom. Pool =
            # explore files first, then semantic-only files, deduped, up to --pool.
            sem_files: list[str] = []
            for h in eng._search_symbols_semantic_ann(q, limit=200):
                if h.file_path not in sem_files:
                    sem_files.append(h.file_path)
                if len(sem_files) >= args.pool:
                    break
            pool = list(dict.fromkeys(explore_files + sem_files))[: args.pool]
            if not pool:
                continue
            passages = [_passage(eng, f, args.max_chars) for f in pool]
            scores = reranker.rerank(q, passages)
            reranked = [pool[i] for i in sorted(range(len(pool)), key=lambda i: -scores[i])]
            er, rr = _rank(explore_files[:10], trues), _rank(reranked[:10], trues)
            rc = _rank(pool, trues)  # gold anywhere in pool = recall ceiling
            for agg, br_a, rk in (
                (explore_agg, br["explore"], er),
                (rerank_agg, br["rerank"], rr),
                (recall_agg, br["recall"], rc),
            ):
                _add(agg, rk)
                _add(br_a, rk)
            n_done += 1
            if n_done % 50 == 0:
                print(f"[rerank] {n_done} q  {n_done / (time.perf_counter() - t0):.1f}/s", file=sys.stderr, flush=True)
        print(
            f"[rerank] {prefix:26} explore={_fmt(br['explore'])}  rerank={_fmt(br['rerank'])}",
            file=sys.stderr,
            flush=True,
        )

    print(
        json.dumps(
            {
                "explore": {
                    "mrr": round(explore_agg["rr"] / max(explore_agg["n"], 1), 4),
                    "hit1": round(explore_agg["h1"] / max(explore_agg["n"], 1), 4),
                    "n": explore_agg["n"],
                },
                "reranked": {
                    "mrr": round(rerank_agg["rr"] / max(rerank_agg["n"], 1), 4),
                    "hit1": round(rerank_agg["h1"] / max(rerank_agg["n"], 1), 4),
                    "n": rerank_agg["n"],
                },
                "recall_ceiling": {
                    "mrr": round(recall_agg["rr"] / max(recall_agg["n"], 1), 4),
                    "hit1": round(recall_agg["h1"] / max(recall_agg["n"], 1), 4),
                    "n": recall_agg["n"],
                },
                "pool": args.pool,
                "model": args.model,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
