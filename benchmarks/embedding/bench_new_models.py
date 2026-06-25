"""
Benchmark jina-embeddings-v4 and voyage-code-3 on 200 queries.
"""
import json
import math
import os
import statistics
import time

import numpy as np
import requests as req

BASE = "/home/pankaj/Projects/leanchain/atelier/benchmarks/embedding/data"

corpus = [json.loads(l) for l in open(os.path.join(BASE, "corpus.jsonl")) if l.strip()]
queries = [json.loads(l) for l in open(os.path.join(BASE, "queries.jsonl")) if l.strip()]
cid = [c["id"] for c in corpus]
qq = queries[:200]

# ── Jina Embeddings v4 ──────────────────────────────────────────────
import torch
from sentence_transformers import SentenceTransformer

print("=" * 70)
print("JINA EMBEDDINGS V4")
print("=" * 70)

print("Loading jina-embeddings-v4...", flush=True)
t0 = time.time()
jina_model = SentenceTransformer(
    "jinaai/jina-embeddings-v4",
    trust_remote_code=True,
    device="cuda" if torch.cuda.is_available() else "cpu",
)
print(f"  Loaded in {time.time()-t0:.1f}s", flush=True)

def jina_embed(texts, batch_size=8, role="query"):
    prompt = "query" if role == "query" else "passage"
    return np.array(jina_model.encode(
        texts, batch_size=batch_size, show_progress_bar=True,
        task="code", prompt_name=prompt,
        normalize_embeddings=True,
    ), dtype=np.float32)

# Embed corpus
print("Embedding corpus with jina-embeddings-v4...", flush=True)
t0 = time.time()
corp_texts = [c["text"] for c in corpus]
# Check if cached
cache_path = os.path.join(BASE, "embeddings_jina/corpus.npy")
os.makedirs(os.path.dirname(cache_path), exist_ok=True)
if os.path.exists(cache_path):
    cv_jina = np.load(cache_path)
    print(f"  Loaded cached: {cv_jina.shape}", flush=True)
else:
    cv_jina = jina_embed(corp_texts, batch_size=4, role="passage")
    np.save(cache_path, cv_jina)
    print(f"  Corpus: {cv_jina.shape}, time={time.time()-t0:.1f}s", flush=True)

# Self-retrieval sanity
scores = cv_jina @ cv_jina.T
top3 = np.argsort(-scores, axis=1)[:, :3]
self_hits = sum(1 for i in range(len(cv_jina)) if i in top3[i])
print(f"  Self in top-3: {self_hits}/{len(cv_jina)} = {self_hits/len(cv_jina):.2%}")
unique = len(np.unique(cv_jina.round(4), axis=0))
print(f"  Unique vectors (4dp): {unique}/{len(cv_jina)}")

# Evaluate on 200 queries
def evaluate(corpus_vecs, embed_fn, role="query"):
    hits = {1: [], 5: [], 10: []}; rrs = []; nds = []
    for qi, q in enumerate(qq):
        rel = set(q["relevant"])
        qv = embed_fn([q["query"]], role=role)
        ranked = [cid[i] for i in np.argsort(-(corpus_vecs @ qv[0]))]
        for k in hits:
            hits[k].append(float(bool(set(ranked[:k]) & rel)))
        for r, rid in enumerate(ranked[:10], 1):
            if rid in rel: rrs.append(1.0/r); break
        else: rrs.append(0.0)
        gains = [1 if rid in rel else 0 for rid in ranked[:10]]
        ideal_len = min(10, len(rel))
        d = sum(g / math.log2(i+2) for i, g in enumerate(gains))
        id_ = sum(1 / math.log2(i+2) for i in range(ideal_len))
        nds.append(d / id_ if id_ else 0.0)
    return {f"hit@{k}": statistics.mean(v) for k, v in hits.items()} | {"mrr@10": statistics.mean(rrs), "ndcg@10": statistics.mean(nds)}

