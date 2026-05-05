"""Archival memory archive and recall capability."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

import tiktoken
from blake3 import blake3

from atelier.core.capabilities.archival_recall.ranking import rank_archival_passages
from atelier.core.foundation.memory_models import ArchivalPassage, ArchivalSource, MemoryRecall
from atelier.infra.embeddings.base import Embedder
from atelier.infra.storage.memory_store import MemoryStore


class ArchivalRecallCapability:
    def __init__(self, store: MemoryStore, embedder: Embedder, *, redactor: Callable[[str], str]):
        self._store = store
        self._embedder = embedder
        self._redactor = redactor

    def archive(
        self,
        *,
        agent_id: str,
        text: str,
        source: ArchivalSource,
        source_ref: str = "",
        tags: list[str] | None = None,
    ) -> ArchivalPassage:
        clean = self._redactor(text)
        chunks = _chunk_text(clean)
        embeddings: list[list[float]] = []
        if self._embedder.dim > 0:
            embeddings = self._embedder.embed(chunks)

        first: ArchivalPassage | None = None
        for idx, chunk in enumerate(chunks):
            embedding = embeddings[idx] if idx < len(embeddings) and embeddings[idx] else None
            passage = ArchivalPassage(
                agent_id=agent_id,
                text=chunk,
                embedding=embedding,
                embedding_model=self._embedder.name if embedding is not None else "",
                embedding_provenance=self._embedder.__class__.__name__,
                tags=tags or [],
                source=source,
                source_ref=source_ref,
                dedup_hash=blake3(chunk.encode("utf-8")).hexdigest(),
            )
            stored = self._store.insert_passage(passage)
            if first is None:
                first = stored
        if first is None:  # pragma: no cover - _chunk_text always returns one item
            raise ValueError("archive text produced no passages")
        return first

    def recall(
        self,
        *,
        agent_id: str,
        query: str,
        top_k: int = 5,
        tags: list[str] | None = None,
        since: datetime | None = None,
    ) -> tuple[list[ArchivalPassage], MemoryRecall]:
        clean_query = self._redactor(query)
        query_embedding: list[float] | None = None
        if self._embedder.dim > 0:
            vectors = self._embedder.embed([clean_query])
            if vectors and vectors[0]:
                query_embedding = vectors[0]

        passages = self._store.list_passages(agent_id, tags=tags, since=since, limit=500)
        ranked = rank_archival_passages(
            query=clean_query,
            passages=passages,
            query_embedding=query_embedding,
            tags=tags,
            since=since,
            top_k=top_k,
        )
        recall_query = clean_query
        if not ranked:
            widened_query = _widen_query(clean_query)
            if widened_query and widened_query != clean_query:
                passages = self._store.list_passages(agent_id, tags=tags, since=since, limit=500)
                ranked = rank_archival_passages(
                    query=widened_query,
                    passages=passages,
                    query_embedding=query_embedding,
                    tags=tags,
                    since=since,
                    top_k=top_k,
                )
                recall_query = widened_query
        selected = [item.passage for item in ranked]
        recall = MemoryRecall(
            agent_id=agent_id,
            query=recall_query,
            top_passages=[passage.id for passage in selected],
            selected_passage_id=selected[0].id if selected else None,
        )
        self._store.record_recall(recall)
        return selected, recall


def _chunk_text(text: str, *, max_tokens: int = 800, window_tokens: int = 400, overlap: int = 80) -> list[str]:
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    if len(tokens) <= max_tokens:
        return [text]
    chunks: list[str] = []
    step = max(1, window_tokens - overlap)
    for start in range(0, len(tokens), step):
        piece = tokens[start : start + window_tokens]
        if not piece:
            break
        chunks.append(encoding.decode(piece))
        if start + window_tokens >= len(tokens):
            break
    return chunks


def _widen_query(query: str) -> str:
    without_quotes = re.sub(r"(['\"]).*?\1", " ", query.lower())
    without_bool = re.sub(r"\bAND\b", " OR ", without_quotes, flags=re.IGNORECASE)
    terms = re.findall(r"[a-z0-9_]+", without_bool)
    stop = {"and", "or", "the", "a", "an", "to", "of", "in", "for", "with", "on"}
    useful = [term for term in terms if term not in stop]
    return " OR ".join(useful[:3])


__all__ = ["ArchivalRecallCapability"]
