"""Vector search helpers for Atelier.

Controls whether vector similarity scoring is enabled, and provides
stub functions for embedding generation.

Environment variables:
    ATELIER_VECTOR_SEARCH_ENABLED   1 | true | yes  to enable (default: false)
    ATELIER_EMBEDDING_DIM           embedding dimension  (default: 1536)
    ATELIER_EMBEDDING_MODEL         model name hint  (default: text-embedding-3-small)
"""

from __future__ import annotations

import os
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
    dot: float = sum((x * y for x, y in zip(a, b)), 0.0)
    mag_a: float = sum((x * x for x in a), 0.0) ** 0.5
    mag_b: float = sum((x * x for x in b), 0.0) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def stub_embedding(text: str, *, dim: int | None = None) -> list[float]:
    """Return a deterministic stub embedding for offline/testing use.

    NOT suitable for production similarity search — use a real embedding
    model (e.g. OpenAI text-embedding-3-small) in production.
    """
    resolved_dim = dim or get_embedding_dim()
    # Simple deterministic hash-based stub
    h = hash(text)
    import hashlib

    digest = hashlib.sha256(text.encode()).digest()
    seed_bytes = list(digest)
    vec: list[float] = []
    for i in range(resolved_dim):
        b = seed_bytes[i % len(seed_bytes)]
        vec.append(float(b - 128) / 128.0)
    # Normalise to unit length
    mag = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / mag for x in vec]


__all__ = [
    "cosine_similarity",
    "get_embedding_dim",
    "get_embedding_model",
    "is_vector_enabled",
    "stub_embedding",
]
