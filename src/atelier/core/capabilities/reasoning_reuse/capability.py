"""ReasoningReuseCapability — RRF + MMR + Bayesian scoring retrieval engine."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atelier.core.foundation.models import ReasonBlock
from atelier.core.foundation.retriever import ScoredBlock, TaskContext, retrieve
from atelier.core.foundation.store import ReasoningStore

from .dead_ends import DeadEndTracker

try:
    import networkx as nx
except Exception:  # pragma: no cover - optional dependency fallback
    nx: Any = None  # type: ignore[no-redef]

try:
    from river import stats
except Exception:  # pragma: no cover - optional dependency fallback
    stats: Any = None  # type: ignore[no-redef]

try:
    from datasketch import HNSW
except Exception:  # pragma: no cover - optional dependency fallback
    HNSW: Any = None  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Token budget: estimated chars per token (GPT-4 ~3.7 chars/token)
# We budget per procedure block to avoid context-window blowout
# ---------------------------------------------------------------------------
_CHARS_PER_TOKEN = 4
_DEFAULT_TOKEN_BUDGET = 2000  # max tokens of injected procedures

# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion constant (k=60 per Cormack et al.)
# RRF is scale-invariant — no manual weight tuning required
# ---------------------------------------------------------------------------
_RRF_K = 60

# ---------------------------------------------------------------------------
# Maximal Marginal Relevance diversity weight
# λ=0.7 → 70% relevance, 30% novelty
# ---------------------------------------------------------------------------
_MMR_LAMBDA = 0.7

# ---------------------------------------------------------------------------
# Bayesian prior for success rate (Beta(a, b) with a=b=1 = uniform prior)
# Smoothed rate = (successes + a) / (total + a + b)
# ---------------------------------------------------------------------------
_BAYES_ALPHA = 1.0
_BAYES_BETA = 1.0

# ---------------------------------------------------------------------------
# Rescue boost: blocks matching error signals get a relevance bonus
# ---------------------------------------------------------------------------
_RESCUE_BOOST = 0.25
_GRAPH_BOOST = 0.10
_ANN_BOOST = 0.15
_ADAPTIVE_MIN_MULTIPLIER = 0.90
_ADAPTIVE_MAX_MULTIPLIER = 1.10
_VECTOR_DIM = 128


def _tokenise(text: str) -> list[str]:
    """Tokenise with camelCase splitting for higher recall."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z0-9]+", text.lower())


def _build_idf(docs: list[list[str]]) -> dict[str, float]:
    N = len(docs)
    if N == 0:
        return {}
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    return {term: math.log((N - freq + 0.5) / (freq + 0.5) + 1.0) for term, freq in df.items()}


def _bm25(
    query_tokens: list[str],
    doc_tokens: list[str],
    idf: dict[str, float],
    *,
    k1: float = 1.5,
    b: float = 0.75,
    avg_len: float = 50.0,
) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    tf = Counter(doc_tokens)
    dl = len(doc_tokens)
    score = 0.0
    for qt in query_tokens:
        if qt not in tf:
            continue
        idf_val = idf.get(qt, math.log(2.0))
        tf_norm = (tf[qt] * (k1 + 1)) / (tf[qt] + k1 * (1 - b + b * dl / avg_len))
        score += idf_val * tf_norm
    return score


def _recency_score(block: ReasonBlock) -> float:
    try:
        updated = block.updated_at
        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        age_days = (datetime.now(UTC) - updated).days
    except (AttributeError, ValueError, TypeError):
        return 0.5
    return max(0.1, math.exp(-age_days / 86.6))


def _bayesian_success(block: ReasonBlock) -> float:
    """Laplace-smoothed success rate: (S + alpha) / (S + F + alpha + beta).

    Avoids 0.0 extremes for untested blocks and 1.0 for single-success blocks.
    """
    return (block.success_count + _BAYES_ALPHA) / (
        block.success_count + block.failure_count + _BAYES_ALPHA + _BAYES_BETA
    )


