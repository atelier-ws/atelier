"""Tests for make_embedder() factory and all embedder backends."""

from __future__ import annotations

import pytest

from atelier.infra.embeddings.base import Embedder
from atelier.infra.embeddings.factory import make_embedder
from atelier.infra.embeddings.local import LocalEmbedder
from atelier.infra.embeddings.null_embedder import NullEmbedder
from atelier.infra.embeddings.openai_embedder import OpenAIEmbedder


def test_make_embedder_returns_local_in_stripped_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without OPENAI_API_KEY and Letta, default to the offline local embedder."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ATELIER_LETTA_URL", raising=False)
    monkeypatch.delenv("ATELIER_EMBEDDER", raising=False)

    import importlib
    import sys

    # Stub out sentence_transformers so it looks unavailable
    original = sys.modules.get("sentence_transformers")
    sys.modules["sentence_transformers"] = None  # type: ignore[assignment]
    try:
        e = make_embedder()
        assert isinstance(e, LocalEmbedder)
        assert isinstance(e, Embedder)
    finally:
        if original is None:
            sys.modules.pop("sentence_transformers", None)
        else:
            sys.modules["sentence_transformers"] = original
        importlib.invalidate_caches()


def test_make_embedder_null_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    e = make_embedder(pin="null")
    assert isinstance(e, NullEmbedder)


def test_make_embedder_openai_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinning to openai without OPENAI_API_KEY must raise."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises((ValueError, Exception)):
        make_embedder(pin="openai")


def test_make_embedder_env_pin_null(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_EMBEDDER", "null")
    e = make_embedder()
    assert isinstance(e, NullEmbedder)
    monkeypatch.delenv("ATELIER_EMBEDDER")


def test_make_embedder_bad_pin_raises() -> None:
    with pytest.raises(ValueError, match="Unknown embedder pin"):
        make_embedder(pin="bogus")


def test_openai_embedder_init_fails_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIEmbedder()


def test_all_embedders_satisfy_protocol() -> None:
    from atelier.infra.embeddings.letta_embedder import LettaEmbedder

    for cls in (NullEmbedder, LettaEmbedder, LocalEmbedder):
        instance = cls()
        assert isinstance(instance, Embedder), f"{cls.__name__} does not satisfy Embedder protocol"


def test_local_embedder_hash_fallback_without_sentence_transformers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib
    import sys

    original = sys.modules.get("sentence_transformers")
    sys.modules["sentence_transformers"] = None  # type: ignore[assignment]
    try:
        embedder = LocalEmbedder()
        vectors = embedder.embed(["checkout retry", "checkout retry"])
        assert len(vectors) == 2
        assert len(vectors[0]) == embedder.dim
        assert vectors[0] == vectors[1]
    finally:
        if original is None:
            sys.modules.pop("sentence_transformers", None)
        else:
            sys.modules["sentence_transformers"] = original
        importlib.invalidate_caches()


def test_null_embedder_dim_and_name() -> None:
    e = NullEmbedder()
    assert e.dim == 0
    assert e.name == "null"
