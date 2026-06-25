"""Re-run Qwen3 benchmark with corrected metrics using saved embeddings."""
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


def embed(texts, batch_size=16):
    vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        r = requests.post(OLLAMA_URL, json={"model": MODEL, "input": batch}, timeout=120)
        r.raise_for_status()
        vecs.extend(r.json()["embeddings"])
        done = min(i + batch_size, len(texts))
        if len(texts) > 1:
            sys.stdout.write(f"\rembed {done}/{len(texts)}")
            sys.stdout.flush()
    if len(texts) > 1:
        sys.stdout.write("\n")
    m = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(norms, 1e-12)


def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def main():
    # Load corpus
    corpus = [json.loads(l) for l in open(BASE / "corpus.jsonl") if l.strip()]
    queries = [json.loads(l) for l in open(BASE / "queries.jsonl") if l.strip()]
    print(f"Corpus: {len(corpus)}  Queries: {len(queries)}", flush=True)

    # Load or embed corpus vectors
    cv_path = BASE / "embeddings_qwen3" / "corpus.npy"
    if cv_path.exists():
        cv = np.load(cv_path)
        print(f"Loaded saved corpus embeddings: {cv.shape}", flush=True)
    else:
        print("Embedding corpus ...", flush=True)
        cv = embed([c["text"] for c in corpus])
        (BASE / "embeddings_qwen3").mkdir(parents=True, exist_ok=True)
        np.save(cv_path, cv)
        print(f"Saved corpus embeddings ({cv.nbytes/1024/1024:.1f} MB)", flush=True)

    fmt = lambda q: (
        "Instruct: Given a natural-language query, retrieve relevant "
        "source-code chunks from a software repository.\n"
        f"Query:{q}"
    )

    # Search with corrected metrics
    cid = [c["id"] for c in corpus]
    hits = {1: [], 5: [], 10: [], 20: []}
    recalls = {1: [], 5: [], 10: [], 20: []}
    rrs, nds, lats = [], [], []

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
            topk = set(ranked[:k])
            hits[k].append(float(bool(topk & rel)))
            if rel:
                recalls[k].append(len(topk & rel) / len(rel))
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
        d_val = dcg(gains)
        id_val = dcg([1] * ideal_count)
        nds.append(d_val / id_val if id_val else 0.0)
        lats.append(lat)

    sys.stdout.write("\n")

    # Report
    print()
    hdr = f"{'Metric':<25}  Qwen3-Embedding-8B ({len(corpus)}×{len(queries)})"
    print("=" * 60)
    print(hdr)
    print("=" * 60)
    for metric in [
        "hit@1", "hit@5", "hit@10", "hit@20",
        "recall@1", "recall@5", "recall@10", "recall@20",
        "mrr@10", "ndcg@10",
    ]:
        if metric.startswith("hit"):
            v = statistics.mean(hits[int(metric.split("@")[1])])
        elif metric.startswith("recall"):
            v = statistics.mean(recalls[int(metric.split("@")[1])])
        elif metric == "mrr@10":
            v = statistics.mean(rrs)
        elif metric == "ndcg@10":
            v = statistics.mean(nds)
        print(f"  {metric:<25} {v:.4f}  ({v:.2%})")
    print(f"  {'latency_p50_ms':<25} {statistics.median(lats):.1f}")
    print(f"  {'latency_p95_ms':<25} {np.percentile(lats, 95):.1f}")
    print(f"  {'dimensions':<25} {cv.shape[1]}")
    print(f"  {'index_size_mb':<25} {cv.nbytes/1024/1024:.1f}")
    print()


if __name__ == "__main__":
    main()