def _jaccard(a: list[str], b: list[str]) -> float:
    """Token-set Jaccard similarity — O(n) with sets, good enough for MMR."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _estimate_tokens(block: ReasonBlock) -> int:
    """Rough token count for a procedure block."""
    text = " ".join(
        filter(
            None,
            [
                block.title,
                block.situation,
                " ".join(block.procedure),
                " ".join(block.triggers),
            ],
        )
    )
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _hash_vector(tokens: list[str], *, dim: int = _VECTOR_DIM) -> list[float]:
    vec = [0.0] * dim
    for tok in tokens:
        bucket = hash(tok) % dim
        vec[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    return max(0.0, 1.0 - dot)


class _AdaptivePriorTracker:
    """Online prior tracker using river when available, with a pure-Python fallback."""

    def __init__(self) -> None:
        self._by_domain: dict[str, Any] = {}
        self._fallback_sum: dict[str, float] = {}
        self._fallback_count: dict[str, int] = {}

    def observe(self, domain: str, reward: float) -> None:
        domain_key = domain or "unknown"
        clamped = min(1.0, max(0.0, reward))
        if stats is not None:
            metric = self._by_domain.get(domain_key)
            if metric is None:
                metric = stats.EWMean(fading_factor=0.2)  # type: ignore[no-untyped-call]
                self._by_domain[domain_key] = metric
            metric.update(clamped)
            return
        self._fallback_sum[domain_key] = self._fallback_sum.get(domain_key, 0.0) + clamped
        self._fallback_count[domain_key] = self._fallback_count.get(domain_key, 0) + 1

    def prior(self, domain: str) -> float:
        domain_key = domain or "unknown"
        if stats is not None:
            metric = self._by_domain.get(domain_key)
            if metric is None:
                return 0.5
            val = getattr(metric, "get", lambda: 0.5)()
            return float(val if val is not None else 0.5)
        count = self._fallback_count.get(domain_key, 0)
        if count == 0:
            return 0.5
        return self._fallback_sum.get(domain_key, 0.0) / count


class ReasoningReuseCapability:
    """
    Retrieves and ranks relevant past reasoning blocks for injection into
    the current agent context.

    Ranking pipeline:
    1. BM25 rank  +  FTS rank  +  base-retriever rank  → fused via RRF
    2. Rescue boost for blocks whose failure_signals match current errors
    3. Bayesian-smoothed success rate (Beta prior avoids 0/1 extremes)
    4. Recency decay (half-life ~87 days)
    5. MMR diversity filter so injected blocks cover different strategies
    6. Token-budget gate so total injection stays under _DEFAULT_TOKEN_BUDGET

    Signature: __init__(store, root) — matches engine.py constructor call.
    """

    def __init__(self, store: ReasoningStore, root: Path) -> None:
        self._store = store
        self._root = Path(root)
        self._dead_ends = DeadEndTracker()
        self._adaptive_priors = _AdaptivePriorTracker()
        # Savings tracker for finalize() reporting
        self._avoided_failures = 0
        self._avoided_tool_calls = 0
        self._rescue_procedures = 0

    # ------------------------------------------------------------------
    # Internal block collection
    # ------------------------------------------------------------------

    def _domain_blocks(self) -> list[ReasonBlock]:
        from atelier.core.domains import DomainManager

        manager = DomainManager(self._root)
        blocks: list[ReasonBlock] = []
        seen: set[str] = set()
        for block in manager.all_reasonblocks():
            if block.status in ("quarantined", "deprecated"):
                continue
            if block.id in seen:
                continue
            seen.add(block.id)
            blocks.append(block)
        return blocks

    def _all_active_blocks(self) -> list[ReasonBlock]:
        learned = self._store.list_blocks()
        active = [b for b in learned if b.status not in ("quarantined", "deprecated")]
        domain_seen = {b.id for b in active}
        for b in self._domain_blocks():
            if b.id not in domain_seen:
                active.append(b)
                domain_seen.add(b.id)
        return active

    # ------------------------------------------------------------------
    # Primary ranking: Reciprocal Rank Fusion + rescue boost + Bayesian score
    # ------------------------------------------------------------------

    def rank_reusable_procedures(
        self,
        *,
        task: str,
        domain: str | None = None,
        files: list[str] | None = None,
        tools: list[str] | None = None,
        errors: list[str] | None = None,
        limit: int = 5,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
    ) -> list[Any]:
        """
        Rank blocks using Reciprocal Rank Fusion of BM25 + FTS + base retriever.

        Steps:
        1. Score each block with BM25, FTS, and base retriever independently
        2. Fuse ranks via RRF (scale-invariant, no manual weight tuning)
        3. Apply rescue boost for blocks matching current errors
        4. Multiply by Bayesian-smoothed success x recency
        5. Apply MMR to select diverse top-k (avoids injecting redundant blocks)
        6. Enforce token budget gate
        """
        ctx = TaskContext(
            task=task,
            domain=domain,
            files=files or [],
            tools=tools or [],
            errors=errors or [],
        )

        all_blocks = self._all_active_blocks()
        if not all_blocks:
            return []

        # Expand query: task text + error phrases (first 200 chars each)
        error_text = " ".join(e[:200] for e in (errors or []))
        query_tokens = _tokenise(task + " " + error_text)

        # BM25 scoring
        doc_tokens_map = {
            b.id: _tokenise(
                f"{b.title} {b.title} {b.domain} {' '.join(b.triggers)} "
                f"{b.situation} {' '.join(b.failure_signals)}"
            )
            for b in all_blocks
        }
        avg_len = sum(len(v) for v in doc_tokens_map.values()) / max(1, len(doc_tokens_map))
        idf = _build_idf(list(doc_tokens_map.values()))

        bm25_scored = sorted(
            [
                (b.id, _bm25(query_tokens, doc_tokens_map[b.id], idf, avg_len=avg_len))
                for b in all_blocks
            ],
            key=lambda x: x[1],
            reverse=True,
        )

        # FTS scoring (reciprocal rank from store)
        fts_blocks = self._store.search_blocks(task, limit=max(limit * 5, 30))
        fts_rank: dict[str, int] = {b.id: rank for rank, b in enumerate(fts_blocks)}

        # Base retriever scoring (domain / trigger matching)
        learned = retrieve(self._store, ctx, limit=max(limit * 3, 20))
        base_scores: dict[str, float] = {item.block.id: item.score for item in learned}
        base_ranked = sorted(base_scores.items(), key=lambda x: x[1], reverse=True)
        base_rank: dict[str, int] = {bid: rank for rank, (bid, _) in enumerate(base_ranked)}

        # RRF fusion — merge three rank lists
        block_map: dict[str, ReasonBlock] = {b.id: b for b in all_blocks}
        rrf_scores: dict[str, float] = {}
        for rank, (bid, _) in enumerate(bm25_scored):
            rrf_scores[bid] = rrf_scores.get(bid, 0.0) + 1.0 / (_RRF_K + rank)
        for bid, rank in fts_rank.items():
            if bid in block_map:
                rrf_scores[bid] = rrf_scores.get(bid, 0.0) + 1.0 / (_RRF_K + rank)
        for bid, rank in base_rank.items():
            if bid in block_map:
                rrf_scores[bid] = rrf_scores.get(bid, 0.0) + 1.0 / (_RRF_K + rank)

        error_text_lower = error_text.lower()

        results: list[_HybridResult] = []
        for bid, rrf in rrf_scores.items():
            block = block_map.get(bid)
            if block is None:
                continue

            is_rescue = bool(
                errors
                and block.failure_signals
                and any(fs.lower() in error_text_lower for fs in block.failure_signals)
            )

            # Combine: RRF (rank quality) x recency x Bayesian success
            # + rescue boost when error signals match
            quality = _bayesian_success(block) * _recency_score(block)
            final = rrf * quality
            if is_rescue:
                final = min(final + _RESCUE_BOOST, 1.0)

            results.append(
                _HybridResult(
                    block=block,
                    fts_score=1.0 / (_RRF_K + fts_rank.get(bid, len(all_blocks))),
                    bm25_score=_bm25(
                        query_tokens, doc_tokens_map.get(bid, []), idf, avg_len=avg_len
                    ),
                    recency_score=_recency_score(block),
                    success_score=_bayesian_success(block),
                    final_score=final,
                    rescue=is_rescue,
                    dead_ends=list(block.dead_ends),
                )
            )

        # Sort by final score before MMR selection
        results.sort(key=lambda r: r.final_score, reverse=True)

        self._apply_adaptive_priors(results)
        self._apply_graph_propagation(results)
        self._apply_ann_reranking(results, query_tokens=query_tokens)
        results.sort(key=lambda r: r.final_score, reverse=True)

        # MMR diversity selection — avoids injecting near-duplicate procedures
        selected: list[_HybridResult] = []
        token_used = 0
        candidates = list(results)

        while candidates and len(selected) < limit:
            if not selected:
                best = candidates.pop(0)
            else:
                # MMR score: λ * relevance - (1-λ) * max_similarity_to_selected
                selected_tokens = [doc_tokens_map.get(s.block.id, []) for s in selected]
                best_score = -1.0
                best_idx = 0
                for idx, cand in enumerate(candidates):
                    cand_tokens = doc_tokens_map.get(cand.block.id, [])
                    max_sim = max(
                        (_jaccard(cand_tokens, st) for st in selected_tokens),
                        default=0.0,
                    )
                    mmr = _MMR_LAMBDA * cand.final_score - (1.0 - _MMR_LAMBDA) * max_sim
                    if mmr > best_score:
                        best_score = mmr
                        best_idx = idx
                best = candidates.pop(best_idx)

            # Token budget gate
            block_tokens = _estimate_tokens(best.block)
            if token_used + block_tokens > token_budget and selected:
                break
            token_used += block_tokens
            selected.append(best)

        for picked in selected:
            self._adaptive_priors.observe(picked.block.domain, picked.success_score)

        return selected

    def _apply_adaptive_priors(self, results: list[Any]) -> None:
        if not results:
            return
        for item in results:
            prior = self._adaptive_priors.prior(item.block.domain)
            item.adaptive_prior = prior
            multiplier = _ADAPTIVE_MIN_MULTIPLIER + (
                (_ADAPTIVE_MAX_MULTIPLIER - _ADAPTIVE_MIN_MULTIPLIER) * prior
            )
            item.final_score *= multiplier

    def _apply_graph_propagation(self, results: list[Any]) -> None:
        if not results or nx is None:
            return
        graph = nx.Graph()
        for item in results:
            graph.add_node(item.block.id)
        for i, left in enumerate(results):
            for right in results[i + 1 :]:
                shared = len(set(left.block.triggers) & set(right.block.triggers))
                same_domain = 1 if left.block.domain == right.block.domain else 0
                shared_dead_ends = len(set(left.block.dead_ends) & set(right.block.dead_ends))
                weight = (0.2 * shared) + (0.3 * same_domain) + (0.1 * shared_dead_ends)
                if weight > 0:
                    graph.add_edge(left.block.id, right.block.id, weight=weight)

        if graph.number_of_edges() == 0:
            return

        rescue_nodes = [r.block.id for r in results if r.rescue]
        if rescue_nodes:
            base = 1.0 / len(rescue_nodes)
            personalization = {
                node: (base if node in rescue_nodes else 0.001) for node in graph.nodes
            }
        else:
            personalization = {node: 1.0 / max(graph.number_of_nodes(), 1) for node in graph.nodes}

        scores = nx.pagerank(graph, alpha=0.85, personalization=personalization, weight="weight")
        max_score = max(scores.values(), default=1.0) or 1.0
        for item in results:
            norm = scores.get(item.block.id, 0.0) / max_score
            item.graph_score = norm
            item.final_score += _GRAPH_BOOST * norm

    def _apply_ann_reranking(self, results: list[Any], *, query_tokens: list[str]) -> None:
        if not results or not query_tokens:
            return
        query_vec = _hash_vector(query_tokens)
        candidate_count = min(len(results), 80)
        candidates = results[:candidate_count]

        if HNSW is not None:
            index = HNSW(distance_func=_cosine_distance)
            vectors_by_id: dict[str, list[float]] = {}
            for item in candidates:
                tokens = _tokenise(
                    " ".join(
                        [
                            item.block.title,
                            item.block.situation,
                            " ".join(item.block.triggers),
                            " ".join(item.block.failure_signals),
                        ]
                    )
                )
                item.ann_score = 0.0
                vectors_by_id[item.block.id] = _hash_vector(tokens)
                index.insert(item.block.id, vectors_by_id[item.block.id])

            nearest = index.query(query_vec, k=min(len(candidates), 25))
            max_sim = 0.0
            sim_map: dict[str, float] = {}
            for candidate_id, dist in nearest:
                sim = max(0.0, 1.0 - float(dist))
                sim_map[str(candidate_id)] = sim
                max_sim = max(max_sim, sim)

            denom = max_sim or 1.0
            for item in candidates:
                sim = sim_map.get(item.block.id, 0.0)
                ann_norm = sim / denom
                item.ann_score = ann_norm
                item.final_score += _ANN_BOOST * ann_norm
            return

        scored: list[tuple[float, Any]] = []
        for item in candidates:
            tokens = _tokenise(
                " ".join(
                    [
                        item.block.title,
                        item.block.situation,
                        " ".join(item.block.triggers),
                        " ".join(item.block.failure_signals),
                    ]
                )
            )
            vec = _hash_vector(tokens)
            sim = max(0.0, 1.0 - _cosine_distance(query_vec, vec))
            scored.append((sim, item))
        max_sim = max((s for s, _ in scored), default=1.0) or 1.0
        for sim, item in scored:
            ann_norm = sim / max_sim
            item.ann_score = ann_norm
            item.final_score += _ANN_BOOST * ann_norm

    # ------------------------------------------------------------------
    # Engine API: retrieve → list[ScoredBlock]
    # ------------------------------------------------------------------

    def retrieve(
        self,
        *,
        task: str,
        domain: str | None = None,
        files: list[str] | None = None,
        tools: list[str] | None = None,
        errors: list[str] | None = None,
        limit: int = 5,
    ) -> list[ScoredBlock]:
        """Return ScoredBlock list for engine.get_reasoning_context."""
        ranked = self.rank_reusable_procedures(
            task=task,
            domain=domain,
            files=files,
            tools=tools,
            errors=errors,
            limit=limit,
        )
        return [
            ScoredBlock(
                block=r.block,
                score=r.final_score,
                breakdown={
                    "fts": r.fts_score,
                    "bm25": r.bm25_score,
                    "recency": r.recency_score,
                    "success": r.success_score,
                    "adaptive": r.adaptive_prior,
                    "graph": r.graph_score,
                    "ann": r.ann_score,
                },
            )
            for r in ranked
        ]

    def inject_runtime_reasoning(
        self,
        *,
        task: str,
        domain: str | None = None,
        files: list[str] | None = None,
        tools: list[str] | None = None,
        errors: list[str] | None = None,
        max_blocks: int = 5,
    ) -> dict[str, Any]:
        """Return structured injection payload for engine.inject_reasoning."""
        ranked = self.rank_reusable_procedures(
            task=task,
            domain=domain,
            files=files,
            tools=tools,
            errors=errors,
            limit=max_blocks,
        )

        procedures: list[dict[str, Any]] = []
        dead_ends: list[str] = []
        rescue_strategies: list[str] = []
        required_validations: list[str] = []

        for r in ranked:
            proc: dict[str, Any] = {
                "id": r.block.id,
                "title": r.block.title,
                "domain": r.block.domain,
                "score": round(r.final_score, 3),
                "rescue": r.rescue,
            }
            if r.block.procedure:
                proc["procedure"] = r.block.procedure
            procedures.append(proc)
            dead_ends.extend(r.dead_ends)
            if r.rescue and r.block.procedure:
                rescue_strategies.append(r.block.procedure)
            if r.block.required_rubrics:
                required_validations.extend(r.block.required_rubrics)

        # Update savings counters
        rescue_count = sum(1 for r in ranked if r.rescue)
        self._avoided_failures += rescue_count
        self._avoided_tool_calls += max(0, len(ranked) - 1)
        self._rescue_procedures += len(rescue_strategies)

        return {
            "procedures": procedures,
            "dead_ends": sorted(set(dead_ends)),
            "rescue_strategies": rescue_strategies[:3],
            "rescue_chains": self._rescue_chains(ranked),
            "required_validations": sorted(set(required_validations)),
            "savings": {
                "avoided_failures": self._avoided_failures,
                "avoided_tool_calls": self._avoided_tool_calls,
                "rescue_procedures": self._rescue_procedures,
            },
        }

    def _rescue_chains(self, ranked: list[Any]) -> list[dict[str, Any]]:
        if nx is None or not ranked:
            return []
        rescue_nodes = [r.block.id for r in ranked if r.rescue]
        if not rescue_nodes:
            return []
        graph = nx.Graph()
        id_to_title = {r.block.id: r.block.title for r in ranked}
        for r in ranked:
            graph.add_node(r.block.id)
        for i, left in enumerate(ranked):
            for right in ranked[i + 1 :]:
                shared = len(set(left.block.triggers) & set(right.block.triggers))
                if shared > 0 or left.block.domain == right.block.domain:
                    graph.add_edge(left.block.id, right.block.id)

        chains: list[dict[str, Any]] = []
        for node in rescue_nodes:
            neighbors = list(graph.neighbors(node))[:3]
            chains.append(
                {
                    "root_id": node,
                    "root_title": id_to_title.get(node, node),
                    "neighbors": [id_to_title.get(n, n) for n in neighbors],
                }
            )
        return chains

    def savings_estimate(self) -> dict[str, int]:
        return {
            "avoided_failures": self._avoided_failures,
            "avoided_tool_calls": self._avoided_tool_calls,
            "rescue_procedures": self._rescue_procedures,
        }

    # ------------------------------------------------------------------
    # Dead-end management
    # ------------------------------------------------------------------

    def mark_dead_end(self, approach: str) -> None:
        self._dead_ends.mark_dead_end(approach)

    def is_dead_end(self, approach: str) -> bool:
        return self._dead_ends.is_dead_end(approach)


# ---------------------------------------------------------------------------
# Internal result type
# ---------------------------------------------------------------------------


class _HybridResult:
    """Internal result type for rank_reusable_procedures."""

    __slots__ = (
        "adaptive_prior",
        "ann_score",
        "block",
        "bm25_score",
        "dead_ends",
        "final_score",
        "fts_score",
        "graph_score",
        "recency_score",
        "rescue",
        "success_score",
    )

    def __init__(
        self,
        *,
        block: ReasonBlock,
        fts_score: float,
        bm25_score: float,
        recency_score: float,
        success_score: float,
        final_score: float,
        rescue: bool,
        dead_ends: list[str],
    ) -> None:
        self.block = block
        self.fts_score = fts_score
        self.bm25_score = bm25_score
        self.recency_score = recency_score
        self.success_score = success_score
        self.final_score = final_score
        self.rescue = rescue
        self.dead_ends = dead_ends
        self.adaptive_prior = 0.5
        self.graph_score = 0.0
        self.ann_score = 0.0
