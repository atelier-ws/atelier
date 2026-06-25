"""
BGE ablation: query variants, corpus format variants, BM25 baseline.
"""
import json
import math
import os
import re
import statistics
from collections import Counter

import numpy as np
import requests as req

BASE = "/home/pankaj/Projects/leanchain/atelier/benchmarks/embedding/data"
MODEL_B = "bge-code-v1"
MODEL_Q = "qwen3-embedding:8b"
OLLAMA_URL = "http://localhost:11434/api/embed"

def embed(model, texts):
    r = req.post(OLLAMA_URL, json={"model": model, "input": texts}, timeout=120)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)

corpus = [json.loads(l) for l in open(os.path.join(BASE, "corpus.jsonl")) if l.strip()]
queries = [json.loads(l) for l in open(os.path.join(BASE, "queries.jsonl")) if l.strip()]
c_by_id = {c["id"]: c for c in corpus}
cid = list(c_by_id.keys())

# ── 1. MemoryRegistry verification ──────────────────────────────────
print("="*70)
print("1. MemoryRegistry verification")
print("="*70)
mem_id = "core.capabilities.cross_vendor_memory.registry::MemoryRegistry#part1"
chunk = c_by_id.get(mem_id)
print(f"Chunk exists: {chunk is not None}")
if chunk:
    text = chunk["text"]
    print(f"Contains 'MemoryRegistry': {'MemoryRegistry' in text}")
    print(f"Contains 'class MemoryRegistry': {'class MemoryRegistry' in text}")
    print(f"Contains '__init__' or method def: {'def ' in text}")
    if 'class MemoryRegistry' in text:
        cls_line = [l for l in text.split('\n') if 'class MemoryRegistry' in l][0]
        print(f"Class signature line: '{cls_line}'")
    print(f"Full text (first 400):\n{text[:400]}")

mem_idx = cid.index(mem_id)
swarm_id = "core.capabilities.swarm.capability::resolve_swarm_runner_metadata"
swarm_idx = cid.index(swarm_id)

# ── 2. Query variants on MemoryRegistry ────────────────────────────
print("\n" + "="*70)
print("2. Query variants — MemoryRegistry rank")
print("="*70)

variants = [
    "MemoryRegistry",
    "class MemoryRegistry",
    "Find the MemoryRegistry class definition",
    "Where is MemoryRegistry defined?",
]

