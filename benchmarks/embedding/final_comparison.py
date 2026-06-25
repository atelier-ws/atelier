"""
Final comparison: BGE (HF) vs Qwen — significance, Matryoshka, hybrid RRF, reranker.
"""
import json
import math
import os
import re
import statistics
import time
from collections import Counter

import numpy as np
import requests as req
import torch
from sentence_transformers import SentenceTransformer

BASE = "/home/pankaj/Projects/leanchain/atelier/benchmarks/embedding/data"
OLLAMA_URL = "http://localhost:11434/api/embed"
MODEL_QWEN = "qwen3-embedding:8b"

corpus = [json.loads(l) for l in open(os.path.join(BASE, "corpus.jsonl")) if l.strip()]
queries = [json.loads(l) for l in open(os.path.join(BASE, "queries.jsonl")) if l.strip()]
cid = [c["id"] for c in corpus]

# Load cached embeddings
cv_bge_hf = np.load(os.path.join(BASE, "embeddings_bge/hf_corpus.npy"))
cv_qwen = np.load(os.path.join(BASE, "embeddings_qwen3/corpus.npy"))
print(f"Loaded: BGE_HF {cv_bge_hf.shape}, Qwen {cv_qwen.shape}")

# Load HF SentenceTransformer for BGE
print("Loading BAAI/bge-code-v1 via SentenceTransformer...", flush=True)
t0 = time.time()
hf_model = SentenceTransformer(
    "BAAI/bge-code-v1",
    trust_remote_code=True,
    device="cuda" if torch.cuda.is_available() else "cpu",
)
hf_model.eval()
print(f"  Loaded in {time.time()-t0:.1f}s on {hf_model.device}", flush=True)

def embed_bge(texts, batch_size=8):
    return np.array(hf_model.encode(texts, batch_size=batch_size, show_progress_bar=True, normalize_embeddings=True), dtype=np.float32)

def embed_qwen(texts):
    r = req.post(OLLAMA_URL, json={"model": MODEL_QWEN, "input": texts}, timeout=120)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)

# Qwen instruction format
QWEN_FMT = lambda q: f"Instruct: Given a natural-language query, retrieve relevant source-code chunks from a software repository.\nQuery:{q}"
BGE_FMT = lambda q: f"<instruct>Given a natural language query, retrieve relevant code.\n<query>{q}"

# ── BM25 ────────────────────────────────────────────────────────────
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
def bm25_scores(query):
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

# RRF
def rrf(rankings, k=60):
    scores = Counter()
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, 1):
            scores[doc_id] += 1.0 / (k + rank)
    return scores

def evaluate(embed_fn, corpus_vecs, fmt_fn, queries_list, use_bm25=False, use_hybrid=False, top_k=10, truncate_dims=None):
    """Return per-query detailed results for significance testing."""
    results = []
    for qi, q in enumerate(queries_list):
        rel = set(q["relevant"])
        if use_bm25:
            dense_scores = None
            bm_scores = bm25_scores(q["query"])
        else:
            qv = embed_fn([fmt_fn(q["query"])])
            if truncate_dims and qv.shape[1] > truncate_dims:
                qv = qv[:, :truncate_dims]
                qv /= np.linalg.norm(qv, axis=1, keepdims=True).clip(min=1e-12)
            dense_scores = corpus_vecs @ qv[0]
            bm_scores = None
        
        if use_hybrid:
            # Normalize both to [0,1] then RRF fusion
            d_scores = dense_scores
            b_scores = bm25_scores(q["query"])
            # Rank-based fusion via RRF
            d_ranked = [cid[i] for i in np.argsort(-d_scores)]
            b_ranked = [cid[i] for i in np.argsort(-b_scores)]
            fusion = rrf([d_ranked, b_ranked])
            ranked = sorted(fusion.keys(), key=lambda x: -fusion[x])
        elif use_bm25:
            ranked = [cid[i] for i in np.argsort(-bm_scores)]
        else:
            ranked = [cid[i] for i in np.argsort(-dense_scores)]
        
        # Compute metrics
        hits = {}
        for k in [1, 5, 10]:
            topk = set(ranked[:k])
            hits[k] = bool(topk & rel)
        
        rr = 0.0
        for r, rid in enumerate(ranked[:10], 1):
            if rid in rel:
                rr = 1.0/r
                break
        
        gains = [1 if rid in rel else 0 for rid in ranked[:10]]
        ideal_len = min(10, len(rel))
        d = sum(g / math.log2(i+2) for i, g in enumerate(gains))
        id_ = sum(1 / math.log2(i+2) for i in range(ideal_len))
        ndcg = d / id_ if id_ else 0.0
        
        results.append({
            "query_id": qi, "query": q["query"], "relevant": q["relevant"],
            "hit1": hits[1], "hit5": hits[5], "hit10": hits[10],
            "mrr": rr, "ndcg": ndcg,
            "ranked_ids": ranked[:50],  # for reranker stage
        })
    return results

