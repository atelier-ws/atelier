"""Retriever — score and rank ReasonBlocks against a task context.

Scoring (deterministic, no LLM):

    Without vector search (default):
        0.30 domain / task_type match
        0.25 file / tool / module overlap
        0.20 trigger phrase match
        0.15 failure / error signal match
        0.10 success history (capped)

    With vector search (ATELIER_VECTOR_SEARCH_ENABLED=true):
        0.30 domain / task_type match
        0.25 file / tool / module overlap
        0.20 trigger phrase match
        0.15 failure / error signal match
        0.05 success history (capped)
        0.05 vector cosine similarity

Quarantined blocks are excluded. Deprecated blocks are excluded by default.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from atelier.core.foundation.models import ReasonBlock
from atelier.core.foundation.store import ReasoningStore


@dataclass
class TaskContext:
    """Inputs used to score reasoning relevance for a single agent task."""

    task: str
    domain: str | None = None
    task_type: str | None = None
    files: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def text_blob(self) -> str:
        parts = [self.task]
        if self.task_type:
            parts.append(self.task_type)
        parts.extend(self.errors)
        parts.extend(self.tools)
        return " ".join(parts).lower()


@dataclass
class ScoredBlock:
    block: ReasonBlock
    score: float
    breakdown: dict[str, float]


# --------------------------------------------------------------------------- #
# Scoring helpers                                                             #
# --------------------------------------------------------------------------- #


def _domain_score(block: ReasonBlock, ctx: TaskContext) -> float:
    if ctx.domain and block.domain == ctx.domain:
        return 1.0
    if ctx.domain and block.domain.startswith(ctx.domain.split(".")[0]):
        return 0.5
    if ctx.task_type and ctx.task_type in block.task_types:
        return 0.7
    return 0.0


def _pattern_overlap(patterns: list[str], items: list[str]) -> float:
    if not patterns or not items:
        return 0.0
    matched = 0
    for it in items:
        for pat in patterns:
            if fnmatch.fnmatch(it, pat):
                matched += 1
                break
    return matched / len(items)


def _scope_score(block: ReasonBlock, ctx: TaskContext) -> float:
    f = _pattern_overlap(block.file_patterns, ctx.files)
    t = _pattern_overlap(block.tool_patterns, ctx.tools)
    if not block.file_patterns and not block.tool_patterns:
        return 0.0
    n = (1 if block.file_patterns else 0) + (1 if block.tool_patterns else 0)
    return (f + t) / n


def _trigger_score(block: ReasonBlock, ctx: TaskContext) -> float:
    if not block.triggers:
        return 0.0
    blob = ctx.text_blob()
    matched = sum(1 for t in block.triggers if t.lower() in blob)
    return min(1.0, matched / max(1, len(block.triggers)))


def _failure_signal_score(block: ReasonBlock, ctx: TaskContext) -> float:
    if not block.failure_signals or not ctx.errors:
        return 0.0
    err_blob = " ".join(ctx.errors).lower()
    matched = sum(1 for f in block.failure_signals if f.lower() in err_blob)
    return min(1.0, matched / max(1, len(block.failure_signals)))


def _success_history_score(block: ReasonBlock) -> float:
    total = block.success_count + block.failure_count
    if total == 0:
        return 0.5  # neutral prior
    return block.success_count / total


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

# Weights when vector search is disabled (default)
WEIGHTS: dict[str, float] = {
    "domain": 0.30,
    "scope": 0.25,
    "triggers": 0.20,
    "failures": 0.15,
    "history": 0.10,
}

# Weights when vector search is enabled (history redistributed to vector)
WEIGHTS_WITH_VECTOR: dict[str, float] = {
    "domain": 0.30,
    "scope": 0.25,
    "triggers": 0.20,
    "failures": 0.15,
    "history": 0.05,
    "vector": 0.05,
}


def score_block(
    block: ReasonBlock,
    ctx: TaskContext,
    *,
    vector_score: float | None = None,
    use_vector_weights: bool | None = None,
) -> ScoredBlock:
    """Score a ReasonBlock against a task context.

    Args:
        block: The candidate ReasonBlock.
        ctx: The current task context.
        vector_score: Pre-computed cosine similarity in [0, 1].  When
            provided and ``use_vector_weights`` is True (or auto-detected
            via ``ATELIER_VECTOR_SEARCH_ENABLED``), the vector component
            is included in the score.
        use_vector_weights: Override the env-var check.  Pass True/False
            explicitly or leave as None to auto-detect from env.
    """
    from atelier.infra.storage.vector import is_vector_enabled

    _use_vec = is_vector_enabled() if use_vector_weights is None else use_vector_weights
    w = WEIGHTS_WITH_VECTOR if _use_vec else WEIGHTS

    breakdown: dict[str, float] = {
        "domain": _domain_score(block, ctx) * w["domain"],
        "scope": _scope_score(block, ctx) * w["scope"],
        "triggers": _trigger_score(block, ctx) * w["triggers"],
        "failures": _failure_signal_score(block, ctx) * w["failures"],
        "history": _success_history_score(block) * w["history"],
    }
    if _use_vec:
        raw_vs = vector_score if vector_score is not None else 0.0
        breakdown["vector"] = max(0.0, min(1.0, raw_vs)) * w["vector"]

    return ScoredBlock(block=block, score=sum(breakdown.values()), breakdown=breakdown)


def retrieve(
    store: ReasoningStore,
    ctx: TaskContext,
    *,
    limit: int = 5,
    min_score: float = 0.15,
    include_deprecated: bool = False,
    vector_scores: dict[str, float] | None = None,
    use_vector_weights: bool | None = None,
) -> list[ScoredBlock]:
    """Return top-N relevant ReasonBlocks for a task context.

    Args:
        store: The backing store.
        ctx: The current task context.
        limit: Maximum number of results.
        min_score: Minimum score to include a block.
        include_deprecated: Include deprecated blocks.
        vector_scores: Mapping of block_id -> cosine similarity score.
            Pass pre-computed scores from a vector search; they will be
            incorporated when vector scoring is enabled.
        use_vector_weights: Override the env-var check for weight selection.
    """
    candidates: list[ReasonBlock] = []

    # 1. FTS5 keyword pre-filter using the task + errors as the query.
    query = " ".join([ctx.task, *ctx.errors]).strip()
    if query:
        candidates.extend(store.search_blocks(query, limit=50))

    # 2. Always include all active blocks for the domain so triggers/scope
    #    can match even if FTS misses them.
    if ctx.domain:
        candidates.extend(store.list_blocks(domain=ctx.domain))

    # Deduplicate by id while preserving order.
    seen: set[str] = set()
    unique: list[ReasonBlock] = []
    for b in candidates:
        if b.id in seen:
            continue
        if b.status == "quarantined":
            continue
        if b.status == "deprecated" and not include_deprecated:
            continue
        seen.add(b.id)
        unique.append(b)

    scored = [
        score_block(
            b,
            ctx,
            vector_score=(vector_scores or {}).get(b.id),
            use_vector_weights=use_vector_weights,
        )
        for b in unique
    ]
    scored = [s for s in scored if s.score >= min_score]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit]
