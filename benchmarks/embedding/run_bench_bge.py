"""
BGE-Code-v1 benchmark: function-level corpus, instruction-prefixed queries, dense-only.
Run while BGE is loaded in GPU (qwen3-embedding must be stopped).
"""
import json
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import requests as req

BASE = Path(__file__).parent / "data"
MODEL = "bge-code-v1-lasttoken"
OLLAMA_URL = "http://localhost:11434/api/embed"

def embed(texts: list[str], batch_size: int = 16) -> np.ndarray:
    """Batch embed via Ollama /api/embed."""
    show_progress = len(texts) > batch_size
    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        try:
            r = req.post(OLLAMA_URL, json={"model": MODEL, "input": batch}, timeout=120)
            r.raise_for_status()
            vecs = np.array(r.json()["embeddings"], dtype=np.float32)
            all_vecs.append(vecs)
        except Exception as e:
            print(f"  ERROR at batch {i}: {e}", flush=True)
            raise
        if show_progress and ((i + batch_size) % 500 == 0 or i == 0):
            print(f"  {i + len(batch)}/{len(texts)}", flush=True)
    return np.concatenate(all_vecs, axis=0)

def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))

def main():
    # Load corpus
    corpus = [json.loads(l) for l in open(BASE / "corpus.jsonl") if l.strip()]
    queries = [json.loads(l) for l in open(BASE / "queries.jsonl") if l.strip()]
    print(f"Corpus: {len(corpus)}  Queries: {len(queries)}", flush=True)

    # Load or embed corpus vectors
    cv_dir = BASE / "embeddings_bge"
    cv_dir.mkdir(parents=True, exist_ok=True)
    cv_path = cv_dir / "corpus.npy"
    if cv_path.exists():
        cv = np.load(cv_path)
        print(f"Loaded saved corpus embeddings: {cv.shape}", flush=True)
    else:
        print("Embedding corpus with BGE ...", flush=True)
        corp_texts = [c["text"] for c in corpus]
        cv = embed(corp_texts)
        np.save(cv_path, cv)
        print(f"Saved corpus embeddings ({cv.nbytes/1024/1024:.1f} MB, {cv.shape[1]}-dim)", flush=True)

    # Instruction prefix for BGE-Code-v1 queries (per model card)
    instruction = "Given a natural language query, retrieve relevant code."
    fmt = lambda q: f"<instruct>{instruction}\n<query>{q}"

    # Search with corrected metrics
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
    print()

    # Report
    hdr = f"{'Metric':<25}  BGE-Code-v1 ({len(corpus)}×{len(queries)})"
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