# ── 1. PAIRED SIGNIFICANCE TEST ──────────────────────────────────────
print("\n" + "=" * 70)
print("1. PAIRED SIGNIFICANCE TEST (200 queries)")
print("=" * 70)

qq = queries[:200]
bge_res = evaluate(embed_bge, cv_bge_hf, BGE_FMT, qq)
qwen_res = evaluate(embed_qwen, cv_qwen, QWEN_FMT, qq)

for k, hit_key in [(1, "hit1"), (5, "hit5"), (10, "hit10")]:
    bge_hits = [r[hit_key] for r in bge_res]
    qwen_hits = [r[hit_key] for r in qwen_res]
    
    bge_ok = sum(bge_hits)
    qwen_ok = sum(qwen_hits)
    
    # Paired contingency
    both_correct = sum(1 for b, q in zip(bge_hits, qwen_hits) if b and q)
    bge_only = sum(1 for b, q in zip(bge_hits, qwen_hits) if b and not q)
    qwen_only = sum(1 for b, q in zip(bge_hits, qwen_hits) if not b and q)
    both_wrong = sum(1 for b, q in zip(bge_hits, qwen_hits) if not b and not q)
    
    # McNemar's test (exact binomial)
    n_discordant = bge_only + qwen_only
    if n_discordant > 0:
        p_val = 2 * sum(math.comb(n_discordant, i) * (0.5 ** n_discordant) 
                       for i in range(min(bge_only, qwen_only), n_discordant + 1))
        p_val = min(p_val, 1.0)  # Two-tailed
    else:
        p_val = 1.0
    
    diff = (bge_ok - qwen_ok) / len(bge_hits) * 100
    
    print(f"\n  Hit@{k}:")
    print(f"    BGE correct: {bge_ok}/{len(bge_hits)} ({bge_ok/len(bge_hits):.1%})")
    print(f"    Qwen correct: {qwen_ok}/{len(qwen_hits)} ({qwen_ok/len(qwen_hits):.1%})")
    print(f"    Diff: {diff:+.1f}pp")
    print(f"    Both correct: {both_correct}, BGE only: {bge_only}, Qwen only: {qwen_only}, Both wrong: {both_wrong}")
    print(f"    McNemar p-value: {p_val:.4f} {'(significant)' if p_val < 0.05 else '(not significant)'}")

# Bootstrap CI for MRR and nDCG
from numpy.random import default_rng

rng = default_rng(42)

def bootstrap_ci(bge_vals, qwen_vals, metric_name, n_resamples=10000):
    diffs = np.array(bge_vals) - np.array(qwen_vals)
    mean_diff = np.mean(diffs)
    
    boot_diffs = np.zeros(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, len(diffs), len(diffs))
        boot_diffs[i] = np.mean(diffs[idx])
    
    ci_low = np.percentile(boot_diffs, 2.5)
    ci_high = np.percentile(boot_diffs, 97.5)
    
    # p-value: proportion of boots where sign is opposite of observed
    if mean_diff > 0:
        p_val = np.mean(boot_diffs <= 0)
    else:
        p_val = np.mean(boot_diffs >= 0)
    
    print(f"  {metric_name}: BGE={np.mean(bge_vals):.4f} Qwen={np.mean(qwen_vals):.4f} Diff={mean_diff:+.4f}  95%CI=[{ci_low:.4f}, {ci_high:.4f}]  p={p_val:.4f}")

