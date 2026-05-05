"""Hybrid ranking for archival memory recall."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from atelier.core.foundation.memory_models import ArchivalPassage
from atelier.infra.storage.vector import cosine_similarity


@dataclass(frozen=True)
class RankedPassage:
    passage: ArchivalPassage
    score: float
    bm25_norm: float
    cosine: float


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _bm25_scores(query: str, passages: list[ArchivalPassage]) -> dict[str, float]:
    query_tokens = _tokens(query)
    if not query_tokens or not passages:
        return {p.id: 0.0 for p in passages}

    docs = [_tokens(p.text + " " + " ".join(p.tags)) for p in passages]
    avg_len = sum(len(doc) for doc in docs) / max(len(docs), 1)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))

    scores: dict[str, float] = {}
    total_docs = len(docs)
    for passage, doc in zip(passages, docs, strict=True):
        tf = Counter(doc)
        doc_len = len(doc) or 1
        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            idf = math.log((total_docs - df[term] + 0.5) / (df[term] + 0.5) + 1.0)
            denom = tf[term] + 1.5 * (1 - 0.75 + 0.75 * doc_len / max(avg_len, 1.0))
            score += idf * ((tf[term] * 2.5) / denom)
        scores[passage.id] = score
    return scores


def rank_archival_passages(
    *,
    query: str,
    passages: list[ArchivalPassage],
    query_embedding: list[float] | None = None,
    tags: list[str] | None = None,
    since: datetime | None = None,
    top_k: int = 5,
) -> list[RankedPassage]:
    """Rank archival passages with hybrid BM25 and cosine scoring."""
    filtered = passages
    if tags:
        required = set(tags)
        filtered = [p for p in filtered if required.issubset(set(p.tags))]
    if since is not None:
        filtered = [p for p in filtered if p.created_at >= since]
    if not filtered:
        return []

    bm25 = _bm25_scores(query, filtered)
    max_bm25 = max(bm25.values(), default=0.0)
    bm25_norm = {pid: (score / max_bm25 if max_bm25 > 0 else 0.0) for pid, score in bm25.items()}

    vector_enabled = bool(query_embedding)
    ranked: list[RankedPassage] = []
    for passage in filtered:
        cosine = 0.0
        if vector_enabled and passage.embedding and passage.embedding_provenance != "legacy_stub":
            try:
                cosine = max(0.0, min(1.0, cosine_similarity(query_embedding or [], passage.embedding)))
            except ValueError:
                cosine = 0.0
        score = (0.6 * cosine) + (0.4 * bm25_norm.get(passage.id, 0.0))
        ranked.append(
            RankedPassage(
                passage=passage,
                score=score,
                bm25_norm=bm25_norm.get(passage.id, 0.0),
                cosine=cosine,
            )
        )

    ranked.sort(key=lambda item: (item.score, item.bm25_norm, item.passage.created_at), reverse=True)
    return ranked[:top_k]


__all__ = ["RankedPassage", "rank_archival_passages"]
