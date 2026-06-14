"""Embedding backend factory."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Protocol, runtime_checkable

from atelier.core.environment import resolve_memory_backend
from atelier.core.foundation.paths import default_store_root

from .base import Embedder
from .letta_embedder import LettaEmbedder
from .local import LocalEmbedder
from .null_embedder import NullEmbedder
from .ollama_embedder import DEFAULT_CODE_EMBED_MODEL, OllamaEmbedder
from .openai_embedder import OpenAIEmbedder

logger = logging.getLogger(__name__)

_PIN_CHOICES = frozenset({"local", "openai", "letta", "null"})
_CODE_PIN_CHOICES = frozenset({"local", "openai", "letta", "null", "ollama"})


@runtime_checkable
class TaskAwareEmbedder(Protocol):
    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


def make_embedder(pin: str | None = None) -> Embedder:
    """Return the memory-path embedder without changing existing selection rules."""
    raw_choice = pin if pin is not None else (os.environ.get("ATELIER_EMBEDDER") or "")
    chosen = raw_choice.strip().lower()

    if chosen:
        if chosen not in _PIN_CHOICES:
            raise ValueError(f"Unknown embedder pin {chosen!r}; must be one of {sorted(_PIN_CHOICES)}")
        if chosen == "local":
            return LocalEmbedder()
        if chosen == "null":
            return NullEmbedder()
        if chosen == "openai":
            return OpenAIEmbedder()
        return LettaEmbedder()

    backend = resolve_memory_backend(root=default_store_root())
    if backend == "sqlite":
        return LocalEmbedder()
    if backend == "letta":
        try:
            from atelier.infra.memory_bridges.letta_adapter import LettaAdapter
        except ImportError:
            return LocalEmbedder()
        if LettaAdapter.is_available():
            return LettaEmbedder()
        logger.warning("Letta backend selected but sidecar is unavailable; falling back to local embedder")
        return LocalEmbedder()
    if backend == "openmemory" and os.environ.get("OPENAI_API_KEY"):
        return OpenAIEmbedder()
    return LocalEmbedder()


_embedder_singleton: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder_singleton
    if _embedder_singleton is None:
        _embedder_singleton = make_embedder()
    return _embedder_singleton


def embed_queries(embedder: Embedder, texts: list[str]) -> list[list[float]]:
    if isinstance(embedder, TaskAwareEmbedder):
        return embedder.embed_queries(texts)
    return embedder.embed(texts)


def embed_documents(embedder: Embedder, texts: list[str]) -> list[list[float]]:
    if isinstance(embedder, TaskAwareEmbedder):
        return embedder.embed_documents(texts)
    return embedder.embed(texts)


def _default_code_model(model: str | None = None) -> str:
    return (
        model or os.getenv("ATELIER_CODE_EMBED_MODEL") or DEFAULT_CODE_EMBED_MODEL
    ).strip() or DEFAULT_CODE_EMBED_MODEL


@lru_cache(maxsize=8)
def _make_available_ollama_code_embedder(model: str) -> OllamaEmbedder:
    embedder = OllamaEmbedder(model=model)
    if not embedder.is_available():
        raise RuntimeError(f"Ollama model {model!r} is unavailable")
    return embedder


def make_code_embedder(pin: str | None = None, model: str | None = None) -> Embedder:
    chosen = (pin or os.getenv("ATELIER_CODE_EMBEDDER") or os.getenv("ATELIER_EMBEDDER") or "").strip().lower()
    if chosen and chosen not in _CODE_PIN_CHOICES:
        raise ValueError(f"Unknown code embedder pin {chosen!r}; must be one of {sorted(_CODE_PIN_CHOICES)}")
    if chosen == "local":
        return LocalEmbedder()
    if chosen == "openai":
        return OpenAIEmbedder()
    if chosen == "letta":
        return LettaEmbedder()
    if chosen == "ollama":
        if os.getenv("ATELIER_OFFLINE"):
            return LocalEmbedder()
        try:
            return _make_available_ollama_code_embedder(_default_code_model(model))
        except RuntimeError:
            return LocalEmbedder()
    # Default (or explicit "null"): semantic code search is OFF unless an embedding
    # backend is configured via ATELIER_CODE_EMBEDDER (local|openai|letta|ollama) and
    # optionally ATELIER_CODE_EMBED_MODEL. No external LLM (ollama) is contacted by
    # default -- callers see the null embedder and surface "semantic unavailable".
    return NullEmbedder()


def get_code_embedder() -> Embedder:
    return make_code_embedder(
        pin=os.getenv("ATELIER_CODE_EMBEDDER") or os.getenv("ATELIER_EMBEDDER") or None,
        model=os.getenv("ATELIER_CODE_EMBED_MODEL") or None,
    )


def _clear_code_embedder_cache() -> None:
    _make_available_ollama_code_embedder.cache_clear()


make_code_embedder.cache_clear = _clear_code_embedder_cache  # type: ignore[attr-defined]


__all__ = [
    "DEFAULT_CODE_EMBED_MODEL",
    "LettaEmbedder",
    "LocalEmbedder",
    "NullEmbedder",
    "OllamaEmbedder",
    "OpenAIEmbedder",
    "embed_documents",
    "embed_queries",
    "get_code_embedder",
    "get_embedder",
    "make_code_embedder",
    "make_embedder",
]
