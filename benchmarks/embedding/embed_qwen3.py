"""Embed full corpus + queries with Qwen3-Embedding-8B via Ollama.

Output (under benchmarks/embedding/data/):
  corpus.jsonl              — input corpus (already exists)
  corpus_meta.json          — metadata
  embeddings_qwen3/         — sharded .npy files, each 1000 vectors
    shard_0000.npy
    shard_0001.npy
    ...
  queries_qwen3.npy         — query embeddings (all queries, single file)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/embed")
MODEL = "qwen3-embedding:8b"
DATA = Path(__file__).resolve().parent / "data"
BATCH_SIZE = 32
SHARD_SIZE = 1000


def embed(texts: list[str]) -> np.ndarray:
    """Embed a list of texts via Ollama, return L2-normalized float32 matrix."""
    vecs: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "input": batch},
            timeout=600,
        )
        resp.raise_for_status()
        vecs.extend(resp.json()["embeddings"])
        if (i + BATCH_SIZE) % 200 == 0 or i + BATCH_SIZE >= len(texts):
            print(f"  embedded {min(i+BATCH_SIZE, len(texts))}/{len(texts)}")
    m = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(norms, 1e-12)


def save_sharded(matrix: np.ndarray, out_dir: Path, prefix: str):
    """Save matrix as sharded .npy files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n = matrix.shape[0]
    n_shards = (n + SHARD_SIZE - 1) // SHARD_SIZE
    for shard in range(n_shards):
        a, b = shard * SHARD_SIZE, min((shard + 1) * SHARD_SIZE, n)
        path = out_dir / f"{prefix}_{shard:04d}.npy"
        np.save(path, matrix[a:b])
    print(f"  saved {n} vectors across {n_shards} shards in {out_dir}/")

    # Write shard manifest
    manifest = {
        "model": MODEL,
        "dimensions": matrix.shape[1],
        "total_vectors": n,
        "shard_size": SHARD_SIZE,
        "num_shards": n_shards,
        "files": [f"{prefix}_{i:04d}.npy" for i in range(n_shards)],
    }
    with open(out_dir / f"{prefix}_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  wrote {out_dir / f'{prefix}_manifest.json'}")


def main():
    # Load corpus
    corpus_path = DATA / "corpus.jsonl"
    corpus = [json.loads(l) for l in open(corpus_path) if l.strip()]
    print(f"Corpus: {len(corpus)} chunks")

    # Embed corpus
    print(f"Embedding corpus with {MODEL} ...")
    t0 = time.perf_counter()
    corpus_vecs = embed([c["text"] for c in corpus])
    t_corpus = time.perf_counter() - t0
    print(f"  {len(corpus_vecs)} vectors, dim={corpus_vecs.shape[1]}, "
          f"{t_corpus:.1f}s ({len(corpus)/t_corpus:.1f} chunks/s)")

    # Save corpus embeddings as shards
    out_dir = DATA / "embeddings_qwen3"
    save_sharded(corpus_vecs, out_dir, "shard")
    print(f"  total size: {corpus_vecs.nbytes / 1024 / 1024:.1f} MB")

    # Load and embed queries
    queries_path = DATA / "queries.jsonl"
    queries = [json.loads(l) for l in open(queries_path) if l.strip()]
    print(f"\nQueries: {len(queries)}")

    instruct_prefix = (
        "Instruct: Given a natural-language query, retrieve relevant "
        "source-code chunks from a software repository.\n"
        "Query:"
    )
    query_texts = [instruct_prefix + q["query"] for q in queries]

    print(f"Embedding queries with {MODEL} ...")
    t0 = time.perf_counter()
    query_vecs = embed(query_texts)
    t_q = time.perf_counter() - t0
    print(f"  {t_q:.1f}s ({len(queries)/t_q:.1f} queries/s)")

    # Save query embeddings
    qpath = DATA / "queries_qwen3.npy"
    np.save(qpath, query_vecs)
    print(f"  saved {qpath} ({query_vecs.nbytes/1024:.1f} KB)")

    # Save queries metadata
    meta = {
        "num_queries": len(queries),
        "model": MODEL,
        "dimensions": query_vecs.shape[1],
    }
    with open(DATA / "queries_qwen3_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Write a summary
    print(f"\n{'='*50}")
    print(f"Done. Files in {DATA}/:")
    for p in sorted(DATA.iterdir()):
        if p.is_dir():
            sz = sum(f.stat().st_size for f in p.iterdir() if f.is_file())
            print(f"  {p.name}/  ({sz/1024/1024:.1f} MB)")
        else:
            print(f"  {p.name}  ({p.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
