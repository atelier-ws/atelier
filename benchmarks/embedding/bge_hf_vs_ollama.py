"""
HF BAAI/bge-code-v1 vs Ollama GGUF: using SentenceTransformer (v4 compatible).
"""
import json
import math
import os
import statistics
import time

import numpy as np
import requests as req
import torch
from sentence_transformers import SentenceTransformer

BASE = "/home/pankaj/Projects/leanchain/atelier/benchmarks/embedding/data"
OLLAMA_URL = "http://localhost:11434/api/embed"

corpus = [json.loads(l) for l in open(os.path.join(BASE, "corpus.jsonl")) if l.strip()]
queries = [json.loads(l) for l in open(os.path.join(BASE, "queries.jsonl")) if l.strip()]
cid = [c["id"] for c in corpus]

# ── 1. Load HF model ────────────────────────────────────────────────
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading BAAI/bge-code-v1 via SentenceTransformer on {device}...", flush=True)
t0 = time.time()
hf_model = SentenceTransformer(
    "BAAI/bge-code-v1",
    trust_remote_code=True,
    device=device,
)
hf_model.eval()
print(f"  Loaded in {time.time()-t0:.1f}s", flush=True)

def hf_embed(texts, batch_size=8):
    return np.array(hf_model.encode(texts, batch_size=batch_size, show_progress_bar=True, normalize_embeddings=True), dtype=np.float32)

def ollama_embed(texts):
    r = req.post(OLLAMA_URL, json={"model": "bge-code-v1", "input": texts}, timeout=300)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)

# ── 2. Embedding space alignment ─────────────────────────────────────
print("\n── Embedding space alignment ──", flush=True)
samples = ["class MemoryRegistry:", "def get_user", "import os", "from typing import List"]
hf_samp = hf_embed(samples)
ollama_samp = ollama_embed(samples)
for i, s in enumerate(samples):
    cs = np.dot(hf_samp[i], ollama_samp[i])
    print(f"  '{s[:30]:30s}'  cos_sim = {cs:.6f}")

# ── 3. Embed corpus with HF ──────────────────────────────────────────
print(f"\n── Embedding corpus ({len(corpus)} chunks) with HF ──", flush=True)
t0 = time.time()
corp_texts = [c["text"] for c in corpus]
hf_corpus = hf_embed(corp_texts, batch_size=8)
print(f"  HF corpus: {hf_corpus.shape}, time={time.time()-t0:.1f}s", flush=True)
np.save(os.path.join(BASE, "embeddings_bge/hf_corpus.npy"), hf_corpus)

# ── 4. Self-retrieval sanity ─────────────────────────────────────────
print("\n── Self-retrieval: HF corpus ──", flush=True)
scores = hf_corpus @ hf_corpus.T
top1 = np.argsort(-scores, axis=1)[:, :3]
self_hits = sum(1 for i in range(len(hf_corpus)) if i in top1[i, :3])
print(f"  Self in top-3: {self_hits}/{len(hf_corpus)} = {self_hits/len(hf_corpus):.2%}")
unique_hf = len(np.unique(hf_corpus.round(4), axis=0))
print(f"  Unique vectors (4dp): {unique_hf}/{len(hf_corpus)}")
print(f"  Mean dim variance: {hf_corpus.var(axis=0).mean():.6f}")

# ── 5. Benchmark ─────────────────────────────────────────────────────
print("\n── Benchmark: 200 queries ──", flush=True)

def evaluate(corpus_vecs, embed_fn, use_instruction=True):
    hits = {1: [], 5: [], 10: []}; rrs = []; nds = []
    for qi, q in enumerate(queries[:200]):
        rel = set(q["relevant"])
        if use_instruction:
            q_text = f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q['query']}"
        else:
            q_text = q["query"]
        qv = embed_fn([q_text])
        ranked = [cid[i] for i in np.argsort(-(corpus_vecs @ qv[0]))]
        for k in hits:
            topk = set(ranked[:k])
            hits[k].append(float(bool(topk & rel)))
        for r, rid in enumerate(ranked[:10], 1):
            if rid in rel: rrs.append(1.0/r); break
        else: rrs.append(0.0)
        gains = [1 if rid in rel else 0 for rid in ranked[:10]]
        ideal_len = min(10, len(rel))
        d = sum(g / math.log2(i+2) for i, g in enumerate(gains))
        id_ = sum(1 / math.log2(i+2) for i in range(ideal_len))
        nds.append(d / id_ if id_ else 0.0)
    return {f"hit@{k}": statistics.mean(v) for k, v in hits.items()} | {"mrr@10": statistics.mean(rrs), "ndcg@10": statistics.mean(nds)}

