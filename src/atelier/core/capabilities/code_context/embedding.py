"""Semantic ranking helpers for mode-aware code search."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from atelier.core.capabilities.code_context.models import SymbolRecord
from atelier.core.foundation.paths import default_store_root
from atelier.infra.embeddings.base import Embedder
from atelier.infra.embeddings.factory import (
    embed_documents,
    embed_queries,
    get_code_embedder,
)
from atelier.infra.storage.vector import (
    cosine_similarity,
    get_cached_embedding,
    put_cached_embedding,
    vector_cache_key,
)

SearchMode = Literal["auto", "lexical", "semantic", "hybrid"]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:.]*$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_STOP_WORDS = frozenset({"a", "an", "for", "how", "in", "of", "the", "to", "with"})
_DEFAULT_RRF_K = 60
_DEFAULT_CANDIDATE_LIMIT = 200
_DEFAULT_EMBED_BATCH_SIZE = 64

# N12: per-signal weights for the BM25(lexical) + semantic + graph RRF blend.
# Env overrides (opt-in, WS6 ATELIER_* style):
_WEIGHT_ENV = {
    "lexical": "ATELIER_FUSION_WEIGHT_LEXICAL",
    "semantic": "ATELIER_FUSION_WEIGHT_SEMANTIC",
    "graph": "ATELIER_FUSION_WEIGHT_GRAPH",
}


@dataclass(frozen=True)
class FusionWeights:
    """Tunable per-signal weights for tri-signal reciprocal-rank fusion (N12).

    Each signal's RRF contribution ``1/(k+rank)`` is scaled by its weight before
    summation. Defaults reproduce today's two-signal behaviour exactly: lexical
    and semantic both weight 1.0 (so the blend is identical to the prior
    ``1/(k+rank)`` sum) and graph weights 0.0 (the third signal is a no-op until
    a caller supplies graph hits AND a non-zero weight). Override per-process via
    ``ATELIER_FUSION_WEIGHT_{LEXICAL,SEMANTIC,GRAPH}`` or per-call via the
    ``weights`` argument -- so weight tuning never silently shifts existing
    rankings.
    """

    lexical: float = 1.0
    semantic: float = 1.0
    graph: float = 0.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> FusionWeights:
        """Build weights from ``ATELIER_FUSION_WEIGHT_*``; defaults reproduce baseline."""
        values = os.environ if env is None else env
        defaults = cls()
        resolved: dict[str, float] = {}
        for field_name, env_name in _WEIGHT_ENV.items():
            raw = values.get(env_name, "").strip()
            current = getattr(defaults, field_name)
            if not raw:
                resolved[field_name] = current
                continue
            try:
                resolved[field_name] = float(raw)
            except ValueError:
                # Robust to garbage env: fall back to the baseline weight.
                resolved[field_name] = current
        return cls(**resolved)


@dataclass
class _FusionEntry:
    symbol: SymbolRecord
    score: float
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    graph_rank: int | None = None


def is_identifier_query(query: str) -> bool:
    """Return True when the query looks like a symbol identifier."""
    stripped = query.strip()
    return bool(stripped) and bool(_IDENTIFIER_RE.fullmatch(stripped))


def looks_natural_language_query(query: str) -> bool:
    """Return True when the query should auto-promote to hybrid search."""
    tokens = [token.lower() for token in _TOKEN_RE.findall(query)]
    return " " in query.strip() or any(token in _STOP_WORDS for token in tokens)


def resolve_search_mode(query: str, requested_mode: SearchMode) -> Literal["lexical", "semantic", "hybrid"]:
    """Resolve the effective search mode for a query."""
    if requested_mode != "auto":
        return requested_mode
    if is_identifier_query(query):
        return "lexical"
    if looks_natural_language_query(query):
        return "hybrid"
    return "lexical"


def semantic_candidate_limit(limit: int) -> int:
    """Cap semantic candidate generation to protect search latency."""
    return max(limit, min(_DEFAULT_CANDIDATE_LIMIT, max(limit * 5, 25)))


def resolve_embed_batch_size() -> int:
    """Documents per ``embed_documents`` call during batch symbol prewarm.

    Overridable via ``ATELIER_EMBED_BATCH_SIZE``; falls back to the default on
    missing/garbage values. Batching collapses a cold prewarm of N symbols from
    N model calls to ``ceil(N / batch)``.
    """
    raw = os.environ.get("ATELIER_EMBED_BATCH_SIZE", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return _DEFAULT_EMBED_BATCH_SIZE
        if value > 0:
            return value
    return _DEFAULT_EMBED_BATCH_SIZE


def render_embedding_text(symbol: SymbolRecord, *, source_text: str | None = None) -> str:
    """Render the text used to embed a symbol."""
    source = (source_text or "").strip().replace("\x00", " ")
    if len(source) > 200:
        source = source[:200]
    parts = [symbol.symbol_name, symbol.signature]
    if symbol.doc_summary:
        parts.append(symbol.doc_summary)
    elif source:
        parts.append(source)
    return "\n".join(part for part in parts if part).strip()


class SemanticSearchRanker:
    """Semantic ranking for symbol search using the code-specific embedder path."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        store_root: str | Path | None = None,
        embedder: Embedder | None = None,
        rrf_k: int = _DEFAULT_RRF_K,
        fusion_weights: FusionWeights | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.store_root = Path(store_root) if store_root is not None else default_store_root()
        self.embedder = embedder if embedder is not None else get_code_embedder()
        self.rrf_k = rrf_k
        # N12: resolve once from env (defaults reproduce baseline ranking).
        self.fusion_weights = fusion_weights if fusion_weights is not None else FusionWeights.from_env()

    @property
    def available(self) -> bool:
        """True only when a real embedding backend is configured (not the null embedder)."""
        return getattr(self.embedder, "name", "") != "null" and int(getattr(self.embedder, "dim", 0)) > 0

    def semantic_search(
        self,
        query: str,
        *,
        candidates: Sequence[SymbolRecord],
        limit: int,
        source_loader: Callable[[SymbolRecord], str],
    ) -> list[SymbolRecord]:
        """Rank candidate symbols by cosine similarity to the query embedding."""
        query_vector = self._embed_query(query)
        if not query_vector:
            return []

        scored: list[tuple[float, SymbolRecord]] = []
        for symbol in candidates:
            source_text = source_loader(symbol)
            embedding_text = render_embedding_text(symbol, source_text=source_text)
            if not embedding_text:
                continue
            symbol_vector = self._embed_symbol(symbol, embedding_text)
            if not symbol_vector:
                continue
            score = cosine_similarity(query_vector, symbol_vector)
            if score <= 0:
                continue
            scored.append((score, symbol.model_copy(update={"score": score})))

        scored.sort(key=lambda item: (-item[0], item[1].file_path, item[1].start_line))
        return [symbol for _, symbol in scored[:limit]]

    def reciprocal_rank_fuse(
        self,
        lexical_hits: Sequence[SymbolRecord],
        semantic_hits: Sequence[SymbolRecord],
        *,
        limit: int,
        graph_hits: Sequence[SymbolRecord] | None = None,
        weights: FusionWeights | None = None,
    ) -> list[SymbolRecord]:
        """Fuse lexical + semantic (+ optional graph) rankings with weighted RRF.

        N12: each signal's reciprocal-rank contribution ``1/(k+rank)`` is scaled
        by its per-signal weight before summation. ``weights=None`` falls back to
        this ranker's ``fusion_weights`` (resolved once from
        ``ATELIER_FUSION_WEIGHT_*`` at construction; default lexical=1.0,
        semantic=1.0, graph=0.0), so existing call sites stay byte-identical
        unless those env knobs are set. The ``graph_hits`` signal is a no-op
        unless callers pass it AND a non-zero graph weight.
        """
        effective = weights if weights is not None else self.fusion_weights
        fused: dict[str, _FusionEntry] = {}
        for rank, symbol in enumerate(lexical_hits, start=1):
            entry = fused.setdefault(
                symbol.symbol_id,
                _FusionEntry(symbol=symbol, score=0.0, lexical_rank=rank),
            )
            entry.score += effective.lexical * (1.0 / (self.rrf_k + rank))
        for rank, symbol in enumerate(semantic_hits, start=1):
            entry = fused.setdefault(
                symbol.symbol_id,
                _FusionEntry(symbol=symbol, score=0.0, semantic_rank=rank),
            )
            entry.score += effective.semantic * (1.0 / (self.rrf_k + rank))
            if entry.lexical_rank is None:
                entry.symbol = symbol
            entry.semantic_rank = rank
        for rank, symbol in enumerate(graph_hits or (), start=1):
            entry = fused.setdefault(
                symbol.symbol_id,
                _FusionEntry(symbol=symbol, score=0.0, graph_rank=rank),
            )
            entry.score += effective.graph * (1.0 / (self.rrf_k + rank))
            if entry.lexical_rank is None and entry.semantic_rank is None:
                entry.symbol = symbol
            entry.graph_rank = rank

        ordered = sorted(
            fused.values(),
            key=lambda entry: (
                -entry.score,
                entry.semantic_rank or 10_000,
                entry.lexical_rank or 10_000,
                entry.symbol.file_path,
                entry.symbol.start_line,
            ),
        )
        return [entry.symbol.model_copy(update={"score": entry.score}) for entry in ordered[:limit]]

    def embed_query(self, query: str) -> list[float]:
        """Public query-embedding entry point (cached). Empty list when disabled."""
        return self._embed_query(query)

    def embed_symbol(self, symbol: SymbolRecord, *, source_text: str | None = None) -> list[float]:
        """Public symbol-embedding entry point (cached) for the ANN store.

        Renders the same embedding text as :meth:`semantic_search` so the
        persisted ANN vectors and the brute-force fallback stay in one vector
        space. Returns an empty list when the embedder is disabled or the symbol
        renders no text.
        """
        embedding_text = render_embedding_text(symbol, source_text=source_text)
        if not embedding_text:
            return []
        return self._embed_symbol(symbol, embedding_text)

    def embed_symbols(
        self,
        symbols: Sequence[SymbolRecord],
        *,
        source_texts: Mapping[str, str | None] | None = None,
    ) -> dict[str, list[float]]:
        """Batch-embed *symbols*, returning ``{symbol_id: vector}``.

        Reuses the per-symbol vector cache and batches the uncached documents
        into chunked ``embed_documents`` calls, so a cold prewarm makes
        ``ceil(N / batch)`` model calls instead of one per symbol. Vectors are
        byte-identical to :meth:`embed_symbol` (same cache key and embedding
        text), so callers may mix the two freely.
        """
        results: dict[str, list[float]] = {}
        if self.embedder.dim <= 0:
            return results
        texts = source_texts or {}
        pending_texts: list[str] = []
        pending_meta: list[tuple[str, str]] = []  # (symbol_id, cache_key)
        for symbol in symbols:
            embedding_text = render_embedding_text(symbol, source_text=texts.get(symbol.symbol_id))
            if not embedding_text:
                continue
            cache_key = vector_cache_key(
                symbol.symbol_id, f"{self.embedder.name}:{symbol.content_hash}:{embedding_text}"
            )
            cached = get_cached_embedding(self.store_root, cache_key=cache_key, embedder_name=self.embedder.name)
            if cached is not None:
                results[symbol.symbol_id] = cached
                continue
            pending_texts.append(embedding_text)
            pending_meta.append((symbol.symbol_id, cache_key))
        batch_size = resolve_embed_batch_size()
        for start in range(0, len(pending_texts), batch_size):
            chunk_texts = pending_texts[start : start + batch_size]
            chunk_meta = pending_meta[start : start + batch_size]
            vectors = embed_documents(self.embedder, chunk_texts)
            for (symbol_id, cache_key), raw_vector in zip(chunk_meta, vectors, strict=False):
                vector = [float(value) for value in raw_vector]
                put_cached_embedding(
                    self.store_root, cache_key=cache_key, embedder_name=self.embedder.name, vector=vector
                )
                results[symbol_id] = vector
        return results

    def _embed_query(self, query: str) -> list[float]:
        cache_key = vector_cache_key("code-search-query", f"{self.embedder.name}:{query.strip().lower()}")
        return self._embed_text(query, cache_key=cache_key, embed_many=embed_queries)

    def _embed_symbol(self, symbol: SymbolRecord, embedding_text: str) -> list[float]:
        cache_key = vector_cache_key(symbol.symbol_id, f"{self.embedder.name}:{symbol.content_hash}:{embedding_text}")
        return self._embed_text(embedding_text, cache_key=cache_key, embed_many=embed_documents)

    def _embed_text(
        self,
        text: str,
        *,
        cache_key: str,
        embed_many: Callable[[Embedder, list[str]], list[list[float]]],
    ) -> list[float]:
        if self.embedder.dim <= 0:
            return []
        cached = get_cached_embedding(self.store_root, cache_key=cache_key, embedder_name=self.embedder.name)
        if cached is not None:
            return cached
        vectors = embed_many(self.embedder, [text])
        if not vectors:
            return []
        vector = [float(value) for value in vectors[0]]
        put_cached_embedding(self.store_root, cache_key=cache_key, embedder_name=self.embedder.name, vector=vector)
        return vector


__all__ = [
    "FusionWeights",
    "SearchMode",
    "SemanticSearchRanker",
    "is_identifier_query",
    "looks_natural_language_query",
    "render_embedding_text",
    "resolve_embed_batch_size",
    "resolve_search_mode",
    "semantic_candidate_limit",
]
