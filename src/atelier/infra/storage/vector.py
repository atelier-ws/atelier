"""Vector search helpers for Atelier.

Provides embedding generation and cosine similarity utilities used by retrieval.

Environment variables:
    ATELIER_VECTOR_SEARCH_ENABLED   1 | true | yes  to enable (default: false)
    ATELIER_EMBEDDING_DIM           embedding dimension (default: 1536)
    ATELIER_EMBEDDING_MODEL         model name hint (default: text-embedding-3-small)
    ATELIER_EMBEDDING_PROVIDER      local | openai (default: local)
    OPENAI_API_KEY                  required when provider=openai
"""

from __future__ import annotations

import os
import re
import urllib.request
from typing import Any

# Optional numpy for embedding math — not required at import time
_numpy: Any = None
try:
    import numpy as _numpy_module

    _numpy = _numpy_module
except ImportError:
    pass


def is_vector_enabled() -> bool:
    """Return True when ATELIER_VECTOR_SEARCH_ENABLED is truthy."""
    return os.environ.get("ATELIER_VECTOR_SEARCH_ENABLED", "false").lower() in (
        "1",
        "true",
        "yes",
    )


def get_embedding_dim() -> int:
    """Return the configured embedding dimension."""
    return int(os.environ.get("ATELIER_EMBEDDING_DIM", "1536"))


def get_embedding_model() -> str:
    """Return the configured embedding model name."""
    return os.environ.get("ATELIER_EMBEDDING_MODEL", "text-embedding-3-small")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [0, 1] between two vectors.

    Falls back to a pure-Python implementation when numpy is not installed.
    """
    if len(a) != len(b):
        raise ValueError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")
    if _numpy is not None:
        va = _numpy.array(a, dtype="float64")
        vb = _numpy.array(b, dtype="float64")
        norm_a = _numpy.linalg.norm(va)
        norm_b = _numpy.linalg.norm(vb)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(_numpy.dot(va, vb) / (norm_a * norm_b))

    # Pure-Python fallback
    dot: float = sum((x * y for x, y in zip(a, b, strict=True)), 0.0)
    mag_a: float = sum((x * x for x in a), 0.0) ** 0.5
    mag_b: float = sum((x * x for x in b), 0.0) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _normalize(vec: list[float]) -> list[float]:
    mag = sum(x * x for x in vec) ** 0.5
    if mag == 0.0:
        return vec
    return [x / mag for x in vec]


def _local_embedding(text: str, *, dim: int) -> list[float]:
    """Generate a deterministic local embedding via feature hashing.

    This is a real text vectorization strategy (hashing trick), fully offline.
    """
    import hashlib

    vec = [0.0] * dim
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    if not tokens:
        return vec

    for token in tokens:
        # add unigram contribution
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if (digest[4] & 1) else -1.0
        vec[idx] += sign

    # add lightweight character 3-gram contribution for semantic smoothness
    compact = "_".join(tokens)
    for i in range(max(0, len(compact) - 2)):
        ngram = compact[i : i + 3]
        digest = hashlib.sha256(ngram.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if (digest[5] & 1) else -1.0
        vec[idx] += 0.25 * sign

    return _normalize(vec)


def _openai_embedding(text: str, *, dim: int) -> list[float]:
    """Generate embeddings using OpenAI's embeddings API."""
    import json

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required when ATELIER_EMBEDDING_PROVIDER=openai")

    body = {
        "model": get_embedding_model(),
        "input": text,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError("OpenAI embeddings response missing data")
    embedding = data[0].get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError("OpenAI embeddings response missing embedding vector")

    vec = [float(x) for x in embedding]
    if len(vec) != dim:
        vec = vec[:dim] if len(vec) > dim else vec + [0.0] * (dim - len(vec))
    return _normalize(vec)


def generate_embedding(text: str, *, dim: int | None = None) -> list[float]:
    """Generate an embedding using configured provider.

    Provider selection:
      - local  (default): deterministic feature-hashing embedding
      - openai: OpenAI embeddings endpoint
    """
    resolved_dim = dim or get_embedding_dim()
    provider = os.environ.get("ATELIER_EMBEDDING_PROVIDER", "local").strip().lower()
    if provider == "openai":
        return _openai_embedding(text, dim=resolved_dim)
    return _local_embedding(text, dim=resolved_dim)


def stub_embedding(text: str, *, dim: int | None = None) -> list[float]:
    """Deterministic local embedding used for tests and offline flows."""
    resolved_dim = dim or get_embedding_dim()
    return _local_embedding(text, dim=resolved_dim)


__all__ = [
    "cosine_similarity",
    "generate_embedding",
    "get_embedding_dim",
    "get_embedding_model",
    "is_vector_enabled",
    "stub_embedding",
]
