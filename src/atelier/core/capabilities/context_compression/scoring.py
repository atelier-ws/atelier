"""TF-IDF and recency-weighted event importance scoring."""

from __future__ import annotations

import math
import re
from typing import Any

from .models import EventScore

# Per-kind base importance weights
_KIND_WEIGHTS: dict[str, float] = {
    "error": 3.0,
    "exception": 3.0,
    "test_fail": 2.5,
    "validation_fail": 2.5,
    "file_edit": 2.0,
    "file_write": 2.0,
    "patch": 2.0,
    "tool_call": 1.0,
    "search": 0.8,
    "read_file": 0.7,
    "smart_read": 0.7,
    "observation": 1.2,
}

# Per-kind recency half-life (in event-count units).
# Errors/edits decay slowly — they remain relevant longer.
# Reads/searches decay quickly — they are cheap to redo.
_KIND_HALF_LIFE: dict[str, float] = {
    "error": 50.0,
    "exception": 50.0,
    "test_fail": 40.0,
    "validation_fail": 40.0,
    "file_edit": 30.0,
    "file_write": 30.0,
    "patch": 30.0,
    "tool_call": 10.0,
    "search": 5.0,
    "read_file": 5.0,
    "smart_read": 5.0,
    "observation": 15.0,
}

_DEFAULT_HALF_LIFE = 10.0

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "in",
        "it",
        "to",
        "of",
        "and",
        "or",
        "at",
        "by",
        "for",
        "on",
        "with",
        "from",
        "that",
        "this",
    }
)

# Penalty factor for repeated events of the same kind with similar summaries
_REPEAT_PENALTY = 0.5


def _tokenise(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9_]*", text.lower()) if t not in _STOPWORDS and len(t) >= 3]


def _build_idf(corpus: list[list[str]]) -> dict[str, float]:
    N = len(corpus)
    if N == 0:
        return {}
    df: dict[str, int] = {}
    for doc in corpus:
        for term in set(doc):
            df[term] = df.get(term, 0) + 1
    return {term: math.log((N - freq + 0.5) / (freq + 0.5) + 1.0) for term, freq in df.items()}


def score_events(
    events: list[dict[str, Any]],
) -> list[EventScore]:
    """
    Assign an importance score to each event.

    Score components:
    1. Kind weight (errors/edits > searches/reads)
    2. TF-IDF rarity of event summary tokens across the whole event log
    3. Recency: kind-specific exponential decay (errors decay slowly, reads fast)
    4. Error-chain boost: events immediately preceding an error get +50% weight
    5. Repeat penalty: second occurrence of same-kind with similar summary gets 0.5x
    """
    if not events:
        return []

    summaries = [str(ev.get("summary", "")) for ev in events]
    corpus = [_tokenise(s) for s in summaries]
    idf = _build_idf(corpus)
    N = len(events)

    # Identify error-preceding indices for chain boosting
    error_precede: set[int] = set()
    for i, ev in enumerate(events):
        kind = str(ev.get("kind", "")).lower()
        if any(kind.startswith(k) for k in ("error", "exception", "test_fail", "validation_fail")) and i > 0:
            error_precede.add(i - 1)

    # Track seen (kind, summary_prefix) pairs to apply repeat penalties
    seen_kinds: dict[str, int] = {}  # key → first-seen index

    scored: list[EventScore] = []
    for idx, (ev, tokens) in enumerate(zip(events, corpus, strict=False)):
        kind = str(ev.get("kind", "")).lower()

        # Kind weight
        kind_w = 1.0
        matched_kind = ""
        for prefix, weight in _KIND_WEIGHTS.items():
            if kind.startswith(prefix):
                kind_w = weight
                matched_kind = prefix
                break

        # Kind-specific recency half-life
        half_life = _KIND_HALF_LIFE.get(matched_kind, _DEFAULT_HALF_LIFE)
        recency = math.exp(-(N - 1 - idx) / half_life)

        # TF-IDF rarity score
        tfidf = sum(idf.get(t, 0.0) for t in tokens)

        # Error-chain boost
        chain_boost = 1.5 if idx in error_precede else 1.0

        # Repeat penalty: same kind + same first 80 chars of summary → penalise repeat
        dedup_key = f"{kind}:{str(ev.get('summary', ''))[:80]}"
        repeat_factor = 1.0
        if dedup_key in seen_kinds:
            repeat_factor = _REPEAT_PENALTY
        else:
            seen_kinds[dedup_key] = idx

        score = kind_w * chain_boost * repeat_factor * (1.0 + tfidf) * (0.5 + 0.5 * recency)
        reason = (
            f"kind_w={kind_w:.1f} recency={recency:.2f} tfidf={tfidf:.2f} "
            f"chain={chain_boost:.1f} repeat={repeat_factor:.1f}"
        )
        scored.append(EventScore(event=ev, score=score, reason=reason))

    return scored
