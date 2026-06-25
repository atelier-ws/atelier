"""Compare embedding models via Ollama on the atelier codebase.

Usage:
    MODEL_B="bge-code-v1" python3 benchmarks/codebench/compare_embeddings.py

Uses benchmarks/codebench/corpus.jsonl and queries.jsonl (same for both models).
Results printed as a table.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/embed")

# ── Model configurations ──────────────────────────────────────────────
# Both models go through the same Ollama /api/embed endpoint.
# Corpus chunks are embedded WITHOUT the instruction prefix (plain code).
# Only queries get the instruct prefix — matches each model's official recipe.

MODELS = {
    "qwen3-embedding": {
        "label": "Qwen3-Embedding-8B",
        "name": os.getenv("MODEL_A", "qwen3-embedding:8b"),
        "format_query": lambda q: (
            "Instruct: Given a natural-language query, retrieve relevant "
            "source-code chunks from a software repository.\n"
            f"Query:{q}"
        ),
    },
    "bge-code": {
        "label": "BGE-Code-v1",
        "name": os.getenv("MODEL_B", "bge-code-v1"),
        "format_query": lambda q: (
            "<instruct>Given a natural-language query, retrieve relevant "
            "source-code chunks from a software repository.\n"
            f"<query>{q}"
        ),
    },
}


# ── Embed helpers ─────────────────────────────────────────────────────

def embed_batch_ollama(
    model: str,
    texts: list[str],
    batch_size: int = 16,
) -> tuple[np.ndarray, float]:
    """Embed via Ollama /api/embed. Returns (L2-normalized matrix, elapsed_s)."""
    vectors: list[list[float]] = []
    started = time.perf_counter()

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = requests.post(
            OLLAMA_URL,
            json={"model": model, "input": batch},
            timeout=600,
        )
        resp.raise_for_status()
        vectors.extend(resp.json()["embeddings"])

    elapsed = time.perf_counter() - started
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12), elapsed


def load_jsonl(path: str) -> list[dict[str, Any]]:
    records = []
    with Path(path).open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}, line {lineno}") from exc
    return records


# ── Metrics ───────────────────────────────────────────────────────────

def reciprocal_rank(ranked_ids: list[str], relevant: set[str], cutoff: int = 10) -> float:
    for rank, cid in enumerate(ranked_ids[:cutoff], 1):
        if cid in relevant:
            return 1.0 / rank
    return 0.0


def hit_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    """1 if any relevant doc in top-k, else 0."""
    return float(bool(set(ranked_ids[:k]) & relevant))


def recall_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    """Proportion of all relevant docs retrieved in top-k."""
    if not relevant:
        return 0.0
    retrieved_relevant = set(ranked_ids[:k]) & relevant
    return len(retrieved_relevant) / len(relevant)


def ndcg_at_k(
    ranked_ids: list[str],
    relevant: set[str],
    k: int = 10,
) -> float:
    def dcg(gains: list[int]) -> float:
        return sum(
            gain / math.log2(rank + 2)
            for rank, gain in enumerate(gains)
        )

    gains = [
        1 if item_id in relevant else 0
        for item_id in ranked_ids[:k]
    ]

    ideal_relevant_count = min(k, len(relevant))
    ideal_gains = [1] * ideal_relevant_count

    denominator = dcg(ideal_gains)
    return dcg(gains) / denominator if denominator else 0.0


# ── Evaluation ────────────────────────────────────────────────────────

def evaluate_model(
    key: str,
    config: dict[str, Any],
    corpus: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    per_query_wins: dict[str, int] | None,
    other_key: str | None,
    other_vectors: np.ndarray | None,
) -> dict[str, float] | tuple[dict[str, float], np.ndarray]:
    """Index corpus, score every query, return metrics dict + full corpus matrix.

    If *per_query_wins* and *other_vectors* are given, also tally per-query
    winner between this model and *other_key* into *per_query_wins*.
    """
    corpus_ids = [c["id"] for c in corpus]
    corpus_texts = [c["text"] for c in corpus]

    print(f"\n[{config['label']}] Indexing {len(corpus)} chunks …")
    t0 = time.perf_counter()
    corpus_vec, _ = embed_batch_ollama(config["name"], corpus_texts)
    idx_s = time.perf_counter() - t0
    dim = corpus_vec.shape[1]
    print(f"  dim={dim}, {corpus_vec.shape[0] / idx_s:.1f} chunks/s, {idx_s:.1f}s total")

    hits = {1: [], 5: [], 10: [], 20: []}
    recalls = {1: [], 5: [], 10: [], 20: []}
    rrs: list[float] = []
    ndcgs: list[float] = []
    lats: list[float] = []

    for qi, qrec in enumerate(queries):
        qtext = config["format_query"](qrec["query"])
        relevant = set(qrec["relevant"])

        t0 = time.perf_counter()
        qvec, _ = embed_batch_ollama(config["name"], [qtext], batch_size=1)
        lat = (time.perf_counter() - t0) * 1000

        scores = corpus_vec @ qvec[0]
        order = np.argsort(-scores)
        ranked = [corpus_ids[i] for i in order]

        for k in hits:
            hits[k].append(hit_at_k(ranked, relevant, k))
            recalls[k].append(recall_at_k(ranked, relevant, k))
        rrs.append(reciprocal_rank(ranked, relevant))
        ndcgs.append(ndcg_at_k(ranked, relevant))
        lats.append(lat)

        # Per-query comparison vs other model
        if per_query_wins is not None and other_vectors is not None:
            scores_b = other_vectors @ qvec[0]
            order_b = np.argsort(-scores_b)
            ranked_b = [corpus_ids[i] for i in order_b]
            rr_b = reciprocal_rank(ranked_b, relevant)

            rr_this = rrs[-1]
            if rr_this > rr_b:
                per_query_wins[key] += 1
            elif rr_b > rr_this:
                per_query_wins[other_key] += 1
            else:
                per_query_wins["tie"] += 1

        if (qi + 1) % 50 == 0:
            print(f"  {qi + 1}/{len(queries)} queries done")

    return {
        "dimensions": float(dim),
        "hit@1": statistics.mean(hits[1]),
        "hit@5": statistics.mean(hits[5]),
        "hit@10": statistics.mean(hits[10]),
        "recall@1": statistics.mean(recalls[1]),
        "recall@5": statistics.mean(recalls[5]),
        "recall@10": statistics.mean(recalls[10]),
        "recall@20": statistics.mean(recalls[20]),
        "mrr@10": statistics.mean(rrs),
        "ndcg@10": statistics.mean(ndcgs),
        "index_chunks_per_second": len(corpus) / idx_s,
        "query_latency_p50_ms": statistics.median(lats),
        "query_latency_p95_ms": float(np.percentile(lats, 95)),
        "estimated_vector_index_mb": corpus_vec.nbytes / 1024 / 1024,
    }, corpus_vec


def main() -> None:
    base = Path(__file__).resolve().parent
    corpus = load_jsonl(str(base / "corpus.jsonl"))
    queries = load_jsonl(str(base / "queries.jsonl"))
    print(f"Corpus: {len(corpus)} chunks  |  Queries: {len(queries)}")

    # Warm-up each model (load into GPU memory)
    print("\nWarming up …")
    for key, cfg in MODELS.items():
        embed_batch_ollama(cfg["name"], ["warmup"], batch_size=1)
        print(f"  {cfg['label']} ready")

    # ── Evaluate ──────────────────────────────────────────────────────
    keys = list(MODELS.keys())
    results: dict[str, dict[str, float]] = {}
    vectors: dict[str, np.ndarray] = {}

    # First model evaluated without per-query comparison
    res_a, vec_a = evaluate_model(keys[0], MODELS[keys[0]], corpus, queries,
                                   per_query_wins=None, other_key=None, other_vectors=None)
    results[keys[0]] = res_a
    vectors[keys[0]] = vec_a

    # Second model compared against the first
    per_query = {keys[0]: 0, keys[1]: 0, "tie": 0}
    res_b, vec_b = evaluate_model(keys[1], MODELS[keys[1]], corpus, queries,
                                   per_query_wins=per_query, other_key=keys[0],
                                   other_vectors=vectors[keys[0]])
    results[keys[1]] = res_b
    vectors[keys[1]] = vec_b

    # ── Results table ─────────────────────────────────────────────────
    label_a = MODELS[keys[0]]["label"]
    label_b = MODELS[keys[1]]["label"]
    print(f"\n{'=' * 70}")
    print(f"{'Metric':<30} {label_a:>18} {label_b:>18}")
    print(f"{'=' * 70}")

    metric_names = list(next(iter(results.values())).keys())
    for m in metric_names:
        va = results[keys[0]][m]
        vb = results[keys[1]][m]
        if m.startswith(("recall", "mrr", "ndcg")):
            print(f"{m:<30} {va:>17.2%} {vb:>17.2%}")
        elif "latency" in m:
            print(f"{m:<30} {va:>17.2f} {vb:>17.2f}")
        else:
            print(f"{m:<30} {va:>17.2f} {vb:>17.2f}")

    # ── Per-query wins ────────────────────────────────────────────────
    print(f"\n{'─' * 40}")
    print("Per-query win count (by MRR@10):")
    for k in keys:
        print(f"  {MODELS[k]['label']}: {per_query[k]} wins")
    print(f"  Tie: {per_query['tie']}")

    if per_query[keys[0]] > per_query[keys[1]]:
        print(f"\n→ Winner: {MODELS[keys[0]]['label']} "
              f"({per_query[keys[0]]} vs {per_query[keys[1]]})")
    elif per_query[keys[1]] > per_query[keys[0]]:
        print(f"\n→ Winner: {MODELS[keys[1]]['label']} "
              f"({per_query[keys[1]]} vs {per_query[keys[0]]})")
    else:
        print("\n→ Tie")


if __name__ == "__main__":
    main()
