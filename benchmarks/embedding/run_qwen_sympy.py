"""Embed sympy corpus with Qwen via Ollama in batches (400 req limit workaround)."""
from __future__ import annotations

import json
import math
import statistics

import numpy as np
import requests as req

OUT = "/home/pankaj/Projects/leanchain/atelier/benchmarks/embedding/data/multi_repo"
OLLAMA_URL = "http://localhost:11434/api/embed"


def log(msg):
    print(msg, flush=True)


chunks = [json.loads(l) for l in open(f"{OUT}/corpus_sympy.jsonl") if l.strip()]
queries = [json.loads(l) for l in open(f"{OUT}/queries_sympy.jsonl") if l.strip()]
log(f"Sympy: {len(chunks)} chunks, {len(queries)} queries")

# Corpus already embedded, skip to evaluation
corpus_qwen = np.load(f"{OUT}/emb_qwen_sympy.npy")
log(f"Corpus loaded: {corpus_qwen.shape}")

cid = [c["id"] for c in chunks]
eval_queries = queries[:200]
q_texts = [f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q['query']}" for q in eval_queries]
log(f"Embedding {len(q_texts)} queries in one batch...")
r = req.post(OLLAMA_URL, json={"model": "qwen3-embedding:8b", "input": q_texts}, timeout=600)
all_qv = np.array(r.json()["embeddings"], dtype=np.float32)  # (200, 4096)

hits = {1: [], 5: [], 10: []}
rrs = []
nds = []
for qi, q in enumerate(eval_queries):
    rel = set(q["relevant"])
    qv = all_qv[qi]
    ranked = [cid[i] for i in np.argsort(-(corpus_qwen @ qv))]
    for k in hits:
        hits[k].append(float(bool(set(ranked[:k]) & rel)))
    for rk, rid in enumerate(ranked[:10], 1):
        if rid in rel:
            rrs.append(1.0 / rk)
            break
    else:
        rrs.append(0.0)
    gains = [1 if rid in rel else 0 for rid in ranked[:10]]
    ideal = min(10, len(rel))
    d = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    id_ = sum(1 / math.log2(i + 2) for i in range(ideal))
    nds.append(d / id_ if id_ else 0.0)

res = {
    "hit@1": statistics.mean(hits[1]),
    "hit@5": statistics.mean(hits[5]),
    "hit@10": statistics.mean(hits[10]),
    "mrr@10": statistics.mean(rrs),
    "ndcg@10": statistics.mean(nds),
}
log(f"Qwen sympy: hit@1={res['hit@1']:.2%}  hit@5={res['hit@5']:.2%}  hit@10={res['hit@10']:.2%}  "
    f"MRR={res['mrr@10']:.2%}  nDCG={res['ndcg@10']:.2%}")

result = json.load(open(f"{OUT}/results_sympy.json"))
result["qwen"] = res
json.dump(result, open(f"{OUT}/results_sympy.json", "w"), indent=2)
log("Saved")

# Final combined summary
log("\n" + "=" * 80)
log("FINAL: BGE-Code-v1 vs Qwen3-Embedding-8B")
log("=" * 80)
METRICS = ["hit@1", "hit@5", "hit@10", "mrr@10", "ndcg@10"]
repos = ["django", "pytest", "astropy", "sympy", "scikit-learn", "xarray"]
header = f"{'Repo':14s}{'Model':8s}" + "".join(f"{m:>9s}" for m in METRICS)
log(f"\n{header}")
log("-" * 72)
bge_all = {m: [] for m in METRICS}
qwen_all = {m: [] for m in METRICS}
for repo in repos:
    rp = f"{OUT}/results_{repo}.json"
    try:
        d = json.load(open(rp))
    except (FileNotFoundError, json.JSONDecodeError):
        continue
    if "bge" in d:
        vals = "".join(f"{d['bge'][m]:>8.1%}" for m in METRICS)
        log(f"{repo:14s}{'BGE':8s}{vals}")
        for m in METRICS:
            bge_all[m].append(d["bge"][m])
    if "qwen" in d and "error" not in d.get("qwen", {}):
        vals = "".join(f"{d['qwen'][m]:>8.1%}" for m in METRICS)
        log(f"{repo:14s}{'Qwen':8s}{vals}")
        for m in METRICS:
            qwen_all[m].append(d["qwen"][m])
if bge_all["hit@1"]:
    vals = "".join(f"{statistics.mean(bge_all[m]):>8.1%}" for m in METRICS)
    log(f"{'─── AVG ───':14s}{'BGE':8s}{vals}")
if qwen_all["hit@1"]:
    vals = "".join(f"{statistics.mean(qwen_all[m]):>8.1%}" for m in METRICS)
    log(f"{'─── AVG ───':14s}{'Qwen':8s}{vals}")

log("\nDone.")
