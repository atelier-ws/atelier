"""Benchmark Qwen3-Embedding-8B on full corpus + queries."""
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/embed")
MODEL = "qwen3-embedding:8b"
BASE = Path(__file__).resolve().parent / "data"
BATCH = 16


def embed(texts, label=None):
    vecs = []
    n = len(texts)
    for i in range(0, n, BATCH):
        batch = texts[i : i + BATCH]
        r = requests.post(OLLAMA_URL, json={"model": MODEL, "input": batch}, timeout=120)
        r.raise_for_status()
        vecs.extend(r.json()["embeddings"])
        done = min(i + BATCH, n)
        if n > 1:
            sys.stdout.write(f"\r{label or 'embed'} {done}/{n}")
            sys.stdout.flush()
    if n > 1:
        sys.stdout.write("\n")
    m = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(norms, 1e-12)


def main():
    corpus = [json.loads(l) for l in open(BASE / "corpus.jsonl") if l.strip()]
    queries = [json.loads(l) for l in open(BASE / "queries.jsonl") if l.strip()]
    print(f"Corpus: {len(corpus)}  Queries: {len(queries)}", flush=True)

    fmt = lambda q: (
        "Instruct: Given a natural-language query, retrieve relevant "
        "source-code chunks from a software repository.\n"
        f"Query:{q}"
    )

    # ── Index ──────────────────────────────────────────────────────
    print("Indexing corpus ...", flush=True)
    t0 = time.perf_counter()
    cv = embed([c["text"] for c in corpus], label="corpus")
    idx_s = time.perf_counter() - t0
    print(f"  dim={cv.shape[1]}  {len(corpus)/idx_s:.1f} ch/s  {idx_s:.1f}s", flush=True)

    # Save corpus vectors
    (BASE / "embeddings_qwen3").mkdir(parents=True, exist_ok=True)
    np.save(BASE / "embeddings_qwen3" / "corpus.npy", cv)
    print(f"  saved corpus embeddings ({cv.nbytes/1024/1024:.1f} MB)", flush=True)

    # ── Search ─────────────────────────────────────────────────────
    cid = [c["id"] for c in corpus]
    hits = {1: [], 5: [], 10: [], 20: []}
    recalls = {1: [], 5: [], 10: [], 20: []}
    rrs, nds, lats = [], [], []

    def dcg(gains):
        return sum(g / math.log2(i + 2) for i, g in enumerate(gains))

    for qi, q in enumerate(queries):
        rel = set(q["relevant"])
        t0 = time.perf_counter()
        qv = embed([fmt(q["query"])])
        lat = (time.perf_counter() - t0) * 1000
        if (qi + 1) % 100 == 0 or qi == 0:
            sys.stdout.write(f"\rquery {qi+1}/{len(queries)}")
            sys.stdout.flush()
        scores = cv @ qv[0]
        order = np.argsort(-scores)
        ranked = [cid[i] for i in order]

        for k in hits:
            hits[k].append(float(bool(set(ranked[:k]) & rel)))
            if rel:
                recalls[k].append(len(set(ranked[:k]) & rel) / len(rel))
            else:
                recalls[k].append(0.0)
        for r, rid in enumerate(ranked[:10], 1):
            if rid in rel:
                rrs.append(1.0 / r)
                break
        else:
            rrs.append(0.0)
        gains = [1 if rid in rel else 0 for rid in ranked[:10]]
        ideal_count = min(10, len(rel))
        d = dcg(gains)
        idcg = dcg([1] * ideal_count)
        nds.append(d / idcg if idcg else 0.0)
        lats.append(lat)

    sys.stdout.write("\n")

    # ── Report ─────────────────────────────────────────────────────
    print()
    hdr = f"{'Metric':<25}  Qwen3-Embedding-8B ({len(corpus)}×{len(queries)})"
    print("=" * 60)
    print(hdr)
    print("=" * 60)
    for metric in [
        "hit@1", "hit@5", "hit@10",
        "recall@1", "recall@5", "recall@10", "recall@20",
        "mrr@10", "ndcg@10",
    ]:
        mtype, k = metric.split("@")
        k = int(k)
        if mtype == "hit":
            v = statistics.mean(hits[k])
        elif mtype == "recall":
            v = statistics.mean(recalls[k])
        elif metric == "mrr@10":
            v = statistics.mean(rrs)
        elif metric == "ndcg@10":
            v = statistics.mean(nds)
        else:
            continue
        print(f"  {metric:<25} {v:.4f}  ({v:.2%})")
    print(f"  {'latency_p50_ms':<25} {statistics.median(lats):.1f}")
    print(f"  {'latency_p95_ms':<25} {np.percentile(lats, 95):.1f}")
    print(f"  {'dimensions':<25} {cv.shape[1]}")
    print(f"  {'index_size_mb':<25} {cv.nbytes/1024/1024:.1f}")
    print()


if __name__ == "__main__":
    main()