bge_mrr = [r["mrr"] for r in bge_res]
qwen_mrr = [r["mrr"] for r in qwen_res]
bge_ndcg = [r["ndcg"] for r in bge_res]
qwen_ndcg = [r["ndcg"] for r in qwen_res]
print("\n  Bootstrap 95% CI (10,000 resamples):")
bootstrap_ci(bge_mrr, qwen_mrr, "MRR@10")
bootstrap_ci(bge_ndcg, qwen_ndcg, "nDCG@10")

# ── 2. QWEN MATRYOSHKA ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("2. QWEN MATRYOSHKA (variable dimensions)")
print("=" * 70)

for dims in [4096, 2048, 1536, 1024, 512]:
    if dims == 4096:
        cv = cv_qwen
    else:
        cv = cv_qwen[:, :dims].copy()
        # Re-normalize
        norms = np.linalg.norm(cv, axis=1, keepdims=True).clip(min=1e-12)
        cv = cv / norms
    
    qwen_res_sub = evaluate(embed_qwen, cv, QWEN_FMT, qq, truncate_dims=dims)
    h1 = sum(r["hit1"] for r in qwen_res_sub) / len(qwen_res_sub)
    h5 = sum(r["hit5"] for r in qwen_res_sub) / len(qwen_res_sub)
    h10 = sum(r["hit10"] for r in qwen_res_sub) / len(qwen_res_sub)
    mr = sum(r["mrr"] for r in qwen_res_sub) / len(qwen_res_sub)
    nd = sum(r["ndcg"] for r in qwen_res_sub) / len(qwen_res_sub)
    storage = 4975 * dims * 4 / (1024*1024)
    print(f"  Qwen@{dims:4d}  hit@1={h1:.2%}  hit@5={h5:.2%}  hit@10={h10:.2%}  mrr={mr:.2%}  ndcg={nd:.2%}  storage={storage:.1f}MB")

# ── 3. HYBRID RETRIEVAL (RRF) ───────────────────────────────────────
print("\n" + "=" * 70)
print("3. HYBRID RETRIEVAL (RRF)")
print("=" * 70)

configs = [
    ("BGE dense",       embed_bge, cv_bge_hf, BGE_FMT, False),
    ("Qwen dense",      embed_qwen, cv_qwen, QWEN_FMT, False),
    ("BM25 only",       None, None, None, True),
    ("BGE + BM25 RRF",  embed_bge, cv_bge_hf, BGE_FMT, False),
    ("Qwen + BM25 RRF", embed_qwen, cv_qwen, QWEN_FMT, False),
    ("BGE dense-full",  embed_bge, cv_bge_hf[:, :], BGE_FMT, False),
]

for label, fn, cv, fmt, bm25_only in configs:
    res = evaluate(fn, cv, fmt, qq, use_bm25=bm25_only, use_hybrid=("RRF" in label and not bm25_only))
    h1 = sum(r["hit1"] for r in res) / len(res)
    h5 = sum(r["hit5"] for r in res) / len(res)
    h10 = sum(r["hit10"] for r in res) / len(res)
    mr = sum(r["mrr"] for r in res) / len(res)
    nd = sum(r["ndcg"] for r in res) / len(res)
    print(f"  {label:25s}  hit@1={h1:.2%}  hit@5={h5:.2%}  hit@10={h10:.2%}  mrr={mr:.2%}  ndcg={nd:.2%}")

# ── 4. CATEGORY BREAKDOWN ────────────────────────────────────────────
print("\n" + "=" * 70)
print("4. CATEGORY BREAKDOWN (per-query win/loss)")
print("=" * 70)

# Classify queries
def classify_query(q_text, rel_ids, corpus_dict):
    """Rough classification of query type."""
    text_lower = q_text.lower()
    if any(q_text.startswith(p) for p in ["class ", "def ", "async def "]):
        return "exact_identifier"
    if any(x in text_lower for x in ["function ", "method ", "class definition", "class named"]):
        return "exact_identifier"
    if any(x in text_lower for x in ["bug", "error", "fail", "exception", "crash", "fix"]):
        return "bug_description"
    if any(x in text_lower for x in ["architecture", "design", "pattern", "structure", "how does"]):
        return "architecture"
    if any(x in text_lower for x in ["config", "setting", "option", "parameter", "env"]):
        return "configuration"
    if any(x in text_lower for x in ["test", "assert", "pytest", "unittest"]):
        return "tests"
    if any(x in text_lower for x in ["call", "invoke", "use", "who uses", "caller"]):
        return "call_sites"
    return "conceptual_functionality"

