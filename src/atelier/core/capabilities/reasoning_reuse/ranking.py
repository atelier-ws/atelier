"""Hybrid ranking engine: BM25 + recency + success-rate + dead-end avoidance."""

from __future__ import annotations

import math
from typing import Any

from .bm25 import bm25_score, build_idf, tokenise
from .dead_ends import DeadEndTracker
from .models import RankedProcedure

# Ranking weights (sum should be ~1.0 for interpretability)
_W_BM25 = 0.45
_W_RECENCY = 0.25
_W_SUCCESS = 0.20
_W_BASE = 0.10


def _recency_score(last_used_ts: float, now_ts: float, *, half_life_days: float = 7.0) -> float:
    """Exponential decay: score=1.0 if used now, decays to ~0.5 after half_life_days."""
    if last_used_ts <= 0:
        return 0.1
    elapsed_days = (now_ts - last_used_ts) / 86_400
    return math.exp(-elapsed_days * math.log(2) / half_life_days)


def _success_score(success_rate: float, reuse_count: int) -> float:
    """Bayesian smoothed success rate (adds prior of 0.5 with weight 2)."""
    numerator = success_rate * reuse_count + 0.5 * 2
    denominator = reuse_count + 2
    return numerator / denominator


def rank_blocks(
    query: str,
    blocks: list[dict[str, Any]],
    *,
    dead_end_tracker: DeadEndTracker | None = None,
    now_ts: float = 0.0,
    domain_filter: str = "",
    limit: int = 5,
) -> list[RankedProcedure]:
    """
    Rank procedure blocks against a query using a hybrid scoring model.

    Args:
        query:            The current task description or goal.
        blocks:           List of block dicts from the reasoning store.
        dead_end_tracker: Optional tracker for penalising dead-end approaches.
        now_ts:           Current Unix timestamp (0 = disabled recency scoring).
        domain_filter:    If set, prefer blocks from this domain.
        limit:            Maximum results to return.

    Returns:
        List of :class:`RankedProcedure` sorted by score descending.
    """
    if not blocks:
        return []

    import time as _time

    if now_ts <= 0:
        now_ts = _time.time()

    # Build BM25 corpus
    query_tokens = tokenise(query)
    doc_texts: list[str] = []
    for block in blocks:
        parts = [
            str(block.get("title", "")),
            str(block.get("description", "")),
            str(block.get("tags", "")),
            str(block.get("domain", "")),
        ]
        doc_texts.append(" ".join(parts))

    corpus = [tokenise(t) for t in doc_texts]
    idf = build_idf(corpus)
    avg_dl = sum(len(d) for d in corpus) / max(len(corpus), 1)

    ranked: list[RankedProcedure] = []
    for block, doc_tokens in zip(blocks, corpus, strict=False):
        # BM25 score (normalised to [0, 1] via sigmoid)
        raw_bm25 = bm25_score(query_tokens, doc_tokens, idf, avg_dl)
        bm25_norm = raw_bm25 / (raw_bm25 + 3.0)  # soft normalisation

        # Recency score
        last_used = float(block.get("last_used_ts", 0) or block.get("last_used", 0) or 0)
        recency = _recency_score(last_used, now_ts) if last_used > 0 else 0.1

        # Success rate
        success_rate = float(block.get("success_rate", 0.5))
        reuse_count = int(block.get("reuse_count", 0))
        success = _success_score(success_rate, reuse_count)

        # Base score (normalised)
        base = float(block.get("base_score", 0.5))

        composite = (
            _W_BM25 * bm25_norm + _W_RECENCY * recency + _W_SUCCESS * success + _W_BASE * base
        )

        # Domain alignment bonus
        if domain_filter and str(block.get("domain", "")) == domain_filter:
            composite *= 1.15

        # Dead-end penalty
        is_dead_end = False
        if dead_end_tracker:
            title = str(block.get("title", ""))
            desc = str(block.get("description", ""))
            is_dead_end = dead_end_tracker.is_dead_end(title) or dead_end_tracker.is_dead_end(desc)
            if is_dead_end:
                composite *= 0.2

        snippet_text = str(block.get("description", ""))[:300]

        ranked.append(
            RankedProcedure(
                block_id=str(block.get("id", block.get("block_id", ""))),
                title=str(block.get("title", "")),
                domain=str(block.get("domain", "")),
                score=composite,
                base_score=base,
                recency_score=recency,
                success_rate=success_rate,
                reuse_count=reuse_count,
                snippet=snippet_text,
                is_dead_end=is_dead_end,
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:limit]
