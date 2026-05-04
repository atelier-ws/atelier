"""Lesson promoter capability.

Failed trace -> embedding -> nearest-neighbor cluster -> inbox candidate.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from atelier.core.capabilities.lesson_promotion.draft import draft_lesson_candidate
from atelier.core.foundation.extractor import extract_candidate
from atelier.core.foundation.lesson_models import LessonCandidate, LessonPromotion
from atelier.core.foundation.models import Rubric, Trace
from atelier.core.foundation.store import ReasoningStore
from atelier.infra.storage.vector import cosine_similarity, get_embedding_dim, stub_embedding


class LessonPromoterCapability:
    """Create and review lesson candidates from failed traces."""

    def __init__(self, store: ReasoningStore, *, now: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self._now = now or (lambda: datetime.now(UTC))
        self._embedding_dim = min(get_embedding_dim(), 128)
        self._trace_embedding_cache: dict[str, list[float]] = {}
        self._recent_failed_by_fingerprint: dict[str, list[Trace]] = {}

    def _trace_text(self, trace: Trace) -> str:
        commands: list[str] = []
        for item in trace.commands_run:
            if isinstance(item, str):
                commands.append(item)
            else:
                commands.append(str(item.command))
        errors = "\n".join(trace.errors_seen)
        return "\n".join([*commands, errors, trace.diff_summary, trace.output_summary])

    def _embed_trace(self, trace: Trace) -> list[float]:
        cached = self._trace_embedding_cache.get(trace.id)
        if cached is not None:
            return cached
        embedding = stub_embedding(self._trace_text(trace), dim=self._embedding_dim)
        self._trace_embedding_cache[trace.id] = embedding
        return embedding

    def _recent_inbox(self, domain: str, days: int = 30) -> list[LessonCandidate]:
        cutoff = self._now() - timedelta(days=days)
        out: list[LessonCandidate] = []
        for item in self.store.list_lesson_candidates(domain=domain, status="inbox", limit=500):
            if item.created_at >= cutoff:
                out.append(item)
        return out

    def _nearest_cluster(
        self,
        *,
        domain: str,
        embedding: list[float],
        cluster_fingerprint: str,
        top_k: int = 8,
    ) -> list[LessonCandidate]:
        scored: list[tuple[float, LessonCandidate]] = []
        for candidate in self._recent_inbox(domain):
            if not candidate.embedding:
                continue
            if candidate.cluster_fingerprint != cluster_fingerprint:
                continue
            sim = cosine_similarity(embedding, candidate.embedding)
            scored.append((sim, candidate))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry[1] for entry in scored[:top_k]]

    def _recent_trace_cluster(
        self,
        *,
        domain: str,
        current_trace_id: str,
        cluster_fingerprint: str,
        embedding: list[float],
        limit: int = 8,
    ) -> list[Trace]:
        scored: list[tuple[float, Trace]] = []
        for trace in self.store.list_traces(domain=domain, status="failed", limit=500):
            if trace.id == current_trace_id:
                continue
            if not trace.errors_seen:
                continue
            trace_fp = trace.errors_seen[0].strip().lower()[:160]
            if trace_fp != cluster_fingerprint:
                continue
            sim = cosine_similarity(embedding, self._embed_trace(trace))
            scored.append((sim, trace))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def ingest_trace(self, trace: Trace) -> LessonCandidate | None:
        """Ingest one failed trace and create an inbox candidate when cluster size >= 3."""
        if trace.status != "failed":
            return None
        if not trace.errors_seen:
            return None

        embedding = self._embed_trace(trace)
        cluster_fingerprint = trace.errors_seen[0].strip().lower()[:160] or "unknown_failure"
        neighbors = self._nearest_cluster(
            domain=trace.domain,
            embedding=embedding,
            cluster_fingerprint=cluster_fingerprint,
        )
        bucket = self._recent_failed_by_fingerprint.setdefault(cluster_fingerprint, [])
        trace_neighbors = bucket[-8:]

        if len(neighbors) + len(trace_neighbors) + 1 < 3:
            bucket.append(trace)
            return None

        traces = [trace, *trace_neighbors]
        seen_trace_ids = {item.id for item in traces}
        for neighbor in neighbors[:6]:
            for trace_id in neighbor.evidence_trace_ids[:1]:
                if trace_id in seen_trace_ids:
                    continue
                found = self.store.get_trace(trace_id)
                if found is not None:
                    traces.append(found)
                    seen_trace_ids.add(trace_id)

        traces = traces[:8]

        existing_blocks = self.store.list_blocks(domain=trace.domain, include_deprecated=False)
        candidate = draft_lesson_candidate(
            traces=traces,
            domain=trace.domain,
            cluster_fingerprint=cluster_fingerprint,
            embedding=embedding,
            existing_blocks=existing_blocks,
        )
        self.store.upsert_lesson_candidate(candidate)
        bucket.append(trace)
        return candidate

    def inbox(self, *, domain: str | None = None, limit: int = 25) -> list[LessonCandidate]:
        return self.store.list_lesson_candidates(domain=domain, status="inbox", limit=limit)

    def decide(
        self,
        *,
        lesson_id: str,
        decision: str,
        reviewer: str,
        reason: str,
    ) -> dict[str, Any]:
        candidate = self.store.get_lesson_candidate(lesson_id)
        if candidate is None:
            raise ValueError(f"lesson not found: {lesson_id}")

        now = self._now()
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be 'approve' or 'reject'")

        candidate.reviewer = reviewer
        candidate.decision_reason = reason
        candidate.decision_at = now
        candidate.status = "approved" if decision == "approve" else "rejected"
        self.store.upsert_lesson_candidate(candidate)

        if decision == "reject":
            return {"lesson": candidate.model_dump(mode="json"), "promotion": None}

        promotion = self._promote(candidate)
        self.store.upsert_lesson_promotion(promotion)
        return {
            "lesson": candidate.model_dump(mode="json"),
            "promotion": promotion.model_dump(mode="json"),
        }

    def _promote(self, candidate: LessonCandidate) -> LessonPromotion:
        kind = str(getattr(candidate, "kind", ""))

        if kind in {"new_block", "reasonblock"}:
            block = candidate.proposed_block
            if block is None:
                # Fallback to the existing extractor path from evidence traces.
                trace_id = candidate.evidence_trace_ids[0]
                trace = self.store.get_trace(trace_id)
                if trace is None:
                    raise ValueError("missing evidence trace for new_block promotion")
                block = extract_candidate(trace).block
            self.store.upsert_block(block, write_markdown=False)
            return LessonPromotion(lesson_id=candidate.id, published_block_id=block.id)

        if kind == "edit_block":
            if not candidate.target_id:
                raise ValueError("edit_block promotion requires target_id")
            block = self.store.get_block(candidate.target_id)
            if block is None:
                raise ValueError(f"target block not found: {candidate.target_id}")
            dead_end = candidate.cluster_fingerprint
            if dead_end and dead_end not in block.dead_ends:
                block.dead_ends.append(dead_end)
                block.updated_at = self._now()
                self.store.upsert_block(block, write_markdown=False)
            return LessonPromotion(lesson_id=candidate.id, edited_block_id=block.id)

        if kind in {"new_rubric_check", "rubric_check"}:
            check = candidate.proposed_rubric_check
            if not check:
                raise ValueError("new_rubric_check promotion requires proposed_rubric_check")
            rubrics = self.store.list_rubrics(domain=candidate.domain)
            if rubrics:
                rubric = rubrics[0]
            else:
                rubric = Rubric(
                    id=f"rubric_{candidate.domain.replace('.', '_')}",
                    domain=candidate.domain,
                    required_checks=[],
                    block_if_missing=[],
                )
            if check not in rubric.required_checks:
                rubric.required_checks.append(check)
            if check not in rubric.block_if_missing:
                rubric.block_if_missing.append(check)
            self.store.upsert_rubric(rubric, write_yaml=False)
            return LessonPromotion(lesson_id=candidate.id)

        raise ValueError(f"unsupported lesson candidate kind: {candidate.kind}")