cv_ollama = np.load(os.path.join(BASE, "embeddings_bge/corpus.npy"))

for label, cv, fn, inst in [
    ("HF (instruction)",      hf_corpus, hf_embed, True),
    ("Ollama (instruction)",  cv_ollama, ollama_embed, True),
    ("HF (no instruction)",   hf_corpus, hf_embed, False),
    ("Ollama (no instruction)", cv_ollama, ollama_embed, False),
    ("HF->Ollama corpus",     cv_ollama, hf_embed, True),
    ("Ollama->HF corpus",     hf_corpus, ollama_embed, True),
]:
    res = evaluate(cv, fn, inst)
    print(f"  {label:25s}  hit@1={res['hit@1']:.2%}  hit@5={res['hit@5']:.2%}  hit@10={res['hit@10']:.2%}  mrr={res['mrr@10']:.2%}  ndcg={res['ndcg@10']:.2%}")

# ── 6. MemoryRegistry ────────────────────────────────────────────────
print("\n── MemoryRegistry ──", flush=True)
mem_idx = cid.index("core.capabilities.cross_vendor_memory.registry::MemoryRegistry#part1")
for label, cv, fn in [("HF", hf_corpus, hf_embed), ("Ollama", cv_ollama, ollama_embed)]:
    print(f"  {label}:")
    for q_text in ["MemoryRegistry", "class MemoryRegistry", "Find the MemoryRegistry class definition"]:
        qv = fn([f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q_text}"])
        scores = cv @ qv[0]
        rank = list(np.argsort(-scores)).index(mem_idx) + 1
        top3 = [cid[i].split('::')[1] if '::' in cid[i] else cid[i][:60] for i in np.argsort(-scores)[:3]]
        print(f"    '{q_text:40s}' → rank {rank:5d}  top: {top3}")

# ── 7. Final comparison ──────────────────────────────────────────────
print("\n── Final comparison (200 queries) ──", flush=True)
cv_qwen = np.load(os.path.join(BASE, "embeddings_qwen3/corpus.npy"))
def qwen_embed(texts):
    r = req.post(OLLAMA_URL, json={"model": "qwen3-embedding:8b", "input": texts}, timeout=120)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)
res_qwen = evaluate(cv_qwen, qwen_embed, use_instruction=True)
print(f"  Qwen3-Embedding-8B          hit@1={res_qwen['hit@1']:.2%}  hit@5={res_qwen['hit@5']:.2%}  hit@10={res_qwen['hit@10']:.2%}  mrr={res_qwen['mrr@10']:.2%}  ndcg={res_qwen['ndcg@10']:.2%}")

# BM25
import re
from collections import Counter


def tokenize(text):
    return [t.lower() for t in re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*|[a-zA-Z]+', text)]
tok_corp = [tokenize(c["text"]) for c in corpus]
avgdl = sum(len(t) for t in tok_corp) / len(tok_corp)
N = len(tok_corp)
df = Counter()
for dt in tok_corp:
    for t in set(dt): df[t] += 1
idf = {t: math.log((N - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in df}
k1, b = 1.5, 0.75
def bm25(query):
    qt = tokenize(query)
    scores = np.zeros(N, dtype=np.float32)
    for di, dt in enumerate(tok_corp):
        dtf = Counter(dt)
        sc = 0.0
        for t in set(qt):
            if t in idf:
                tf = dtf.get(t, 0)
                sc += idf[t] * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * len(dt) / avgdl))
        scores[di] = sc
    return scores

for k in [1, 5, 10]:
    hits = []
    for qi, q in enumerate(queries[:200]):
        rel = set(q["relevant"])
        ranked = [cid[i] for i in np.argsort(-bm25(q["query"]))]
        hits.append(float(bool(set(ranked[:k]) & rel)))
    print(f"  BM25 only           hit@{k}={statistics.mean(hits):.2%}")

print("\nDone.", flush=True)
