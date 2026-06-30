"""Quick MRR eval for NomicEmbedder on the def+content gold sets.

Mirrors fitness_explore_mrr.py but exercises the embedding layer directly
(no full engine, no Zoekt) — pure semantic retrieval quality from symbol
vectors.  Embeds all symbols from each repo's index DB once, then ranks
queries by cosine similarity against those vectors.

Usage:
    # full-precision 3584d
    ATELIER_CODE_EMBEDDER=nomic FITNESS_SAMPLE=30 uv run python benchmarks/codebench/eval_nomic_mrr.py

    # 768d Matryoshka (matches CMM's bundled int8 dim)
    ATELIER_CODE_EMBEDDER=nomic ATELIER_NOMIC_DIM=768 FITNESS_SAMPLE=30 \
        uv run python benchmarks/codebench/eval_nomic_mrr.py

    # compare against BGE-Code-v1
    ATELIER_CODE_EMBEDDER=bge FITNESS_SAMPLE=30 uv run python benchmarks/codebench/eval_nomic_mrr.py
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

GOLD_PATHS = [
    "benchmarks/codebench/data/bench_pairs_def_gold.json",
    "benchmarks/codebench/data/bench_pairs_content_gold.json",
]
SAMPLE = int(os.environ.get("FITNESS_SAMPLE", "30"))
EMBEDDER_PIN = os.environ.get("ATELIER_CODE_EMBEDDER", "nomic")

golds: list[tuple[str, list, dict]] = []
repos: dict | None = None
for gp in GOLD_PATHS:
    with open(gp) as f:
        d = json.load(f)
    if repos is None:
        repos = _d = d
        repos = d["repos"]
    golds.append((d.get("gold_kind", "definition"), d["pairs"], d["true_map"]))
assert repos is not None

pairs = [r for _, p, _ in golds for r in p]

uq: dict[str, set[str]] = {}
for q, _, prefix in pairs:
    uq.setdefault(prefix, set()).add(q)

if SAMPLE:
    per = max(1, SAMPLE // max(len(uq), 1))
    uq = {p: set(sorted(qs)[:per]) for p, qs in uq.items()}

from atelier.core.foundation.paths import workspace_key
from atelier.infra.embeddings.factory import make_code_embedder

embedder = make_code_embedder(pin=EMBEDDER_PIN)
print(f"[eval] embedder={embedder.name} dim={embedder.dim}", flush=True)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def norm_path(p: str) -> str:
    return (p or "").replace("\\", "/")


def rank_of_true(ranked: list[str], trues: list[str]) -> int | None:
    tn = [norm_path(t) for t in trues]
    for i, f in enumerate(ranked, 1):
        nf = norm_path(f)
        if any(nf.endswith(t) or t.endswith(nf) for t in tn):
            return i
    return None


results: dict[tuple[str, str], list[str]] = {}
t0 = time.time()

for prefix, queries in sorted(uq.items()):
    meta = repos[prefix]
    ws = Path(meta["ws"])
    if not ws.is_dir():
        print(f"[skip] {prefix}: {ws} not found", flush=True)
        continue

    db_path = Path("/tmp") / workspace_key(ws.resolve()) / "code_context.sqlite"
    if not db_path.exists():
        print(f"[skip] {prefix}: no DB at {db_path}", flush=True)
        continue

    print(f"[repo] {prefix} queries={len(queries)}", flush=True)

    con = sqlite3.connect(str(db_path))
    rows = con.execute(
        "SELECT file_path, symbol_name, kind, doc_summary FROM symbols "
        "WHERE file_path IS NOT NULL LIMIT 50000"
    ).fetchall()
    con.close()

    if not rows:
        print(f"[skip] {prefix}: no symbols in DB", flush=True)
        continue

    doc_texts = [f"{r[1]} {r[2]} {r[3] or ''}".strip() for r in rows]
    doc_paths = [norm_path(r[0]) for r in rows]

    t1 = time.time()
    doc_mat = np.array(embedder.embed_documents(doc_texts), dtype=np.float32)  # (N, dim)
    print(f"  embedded {len(doc_texts)} symbols in {time.time() - t1:.1f}s", flush=True)

    query_list = sorted(queries)
    t1 = time.time()
    q_mat = np.array(embedder.embed_queries(query_list), dtype=np.float32)    # (Q, dim)
    print(f"  embedded {len(query_list)} queries in {time.time() - t1:.3f}s", flush=True)

    # (Q, N) similarity matrix — single GPU/BLAS matmul
    sim = q_mat @ doc_mat.T

    for qi, query in enumerate(query_list):
        order = np.argsort(-sim[qi])  # descending
        seen: set[str] = set()
        ranked: list[str] = []
        for idx in order:
            p = doc_paths[int(idx)]
            if p not in seen:
                seen.add(p)
                ranked.append(p)
            if len(ranked) >= 10:
                break
        results[(prefix, query)] = ranked

print(f"\n[eval] {len(results)} queries done in {time.time() - t0:.1f}s", flush=True)

runset = {p: set(qs) for p, qs in uq.items()}


def score_gold(kind: str, gpairs: list, gtm: dict) -> dict:
    agg = {"rr": 0.0, "h1": 0, "h3": 0, "n": 0}
    by_repo: dict[str, dict] = {}
    for q, tid, prefix in gpairs:
        if q not in runset.get(prefix, set()):
            continue
        trues = [norm_path(p) for p in gtm.get(tid, []) if p]
        if not trues:
            continue
        ranked = results.get((prefix, q), [])
        r = rank_of_true(ranked, trues)
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
        "by_repo": {p: {"mrr": round(d["rr"] / max(d["n"], 1), 4), "n": d["n"]} for p, d in sorted(by_repo.items())},
    }


W = 60
print("\n" + "─" * W)
print(f"  embedder={embedder.name}")
for kind, gpairs, gtm in golds:
    s = score_gold(kind, gpairs, gtm)
    print(f"  gold={kind:<18} MRR {s['mrr']:.4f}  hit@1 {s['hit1']:.4f}  hit@3 {s['hit3']:.4f}  n={s['n']}")
    for rp, rd in sorted(s["by_repo"].items(), key=lambda kv: kv[1]["mrr"]):
        icon = "✓" if rd["mrr"] >= 0.9 else ("~" if rd["mrr"] >= 0.5 else "✗")
        short = rp.split("__")[-1] if "__" in rp else rp
        print(f"    {icon}  {short:<22} n={rd['n']:<4} MRR={rd['mrr']:.3f}")
print("─" * W)