for q in variants:
    bv = embed(MODEL_B, [f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q}"])
    bs = np.load(os.path.join(BASE, "embeddings_bge/corpus.npy")) @ bv[0]
    brank = list(np.argsort(-bs)).index(mem_idx) + 1
    print(f"  BGE  '{q[:40]:40s}' → rank {brank:5d}  top: {cid[np.argmax(bs)][:50]}")

# Also test with NO instruction (raw query)
print("\nNo instruction (raw query):")
for q in variants:
    bv = embed(MODEL_B, [q])
    bs = np.load(os.path.join(BASE, "embeddings_bge/corpus.npy")) @ bv[0]
    brank = list(np.argsort(-bs)).index(mem_idx) + 1
    print(f"  BGE  '{q[:40]:40s}' → rank {brank:5d}  top: {cid[np.argmax(bs)][:50]}")

# ── 3. BM25 baseline ────────────────────────────────────────────────
print("\n" + "="*70)
print("3. BM25 baseline")
print("="*70)

# Pure Python BM25
def tokenize(text):
    return [t.lower() for t in re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*|[a-zA-Z]+', text)]

corp_texts = [c["text"] for c in corpus]
tokenized = [tokenize(t) for t in corp_texts]
avgdl = sum(len(t) for t in tokenized) / len(tokenized)
N = len(tokenized)
k1, b = 1.5, 0.75

df = Counter()
for doc_tokens in tokenized:
    for t in set(doc_tokens):
        df[t] += 1
idf = {t: math.log((N - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in df}

def bm25_score(query):
    q_tokens = tokenize(query)
    scores = np.zeros(N, dtype=np.float32)
    for doc_idx, doc_tokens in enumerate(tokenized):
        doc_tf = Counter(doc_tokens)
        score = 0.0
        for t in set(q_tokens):
            if t in idf:
                tf = doc_tf.get(t, 0)
                score += idf[t] * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * len(doc_tokens) / avgdl))
        scores[doc_idx] = score
    return scores

bm25_hits = []
for qi, q in enumerate(queries[:200]):
    rel = set(q["relevant"])
    scores = bm25_score(q["query"])
    topk = set([cid[i] for i in np.argsort(-scores)[:10]])
    bm25_hits.append(float(bool(topk & rel)))
print(f"BM25 hit@10 (200 queries): {statistics.mean(bm25_hits):.2%}")

# ── 4. BM25 + BGE hybrid ────────────────────────────────────────────
print("\n" + "="*70)
print("4. BM25 + BGE dense hybrid")
print("="*70)

cv_bge = np.load(os.path.join(BASE, "embeddings_bge/corpus.npy"))
cv_qwen = np.load(os.path.join(BASE, "embeddings_qwen3/corpus.npy"))

fmt_bge = lambda q: f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q}"
fmt_qwen = lambda q: f"Instruct: Given a natural-language query, retrieve relevant source-code chunks from a software repository.\nQuery:{q}"

for model_name, cv, fmt_fn, MODEL in [("BGE", cv_bge, fmt_bge, MODEL_B), ("Qwen", cv_qwen, fmt_qwen, MODEL_Q)]:
    hybrid_hits = []
    for qi, q in enumerate(queries[:200]):
        rel = set(q["relevant"])
        # Dense
        qv = embed(MODEL, [fmt_fn(q["query"])])
        dense_scores = cv @ qv[0]
        d_min, d_max = dense_scores.min(), dense_scores.max()
        dense_norm = (dense_scores - d_min) / (d_max - d_min + 1e-12)
        # BM25
        bm_scores = bm25_score(q["query"])
        b_min, b_max = bm_scores.min(), bm_scores.max()
        bm_norm = (bm_scores - b_min) / (b_max - b_min + 1e-12)
        # Hybrid (equal fusion)
        hybrid = 0.5 * dense_norm + 0.5 * bm_norm
        topk = set([cid[i] for i in np.argsort(-hybrid)[:10]])
        hybrid_hits.append(float(bool(topk & rel)))
    print(f"  {model_name} dense + BM25 hybrid hit@10: {statistics.mean(hybrid_hits):.2%}")

# ── 5. Qwen full metrics on 200 queries (dense, hybrid, BM25 only) ──
print("\n" + "="*70)
print("5. Qwen full metrics (200 queries)")
print("="*70)

def evaluate_model(cv, fmt_fn, MODEL, use_hybrid=False, use_bm25_only=False):
    hits = {1: [], 5: [], 10: [], 20: []}
    recalls = {1: [], 5: [], 10: [], 20: []}
    rrs, nds = [], []
    
    for qi, q in enumerate(queries[:200]):
        rel = set(q["relevant"])
        
        if use_bm25_only:
            scores = bm25_score(q["query"])
        elif use_hybrid:
            qv = embed(MODEL, [fmt_fn(q["query"])])
            dense_scores = cv @ qv[0]
            d_min, d_max = dense_scores.min(), dense_scores.max()
            dense_norm = (dense_scores - d_min) / (d_max - d_min + 1e-12)
            bm_scores = bm25_score(q["query"])
            b_min, b_max = bm_scores.min(), bm_scores.max()
            bm_norm = (bm_scores - b_min) / (b_max - b_min + 1e-12)
            scores = 0.5 * dense_norm + 0.5 * bm_norm
        else:
            qv = embed(MODEL, [fmt_fn(q["query"])])
            scores = cv @ qv[0]
        
        ranked = [cid[i] for i in np.argsort(-scores)]
        for k in hits:
            topk = set(ranked[:k])
            hits[k].append(float(bool(topk & rel)))
            recalls[k].append(len(topk & rel) / len(rel) if rel else 0.0)
        for r, rid in enumerate(ranked[:10], 1):
            if rid in rel: rrs.append(1.0/r); break
        else: rrs.append(0.0)
        gains = [1 if rid in rel else 0 for rid in ranked[:10]]
        ideal = [1] * min(10, len(rel))
        d = sum(g / math.log2(i+2) for i, g in enumerate(gains))
        id_ = sum(1 / math.log2(i+2) for i in range(min(10, len(rel))))
        nds.append(d / id_ if id_ else 0.0)
    
    return {
        "hit@1": statistics.mean(hits[1]), "hit@5": statistics.mean(hits[5]),
        "hit@10": statistics.mean(hits[10]), "recall@1": statistics.mean(recalls[1]),
        "recall@5": statistics.mean(recalls[5]), "recall@10": statistics.mean(recalls[10]),
        "recall@20": statistics.mean(recalls[20]), "mrr@10": statistics.mean(rrs),
        "ndcg@10": statistics.mean(nds),
    }

configs = [
    ("Qwen dense", cv_qwen, fmt_qwen, MODEL_Q, False, False),
    ("Qwen hybrid", cv_qwen, fmt_qwen, MODEL_Q, True, False),
    ("BM25 only", None, None, None, False, True),
]

for label, cv, fn, mdl, hybrid, bmonly in configs:
    res = evaluate_model(cv, fn, mdl, hybrid, bmonly)
    print(f"\n  {label}:")
    print(f"    hit@1={res['hit@1']:.2%}  hit@5={res['hit@5']:.2%}  hit@10={res['hit@10']:.2%}")
    print(f"    recall@1={res['recall@1']:.2%}  recall@10={res['recall@10']:.2%}")
    print(f"    mrr@10={res['mrr@10']:.2%}  ndcg@10={res['ndcg@10']:.2%}")

# ── 6. BGE corpus format variants ──────────────────────────────────
print("\n" + "="*70)
print("6. BGE: corpus format ablation (200 queries, hit@10)")
print("="*70)

# Build variant corpuses
# A: Raw code (no Path/Symbol prefix)
def strip_prefix(text):
    lines = text.split('\n')
    # Remove Path: and Symbol: lines
    stripped = [l for l in lines if not l.startswith('Path:') and not l.startswith('Symbol:')]
    return '\n'.join(stripped).strip()

# E: Symbol + signature only
def symbol_signature(text):
    lines = text.split('\n')
    # Take just the symbol line + first logical code block
    symbol = ""
    body = []
    in_body = False
    for l in lines:
        if l.startswith('Symbol:'):
            symbol = l
        elif l.startswith('Path:'):
            continue
        elif symbol and not in_body:
            if l.strip():
                body.append(l)
                in_body = True
        elif in_body:
            body.append(l)
    return f"{symbol}\n" + '\n'.join(body)

print("Building variant corpus embeddings... (may take a moment)", flush=True)

# Embed variant A (raw code)
a_texts = [strip_prefix(c["text"]) for c in corpus]
av = embed(MODEL_B, a_texts)

# Embed variant E (symbol + signature)
e_texts = [symbol_signature(c["text"]) for c in corpus]
ev = embed(MODEL_B, e_texts)

# Test with 2 instruction variants
insts = [
    ("Official BGE", "<instruct>Given a natural language query, retrieve relevant code.\n<query>"),
    ("Short", "<instruct>Retrieve source code relevant to the natural-language query.\n<query>"),
    ("Task-specific", "<instruct>Given a developer query, retrieve the function, class, configuration, or test from the repository that best answers it.\n<query>"),
]

for fmt_name, fmt_template in insts:
    for corpus_name, cvec in [("A: raw code", av), ("E: symbol+signature", ev), ("Cached (Path+Symbol)", cv_bge)]:
        if corpus_name == "Cached (Path+Symbol)":
            pass  # already have cv_bge
        hits = 0
        for qi, q in enumerate(queries[:200]):
            rel = set(q["relevant"])
            qv = embed(MODEL_B, [f"{fmt_template}{q['query']}"])
            scores = cvec @ qv[0]
            topk = set([cid[i] for i in np.argsort(-scores)[:10]])
            if topk & rel: hits += 1
        print(f"  {fmt_name:15s} + {corpus_name:25s}: hit@10 = {hits/200:.2%}")

print("\nDone.", flush=True)
