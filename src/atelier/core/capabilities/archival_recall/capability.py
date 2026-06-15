"""Archival memory archive and recall capability."""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Callable
from datetime import datetime

import tiktoken
from blake3 import blake3

from atelier.core.capabilities.archival_recall.ranking import rank_archival_passages
from atelier.core.foundation.memory_models import ArchivalPassage, ArchivalSource, MemoryRecall
from atelier.infra.embeddings.base import Embedder
from atelier.infra.storage.memory_store import MemoryStore

_log = logging.getLogger(__name__)

# Candidate window pulled from the store before in-Python ranking. Session-recall
# can write thousands of passages per run, so a small window silently excludes
# strong older matches; raise via env for very large stores.
_RECALL_CANDIDATE_LIMIT = int(os.environ.get("ATELIER_RECALL_CANDIDATE_LIMIT", "2000"))
_window_saturation_warned = False

# Embedding is a blocking network round-trip for remote backends (openai/ollama/
# letta) with no provider-side timeout, so an unreachable provider would otherwise
# stall every memory(op=recall|store_fact|archive) call. Bound it. The default
# LocalEmbedder returns in-process and well under this ceiling, so the guard is a
# no-op for it beyond the timeout itself.
_EMBED_TIMEOUT_S = float(os.environ.get("ATELIER_EMBED_TIMEOUT_S", "10"))


def _embed_with_timeout(embedder: Embedder, texts: list[str]) -> list[list[float]]:
    """Embed under a hard timeout; return [] on timeout/error.

    Used by the recall path, which needs the vector synchronously to rank. On
    failure the caller falls back to lexical/recency ranking rather than blocking
    on a slow or unreachable provider. The embed runs on a daemon thread joined
    with a timeout: a hung provider call is abandoned (the daemon thread dies
    with the process) instead of stalling recall, since a pooled worker would
    otherwise block shutdown until the slow call returned."""
    result: list[list[float]] = []
    error: list[BaseException] = []

    def _run() -> None:
        try:
            result.extend(embedder.embed(texts))
        except BaseException as exc:  # noqa: BLE001 - surfaced via `error`, never raised here
            error.append(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=_EMBED_TIMEOUT_S)
    if worker.is_alive():
        _log.warning("embedder %s timed out after %.1fs; falling back to lexical ranking", embedder.name, _EMBED_TIMEOUT_S)
        return []
    if error:
        _log.warning("embedder %s failed; falling back to lexical ranking", embedder.name, exc_info=error[0])
        return []
    return result


def _warn_window_saturated() -> None:
    """Warn at most once per process that the recall candidate window saturated.
    recall() is the shared path for memory.db, recall.db and get_context, so an
    unthrottled warning would repeat on every call against a saturated store."""
    global _window_saturation_warned
    if _window_saturation_warned:
        return
    _window_saturation_warned = True
    _log.warning(
        "recall candidate window saturated at %d passages; older matches are excluded from "
        "ranking (raise ATELIER_RECALL_CANDIDATE_LIMIT)",
        _RECALL_CANDIDATE_LIMIT,
    )


class ArchivalRecallCapability:
    def __init__(self, store: MemoryStore, embedder: Embedder, *, redactor: Callable[[str], str]):
        self._store = store
        self._embedder = embedder
        self._redactor = redactor

    def archive(
        self,
        *,
        text: str,
        source: ArchivalSource,
        agent_id: str | None = None,
        source_ref: str = "",
        tags: list[str] | None = None,
    ) -> ArchivalPassage:
        clean = self._redactor(text)
        chunks = _chunk_text(clean)
        passages = [
            ArchivalPassage(
                agent_id=agent_id or "shared",
                text=chunk,
                tags=tags or [],
                source=source,
                source_ref=source_ref,
                dedup_hash=blake3(chunk.encode("utf-8")).hexdigest(),
            )
            for chunk in chunks
        ]
        if not passages:  # pragma: no cover - _chunk_text always returns one item
            raise ValueError("archive text produced no passages")

        # Fire-and-forget: the embed is the only slow step (a blocking network
        # round-trip for remote backends) and its vector is needed solely to
        # persist the passage, never for this call's return value. Dispatch the
        # embed + insert on a background daemon thread so the tool returns
        # immediately; bound the work with a timeout and drop on failure.
        threading.Thread(
            target=self._embed_and_persist,
            args=(passages, chunks),
            daemon=True,
        ).start()
        return passages[0]

    def _embed_and_persist(self, passages: list[ArchivalPassage], chunks: list[str]) -> None:
        """Background worker: embed chunks then persist passages. Best-effort.

        Runs off the caller's thread. Any embed timeout/error is logged and the
        passages are still persisted without a vector so the text stays
        lexically recallable; a persist failure is logged and dropped so a
        background failure never surfaces to the original caller."""
        embeddings: list[list[float]] = []
        if self._embedder.dim > 0:
            embeddings = _embed_with_timeout(self._embedder, chunks)
        for idx, passage in enumerate(passages):
            embedding = embeddings[idx] if idx < len(embeddings) and embeddings[idx] else None
            to_store = passage.model_copy(
                update={
                    "embedding": embedding,
                    "embedding_model": self._embedder.name if embedding is not None else "",
                    "embedding_provenance": self._embedder.__class__.__name__,
                }
            )
            try:
                self._store.insert_passage(to_store)
            except Exception:  # noqa: BLE001 - best-effort background persist
                _log.warning("background archive persist failed for passage %s", passage.id, exc_info=True)

    def recall(
        self,
        *,
        agent_id: str | None,
        query: str,
        top_k: int = 5,
        tags: list[str] | None = None,
        since: datetime | None = None,
    ) -> tuple[list[ArchivalPassage], MemoryRecall]:
        clean_query = self._redactor(query)
        query_embedding: list[float] | None = None
        if self._embedder.dim > 0:
            # Timeout-guarded: recall needs the vector to rank, so it can't be
            # fire-and-forget, but a slow/unreachable provider must not stall the
            # call. On timeout/failure _embed_with_timeout returns [] and we fall
            # back to lexical/recency ranking below (query_embedding stays None).
            vectors = _embed_with_timeout(self._embedder, [clean_query])
            if vectors and vectors[0]:
                query_embedding = vectors[0]

        # G5: pass the live embedder model-id so the opt-in ANN can N5-gate
        # passages to the current vector space (no-op when the flag is off).
        embedding_model = self._embedder.name if query_embedding else None
        passages = self._store.list_passages(agent_id, tags=tags, since=since, limit=_RECALL_CANDIDATE_LIMIT)
        if len(passages) >= _RECALL_CANDIDATE_LIMIT:
            _warn_window_saturated()
        ranked = rank_archival_passages(
            query=clean_query,
            passages=passages,
            query_embedding=query_embedding,
            tags=tags,
            since=since,
            top_k=top_k,
            embedding_model=embedding_model,
        )
        recall_query = clean_query
        if not ranked:
            widened_query = _widen_query(clean_query)
            if widened_query and widened_query != clean_query:
                ranked = rank_archival_passages(
                    query=widened_query,
                    passages=passages,
                    query_embedding=query_embedding,
                    tags=tags,
                    since=since,
                    top_k=top_k,
                    embedding_model=embedding_model,
                )
                recall_query = widened_query
        selected = [item.passage for item in ranked]
        recall = MemoryRecall(
            agent_id=agent_id or "shared",
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
