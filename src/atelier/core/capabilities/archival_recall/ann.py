"""Persistent-backed ANN retrieval over archival passage embeddings (G5).

Archival passages are persisted by the memory store and carry their own vector
provenance (``embedding`` + ``embedding_model`` + ``embedding_provenance``). This
module layers an opt-in approximate-nearest-neighbour pre-filter over that
persisted set so cosine ranking does not have to brute-force every passage,
while preserving exact results.

Guards (mirroring the code-symbol ANN, WS7):

N5 (drift invalidation)
    Only passages whose ``embedding_model`` matches the live embedder model-id
    AND whose embedding dim matches the query are admitted to the ANN. A model
    or dim change makes the older passages ineligible, so neighbours are never
    recovered from a stale model or a foreign vector space.

Index-version keying (N16-style)
    The cached HNSW graph is keyed to ``(model_id, dim, signature)`` where the
    signature is a content fingerprint of the eligible passage set (count + the
    newest passage id). Any archive/evict mutation changes the signature, which
    rebuilds the graph -- a mutation can never serve stale neighbours.

Most-recent-N exact tail (mandatory)
    The newest ``recent_exact`` passages are always retained as exact candidates
    regardless of ANN recall, so just-stored memory is never missed by the
    approximate index.

Brute-force fallback (mandatory)
    Exact cosine is the fallback when the eligible set is small, ``datasketch``
    is unavailable, or an ANN query raises -- so a missing optional dependency
    never breaks recall.

Default-safe
    Nothing here runs unless the caller opts in (``ATELIER_ANN_RETRIEVAL``); with
    the flag off, archival ranking is byte-identical to today.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from atelier.core.foundation.memory_models import ArchivalPassage
from atelier.infra.storage.vector import cosine_similarity

logger = logging.getLogger(__name__)

_HNSW: Any = None
try:
    from datasketch import HNSW as _HNSW_cls

    _HNSW = _HNSW_cls
except ImportError:
    logger.warning(
        "datasketch.HNSW unavailable; ANN archival recall will use brute-force cosine",
        exc_info=True,
    )

# Below this many eligible passages, exact cosine is faster and exact.
_ANN_MIN_PASSAGES = 16
# Newest passages always kept as exact candidates so just-stored memory is never
# invisible to the approximate index.
_RECENT_EXACT = 8
_ANN_OVERFETCH = 4
# A passage is only ANN-eligible when its stored provenance is a real embedder
# stamp; the legacy stub never carries a usable vector space.
_LEGACY_STUB = "legacy_stub"


def ann_retrieval_enabled(env: Any | None = None) -> bool:
    """Return True when the opt-in ANN retrieval path is enabled (default off)."""
    from atelier.core.environment import bool_env

    return bool_env("ATELIER_ANN_RETRIEVAL", default=False, env=env)


def _ann_distance(a: Any, b: Any) -> float:
    return 1.0 - cosine_similarity(list(a), list(b))


class ArchivalAnnIndex:
    """Opt-in ANN pre-filter over archival passage embeddings (N5 + N16 + tail)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._graph: Any = None
        self._graph_key: tuple[str, int, str] | None = None

    def _eligible(
        self,
        passages: list[ArchivalPassage],
        *,
        model_id: str,
        dim: int,
    ) -> list[ArchivalPassage]:
        """Passages whose vector matches the live model-id and dim (N5 gate)."""
        if dim <= 0 or not model_id:
            return []
        out: list[ArchivalPassage] = []
        for passage in passages:
            if not passage.embedding or len(passage.embedding) != dim:
                continue
            if passage.embedding_provenance == _LEGACY_STUB:
                continue
            if passage.embedding_model != model_id:
                continue
            out.append(passage)
        return out

    def _signature(self, eligible: list[ArchivalPassage]) -> str:
        """Content fingerprint of the eligible passage set (N16 staleness key)."""
        if not eligible:
            return "0:"
        newest = max(eligible, key=lambda p: (p.created_at, p.id))
        return f"{len(eligible)}:{newest.id}"

    def candidate_ids(
        self,
        query_embedding: list[float],
        passages: list[ArchivalPassage],
        *,
        model_id: str,
        dim: int,
        top_k: int,
    ) -> set[str] | None:
        """Return the ANN-narrowed candidate passage ids, or None to mean "all".

        ``None`` signals the caller to keep every passage (small set, ineligible
        set, or HNSW unavailable -> brute-force fallback). When an id set is
        returned it always includes the most-recent-N passages so just-stored
        memory is never dropped by the approximate index.
        """
        if not query_embedding or len(query_embedding) != dim:
            return None
        eligible = self._eligible(passages, model_id=model_id, dim=dim)
        if len(eligible) < _ANN_MIN_PASSAGES or _HNSW is None:
            return None
        recent = sorted(eligible, key=lambda p: (p.created_at, p.id), reverse=True)[:_RECENT_EXACT]
        recent_ids = {p.id for p in recent}
        ann_ids = self._ann_neighbour_ids(query_embedding, eligible, top_k=top_k, model_id=model_id, dim=dim)
        if ann_ids is None:
            return None
        return ann_ids | recent_ids

    def _ann_neighbour_ids(
        self,
        query_embedding: list[float],
        eligible: list[ArchivalPassage],
        *,
        top_k: int,
        model_id: str,
        dim: int,
    ) -> set[str] | None:
        graph = self._ensure_graph(eligible, model_id=model_id, dim=dim)
        if graph is None:
            return None
        try:
            import numpy as np

            neighbours = graph.query(
                np.asarray(query_embedding, dtype="float64"),
                k=max(top_k * _ANN_OVERFETCH, top_k),
            )
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return None
        return {str(key) for key, _distance in neighbours}

    def _ensure_graph(
        self,
        eligible: list[ArchivalPassage],
        *,
        model_id: str,
        dim: int,
    ) -> Any:
        if _HNSW is None:
            return None
        key = (model_id, dim, self._signature(eligible))
        with self._lock:
            if self._graph is not None and self._graph_key == key:
                return self._graph
            try:
                import numpy as np

                graph = _HNSW(distance_func=_ann_distance)
                for passage in eligible:
                    graph.insert(passage.id, np.asarray(passage.embedding, dtype="float64"))
            except Exception:
                logging.exception("Recovered from broad exception handler")
                self._graph = None
                self._graph_key = None
                return None
            self._graph = graph
            self._graph_key = key
            return graph

    def invalidate(self) -> None:
        with self._lock:
            self._graph = None
            self._graph_key = None


__all__ = ["ArchivalAnnIndex", "ann_retrieval_enabled"]