c_dict = {c["id"]: c for c in corpus}
query_cats = [classify_query(q["query"], q["relevant"], c_dict) for q in qq]

from collections import defaultdict

cats = defaultdict(lambda: {"bge_hits": 0, "qwen_hits": 0, "total": 0})
for i, cat in enumerate(query_cats):
    cats[cat]["total"] += 1
    cats[cat]["bge_hits"] += int(bge_res[i]["hit10"])
    cats[cat]["qwen_hits"] += int(qwen_res[i]["hit10"])

for cat in sorted(cats):
    d = cats[cat]
    print(f"  {cat:30s}  n={d['total']:3d}  BGE@10={d['bge_hits']/d['total']:.0%}  Qwen@10={d['qwen_hits']/d['total']:.0%}")

# ── 5. RERANKER (if available) ──────────────────────────────────────
print("\n" + "=" * 70)
print("5. SHARED RERANKER (Qwen3-Reranker)")
print("=" * 70)

RERANK_MODEL = "qwen3-reranker:0.6b"
# Check if model exists
rr_avail = False
try:
    r = req.get(f"{OLLAMA_URL.replace('/api/embed', '/api/tags')}", timeout=5)
    models = [m["name"] for m in r.json().get("models", [])]
    rr_avail = any(RERANK_MODEL in m for m in models)
    print(f"  Model '{RERANK_MODEL}' available: {rr_avail}")
except:
    print("  Could not check model list")

if rr_avail:
    def rerank(query, candidates, top_k=20):
        pairs = [{"query": query, "document": c_dict[cid[idx]]["text"][:8000] if isinstance(cid[idx], str) else c_dict[cid[idx]]["text"][:8000]} 
                 for idx in candidates[:50]]
        # Re-rank via Ollama
        r = req.post(OLLAMA_URL.replace("/embed", "/rerank"), json={
            "model": RERANK_MODEL, "query": query,
            "documents": [p["document"] for p in pairs],
            "top_n": min(top_k, len(pairs)),
        }, timeout=60)
        r.raise_for_status()
        results = r.json().get("results", [])
        # Map back to chunk IDs
        reranked = [(candidates[r["index"]], r["relevance_score"]) for r in results]
        return reranked
    
    for label, fn, cv, fmt in [
        ("BGE → Reranker", embed_bge, cv_bge_hf, BGE_FMT),
        ("Qwen → Reranker", embed_qwen, cv_qwen, QWEN_FMT),
    ]:
        rr_hits = {1: [], 5: [], 10: []}; rr_rrs = []; rr_nds = []
        for qi, q in enumerate(qq[:50]):  # subset for speed
            rel = set(q["relevant"])
            # Initial retrieval: top 50
            qv = fn([fmt(q["query"])])
            scores = cv @ qv[0]
            top50 = [cid[i] for i in np.argsort(-scores)[:50]]
            
            # Rerank
            start = time.time()
            reranked = rerank(q["query"], top50, top_k=20)
            rtime = time.time() - start
            
            final_ranked = [item[0] for item in reranked]
            for k in rr_hits:
                topk = set(final_ranked[:k])
                rr_hits[k].append(float(bool(topk & rel)))
            for r, rid in enumerate(final_ranked[:10], 1):
                if rid in rel: rr_rrs.append(1.0/r); break
            else: rr_rrs.append(0.0)
            gains = [1 if rid in rel else 0 for rid in final_ranked[:10]]
            ideal_len = min(10, len(rel))
            d = sum(g / math.log2(i+2) for i, g in enumerate(gains))
            id_ = sum(1 / math.log2(i+2) for i in range(ideal_len))
            rr_nds.append(d / id_ if id_ else 0.0)
            
            if qi % 10 == 0:
                print(f"  {label}: {qi}/50 done, lat={rtime:.2f}s", flush=True)
        
        print(f"  {label:25s}  hit@1={statistics.mean(rr_hits[1]):.2%}  hit@5={statistics.mean(rr_hits[5]):.2%}  hit@10={statistics.mean(rr_hits[10]):.2%}  mrr={statistics.mean(rr_rrs):.2%}  ndcg={statistics.mean(rr_nds):.2%}")
else:
    print("  Skipping reranker test (model not available)")

print("\nDone.", flush=True)
