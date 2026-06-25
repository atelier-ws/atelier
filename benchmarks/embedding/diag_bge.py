"""
Diagnostic: self-retrieval + batch invariance + vector statistics for BGE-Code-v1.
"""
import json
import os

import numpy as np
import requests as req

BASE = os.path.join(os.path.dirname(__file__), "data")
MODEL = "bge-code-v1"
OLLAMA_URL = "http://localhost:11434/api/embed"

def embed(texts):
    r = req.post(OLLAMA_URL, json={"model": MODEL, "input": texts}, timeout=120)
    r.raise_for_status()
    return np.array(r.json()["embeddings"], dtype=np.float32)

# ── 1. Load corpus ──────────────────────────────────────────────
corpus = [json.loads(l) for l in open(os.path.join(BASE, "corpus.jsonl")) if l.strip()]
print(f"Corpus: {len(corpus)} chunks", flush=True)

# Take 100 chunks for self-retrieval test
chunks = corpus[:100]
texts = [c["text"] for c in chunks]
ids = [c["id"] for c in chunks]
print(f"Self-retrieval: {len(chunks)} chunks", flush=True)

# ── 2. Embed corpus chunks (no instruction prefix, just raw text) ──
print("Embedding corpus chunks...", flush=True)
cv = embed(texts)
print(f"  shape: {cv.shape}", flush=True)

# ── 3. Self-retrieval: re-embed exact same text and search ──────
print("\nSelf-retrieval test:", flush=True)
hits_at_1 = 0
for i in range(100):
    qv = embed([texts[i]])
    scores = cv @ qv[0]
    top = np.argmax(scores)
    if top == i:
        hits_at_1 += 1

print(f"  hit@1 = {hits_at_1}/100 = {hits_at_1}%", flush=True)
print("  (expected: 100% if pipeline is correct)", flush=True)

# ── 4. Batch invariance test ────────────────────────────────────
print("\nBatch invariance test:", flush=True)
# Embed alone
a = embed(["function validateJwt(token) checks token expiration"])[0]
# Embed in batch with different-length neighbors
batch = embed([
    "short",
    "function validateJwt(token) checks token expiration",
    "This is a substantially longer piece of source code and documentation used to change padding"
])[1]
cos = np.dot(a, batch) / (np.linalg.norm(a) * np.linalg.norm(batch))
print(f"  cosine(alone, batch[1]) = {cos:.6f}")
print("  (expected: >0.999 if pooling is correct)", flush=True)

# ── 5. Vector statistics ────────────────────────────────────────
print("\nVector statistics:", flush=True)
norms = np.linalg.norm(cv, axis=1)
print(f"  norm mean: {norms.mean():.6f}")
print(f"  norm min:  {norms.min():.6f}")
print(f"  norm max:  {norms.max():.6f}")
print(f"  dim std mean: {cv.std(axis=0).mean():.6f}")

# Pairwise cosine
sample = cv[:500]
sim = sample @ sample.T
mask = ~np.eye(len(sample), dtype=bool)
off = sim[mask]
print(f"  mean pairwise cosine: {off.mean():.6f}")
print(f"  p95 pairwise cosine:  {np.percentile(off, 95):.6f}")
print(f"  unique (rounded to 5dp): {len(np.unique(np.round(sample, 5), axis=0))} / {len(sample)}")

# ── 6. Check first few embeddings for zeros/NaNs ────────────────
print(f"\n  zeros: {np.count_nonzero(np.all(cv == 0, axis=1))} / {len(cv)}")
print(f"  NaNs:  {np.count_nonzero(np.any(np.isnan(cv), axis=1))} / {len(cv)}")

print("\nDone.", flush=True)
