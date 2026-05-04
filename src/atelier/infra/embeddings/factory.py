"""Embedding backend factory."""

from __future__ import annotations

import importlib
import os

from atelier.infra.embeddings.base import Embedder
from atelier.infra.embeddings.letta_embedder import LettaEmbedder
from atelier.infra.embeddings.local import LocalEmbedder
from atelier.infra.embeddings.null_embedder import NullEmbedder
from atelier.infra.embeddings.openai_embedder import OpenAIEmbedder

_PIN_CHOICES = frozenset({"local", "openai", "letta", "null"})


def make_embedder(*, pin: str | None = None) -> Embedder:
    """Return the most appropriate embedder.

    Selection order (override with ``ATELIER_EMBEDDER`` env var or ``pin``):

    1. Explicit pin (``pin`` arg or ``ATELIER_EMBEDDER`` env var):
       ``local`` | ``openai`` | ``letta`` | ``null``
    2. Letta sidecar available → ``LettaEmbedder``
    3. ``OPENAI_API_KEY`` set → ``OpenAIEmbedder``
    4. ``sentence_transformers`` importable → ``LocalEmbedder``
    5. Fallback → ``NullEmbedder``
    """
    chosen = (pin or os.environ.get("ATELIER_EMBEDDER", "")).strip().lower()

    if chosen:
        if chosen not in _PIN_CHOICES:
            raise ValueError(
                f"Unknown embedder pin {chosen!r}; must be one of {sorted(_PIN_CHOICES)}"
            )
        if chosen == "null":
            return NullEmbedder()
        if chosen == "local":
            return LocalEmbedder()
        if chosen == "openai":
            return OpenAIEmbedder()  # raises if OPENAI_API_KEY missing
        if chosen == "letta":
            return LettaEmbedder()

    # Auto-detect
    try:
        from atelier.infra.memory_bridges.letta_adapter import LettaAdapter

        if LettaAdapter.is_available():
            return LettaEmbedder()
    except Exception:
        pass

    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIEmbedder()

    if _importable("sentence_transformers"):
        return LocalEmbedder()

    return NullEmbedder()


def _importable(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


__all__ = [
    "LettaEmbedder",
    "LocalEmbedder",
    "NullEmbedder",
    "OpenAIEmbedder",
    "make_embedder",
]
