"""
Quick smoke test: BGE-Code-v1 with fixed LAST_TOKEN pooling.
Only tests 200 queries to verify the fix works before running full benchmark.
"""
import json
import math
import statistics
import time
from pathlib import Path

import numpy as np
import requests as req

BASE = Path(__file__).parent / "data"
MODEL = "bge-code-v1-lasttoken"
OLLAMA_URL = "http://localhost:11434/api/embed"

def embed(texts, batch_size=16):
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        r = req.post(OLLAMA_URL, json={"model": MODEL, "input": batch}, timeout=120)
        r.raise_for_status()
        vecs = np.array(r.json()["embeddings"], dtype=np.float32)
        all_vecs.append(vecs)
    return np.concatenate(all_vecs, axis=0)

# Load corpus + 200 queries
corpus = [json.loads(l) for l in open(BASE / "corpus.jsonl") if l.strip()]
queries = [json.loads(l) for l in open(BASE / "queries.jsonl") if l.strip()][:200]
print(f"Corpus: {len(corpus)}  Queries: {len(queries)}", flush=True)

# Embed corpus
cv_dir = BASE / "embeddings_bge"
cv_dir.mkdir(parents=True, exist_ok=True)
cv_path = cv_dir / "corpus.npy"
if cv_path.exists():
    cv = np.load(cv_path)
    print(f"Loaded cached corpus: {cv.shape}", flush=True)
else:
    print("Embedding corpus...", flush=True)
    cv = embed([c["text"] for c in corpus])
    np.save(cv_path, cv)
    print(f"Saved corpus: {cv.shape}, {cv.nbytes/1024/1024:.1f} MB", flush=True)

# Instruction format (per BGE-Code-v1 model card):
#   query_instruction_format="<instruct>{}\n<query>{}"
instruction = "Given a natural language query, retrieve relevant code."
fmt = lambda q: f"<instruct>{instruction}\n<query>{q}"

# Metrics
cid = [c["id"] for c in corpus]
hits = {1: [], 5: [], 10: [], 20: []}
recalls = {1: [], 5: [], 10: [], 20: []}
rrs, nds, lats = [], [], []

for qi, q in enumerate(queries):
    rel = set(q["relevant"])
    qtext = fmt(q["query"])
    t0 = time.perf_counter()
    qv = embed([qtext])
    lat = (time.perf_counter() - t0) * 1000
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
    lats.append(lat)
    if (qi+1) % 50 == 0 or qi == 0:
        avg_h1 = statistics.mean(hits[1])
        print(f"  query {qi+1}/{len(queries)}  hit@1={avg_h1:.2%}  last={hits[1][-1]}", flush=True)

print(f"\n  query {len(queries)}/{len(queries)}  hit@1={statistics.mean(hits[1]):.2%}", flush=True)

print("\n" + "="*60)
print("BGE-Code-v1 (fixed LAST_TOKEN) — 200 query smoke test")
print("="*60)
print(f"  hit@1    = {statistics.mean(hits[1]):.4f}  ({statistics.mean(hits[1]):.2%})")
print(f"  hit@5    = {statistics.mean(hits[5]):.4f}  ({statistics.mean(hits[5]):.2%})")
print(f"  hit@10   = {statistics.mean(hits[10]):.4f}  ({statistics.mean(hits[10]):.2%})")
print(f"  recall@1 = {statistics.mean(recalls[1]):.4f}  ({statistics.mean(recalls[1]):.2%})")
print(f"  recall@5 = {statistics.mean(recalls[5]):.4f}  ({statistics.mean(recalls[5]):.2%})")
print(f"  mrr@10   = {statistics.mean(rrs):.4f}  ({statistics.mean(rrs):.2%})")
print(f"  ndcg@10  = {statistics.mean(nds):.4f}  ({statistics.mean(nds):.2%})")
print(f"  latency  = {statistics.median(lats):.1f}ms p50 / {np.percentile(lats, 95):.1f}ms p95")
print(f"  dims     = {cv.shape[1]}")
print()