# Jina with code adapter
res = evaluate(cv_jina, jina_embed, role="query")
print("\n  jina-embeddings-v4 (code adapter):")
print(f"    hit@1={res['hit@1']:.2%}  hit@5={res['hit@5']:.2%}  hit@10={res['hit@10']:.2%}  mrr={res['mrr@10']:.2%}  ndcg={res['ndcg@10']:.2%}")

# Jina with retrieval adapter (default)
def jina_embed_retrieval(texts, batch_size=8, role="query"):
    return np.array(jina_model.encode(
        texts, batch_size=batch_size, show_progress_bar=False,
        task="retrieval", prompt_name="query" if role == "query" else "passage",
        normalize_embeddings=True,
    ), dtype=np.float32)

res_r = evaluate(cv_jina, jina_embed_retrieval, role="query")
print("  jina-embeddings-v4 (retrieval adapter):")
print(f"    hit@1={res_r['hit@1']:.2%}  hit@5={res_r['hit@5']:.2%}  hit@10={res_r['hit@10']:.2%}  mrr={res_r['mrr@10']:.2%}  ndcg={res_r['ndcg@10']:.2%}")

# MemoryRegistry query
mem_idx = cid.index("core.capabilities.cross_vendor_memory.registry::MemoryRegistry#part1")
print("\n  MemoryRegistry queries:")
for q_text in ["MemoryRegistry", "class MemoryRegistry", "Find the MemoryRegistry class definition"]:
    qv = jina_embed([q_text], role="query")
    scores = cv_jina @ qv[0]
    rank = list(np.argsort(-scores)).index(mem_idx) + 1
    top3 = [cid[i].split('::')[1] if '::' in cid[i] else cid[i][:50] for i in np.argsort(-scores)[:3]]
    print(f"    '{q_text:40s}' → rank {rank:5d}  top: {top3}")

# ── BGE Multi-lingual (bge-m3) via Ollama ──────────────────────────
print("\n" + "=" * 70)
print("BGE-M3 (Ollama)")
print("=" * 70)

OLLAMA_URL = "http://localhost:11434/api/embed"
def bge_m3_embed(texts, role=None):
    r = req.post(OLLAMA_URL, json={"model": "bge-m3", "input": texts}, timeout=120)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)

print("Embedding corpus with bge-m3...", flush=True)
t0 = time.time()
cache_path_m3 = os.path.join(BASE, "embeddings_bge_m3/corpus.npy")
os.makedirs(os.path.dirname(cache_path_m3), exist_ok=True)
if os.path.exists(cache_path_m3):
    cv_m3 = np.load(cache_path_m3)
    print(f"  Loaded cached: {cv_m3.shape}", flush=True)
else:
    cv_m3 = bge_m3_embed(corp_texts)
    np.save(cache_path_m3, cv_m3)
    print(f"  Corpus: {cv_m3.shape}, time={time.time()-t0:.1f}s", flush=True)

res_m3 = evaluate(cv_m3, bge_m3_embed)
print("\n  bge-m3:")
print(f"    hit@1={res_m3['hit@1']:.2%}  hit@5={res_m3['hit@5']:.2%}  hit@10={res_m3['hit@10']:.2%}  mrr={res_m3['mrr@10']:.2%}  ndcg={res_m3['ndcg@10']:.2%}")

# MemoryRegistry
print("  MemoryRegistry queries:")
for q_text in ["MemoryRegistry", "class MemoryRegistry", "Find the MemoryRegistry class definition"]:
    qv = bge_m3_embed([q_text])
    scores = cv_m3 @ qv[0]
    rank = list(np.argsort(-scores)).index(mem_idx) + 1
    top3 = [cid[i].split('::')[1] if '::' in cid[i] else cid[i][:50] for i in np.argsort(-scores)[:3]]
    print(f"    '{q_text:40s}' → rank {rank:5d}  top: {top3}")

print("\nDone.", flush=True)
