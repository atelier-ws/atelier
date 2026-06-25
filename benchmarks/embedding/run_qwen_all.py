"""Run Qwen3-Embedding-8B for all 6 repos via Ollama API.

Corpus and queries must already exist from BGE runs.
Saves results_<repo>.json with qwen key filled.
"""
from __future__ import annotations

import json
import math
import pathlib
import statistics
import time

import numpy as np
import requests as req

REPOS = ["django", "pytest", "astropy", "sympy", "scikit-learn", "xarray"]
OUT_DIR = pathlib.Path("/home/pankaj/Projects/leanchain/atelier/benchmarks/embedding/data/multi_repo")
OLLAMA_URL = "http://localhost:11434/api/embed"


def log(msg):
    print(msg, flush=True)


def qwen_embed(texts):
    r = req.post(OLLAMA_URL, json={"model": "qwen3-embedding:8b", "input": texts}, timeout=1800)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)


def evaluate(corpus_vecs, queries, cid):
    hits = {1: [], 5: [], 10: []}
    rrs = []
    nds = []
    for q in queries:
        rel = set(q["relevant"])
        q_text = f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q['query']}"
        qv = qwen_embed([q_text])
        ranked = [cid[i] for i in np.argsort(-(corpus_vecs @ qv[0]))]
        for k in hits:
            topk = set(ranked[:k])
            hits[k].append(float(bool(topk & rel)))
        for r, rid in enumerate(ranked[:10], 1):
            if rid in rel:
                rrs.append(1.0 / r)
                break
        else:
            rrs.append(0.0)
        gains = [1 if rid in rel else 0 for rid in ranked[:10]]
        ideal_len = min(10, len(rel))
        d = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
        id_ = sum(1 / math.log2(i + 2) for i in range(ideal_len))
        nds.append(d / id_ if id_ else 0.0)
    return {
        "hit@1": statistics.mean(hits[1]),
        "hit@5": statistics.mean(hits[5]),
        "hit@10": statistics.mean(hits[10]),
        "mrr@10": statistics.mean(rrs),
        "ndcg@10": statistics.mean(nds),
    }


def main():
    for repo in REPOS:
        results_path = OUT_DIR / f"results_{repo}.json"
        if results_path.exists():
            existing = json.load(open(results_path))
            if "qwen" in existing and "error" not in existing.get("qwen", {}):
                log(f"{repo}: Qwen already done, skipping")
                continue

        corpus_path = OUT_DIR / f"corpus_{repo}.jsonl"
        queries_path = OUT_DIR / f"queries_{repo}.jsonl"
        if not corpus_path.exists():
            log(f"{repo}: no corpus, skipping")
            continue

        chunks = [json.loads(l) for l in open(corpus_path) if l.strip()]
        queries = [json.loads(l) for l in open(queries_path) if l.strip()]
        eval_queries = queries[:200]
        cid = [c["id"] for c in chunks]
        corp_texts = [c["text"] for c in chunks]

        log(f"\n─── {repo} ({len(chunks)} chunks, {len(eval_queries)} queries) ───")

        # Embed corpus with Qwen
        qwen_path = OUT_DIR / f"emb_qwen_{repo}.npy"
        if qwen_path.exists():
            log("  Loading cached Qwen embeddings...")
            corpus_qwen = np.load(qwen_path)
        else:
            log("  Embedding corpus with Qwen3...")
            t0 = time.time()
            try:
                corpus_qwen = qwen_embed(corp_texts)
                log(f"    Done: {corpus_qwen.shape}, {time.time()-t0:.1f}s")
                np.save(qwen_path, corpus_qwen)
            except Exception as e:
                log(f"    FAILED: {e}")
                result = json.load(open(results_path)) if results_path.exists() else {}
                result["qwen"] = {"error": str(e)}
                json.dump(result, open(results_path, "w"), indent=2)
                continue

        # Evaluate
        log(f"  Evaluating Qwen on {len(eval_queries)} queries...")
        t0 = time.time()
        try:
            res = evaluate(corpus_qwen, eval_queries, cid)
            log(f"    hit@1={res['hit@1']:.2%}  hit@5={res['hit@5']:.2%}  hit@10={res['hit@10']:.2%}  "
                f"MRR={res['mrr@10']:.2%}  nDCG={res['ndcg@10']:.2%}  ({time.time()-t0:.1f}s)")

            result = json.load(open(results_path)) if results_path.exists() else {}
            result["qwen"] = res
            json.dump(result, open(results_path, "w"), indent=2)
            log(f"  Saved to {results_path}")
        except Exception as e:
            log(f"    EVAL FAILED: {e}")
            result = json.load(open(results_path)) if results_path.exists() else {}
            result["qwen"] = {"error": str(e)}
            json.dump(result, open(results_path, "w"), indent=2)

    # ── Final summary ──
    log("\n" + "=" * 80)
    log("FINAL SUMMARY: BGE-Code-v1 vs Qwen3-Embedding-8B")
    log("=" * 80)

    metrics = ["hit@1", "hit@5", "hit@10", "mrr@10", "ndcg@10"]
    header = f"{'Repo':14s}{'Model':8s}" + "".join(f"{m:>9s}" for m in metrics)
    log(f"\n{header}")
    log("-" * 72)

    bge_all = {m: [] for m in metrics}
    qwen_all = {m: [] for m in metrics}

    for repo in REPOS:
        rp = OUT_DIR / f"results_{repo}.json"
        if not rp.exists():
            continue
        d = json.load(open(rp))
        if "bge" in d:
            vals = "".join(f"{d['bge'][m]:>8.1%}" for m in metrics)
            log(f"{repo:14s}{'BGE':8s}{vals}")
            for m in metrics:
                bge_all[m].append(d["bge"][m])
        if "qwen" in d and "error" not in d.get("qwen", {}):
            vals = "".join(f"{d['qwen'][m]:>8.1%}" for m in metrics)
            log(f"{repo:14s}{'Qwen':8s}{vals}")
            for m in metrics:
                qwen_all[m].append(d["qwen"][m])

    if bge_all["hit@1"]:
        vals = "".join(f"{statistics.mean(bge_all[m]):>8.1%}" for m in metrics)
        log(f"{'─── AVG ───':14s}{'BGE':8s}{vals}")
    if qwen_all["hit@1"]:
        vals = "".join(f"{statistics.mean(qwen_all[m]):>8.1%}" for m in metrics)
        log(f"{'─── AVG ───':14s}{'Qwen':8s}{vals}")

    # Save combined summary
    combined = {}
    for repo in REPOS:
        rp = OUT_DIR / f"results_{repo}.json"
        if rp.exists():
            combined[repo] = json.load(open(rp))
    json.dump(combined, open(OUT_DIR / "summary.json", "w"), indent=2, default=str)
    log(f"\nCombined: {OUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
