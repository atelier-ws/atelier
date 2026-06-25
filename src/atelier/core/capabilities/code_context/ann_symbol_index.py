"""Persistent ANN retrieval over code-symbol embeddings (G4 / N5 / N16).

This module backs the opt-in approximate-nearest-neighbour path for semantic
symbol search. It persists one embedding per symbol -- stamped with the
embedder model-id, embedding dimension, and the engine ``index_version`` -- and
builds a ``datasketch.HNSW`` index (the same lib family already used for
context-reuse dedup) over the vectors that belong to the *current* embedder and
index version.

Guards (all mandatory, see WS7):

N5 (drift invalidation)
    Every stored vector carries ``embedder_name`` (model-id) + ``embedding_dim``.
    A neighbour is only ever served from vectors whose stamp matches the live
    embedder. A model-id or dim change makes the old vectors ineligible: they are
    lazily re-embedded / overwritten rather than mixed into a foreign vector
    space. ``cosine`` never compares across dims.

Index-version keying (N16-style)
    The in-memory ANN graph is cached keyed to
    ``(index_version, embedder_name, embedding_dim)``. Any reindex bumps
    ``index_version`` (engine), which invalidates the cached graph so a mutation
    can never serve stale neighbours.

Brute-force fallback (mandatory)
    Exact cosine is always available and is used when: the candidate set is
    small (below ``_ANN_MIN_VECTORS``), ``datasketch`` / the HNSW class is
    unavailable, the freshly-stored vectors have not yet been folded into the
    graph, or an ANN query raises. Freshly-stored symbols are therefore never
    invisible and a missing optional dependency never breaks search.

Default-safe
    Nothing here runs unless the caller opts in (``ATELIER_ANN_RETRIEVAL``). The
    table is created lazily on first persist, so with the flag off the engine
    schema, candidate generation, and ranking are byte-identical to today.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from atelier.infra.storage.vector import cosine_similarity

logger = logging.getLogger(__name__)

# HNSW removed (datasketch dropped); brute-force cosine is the permanent fallback.
# _graph and _graph_key stay None permanently; query() always uses exact cosine.
_HNSW: Any = None

# Below this many eligible vectors, exact cosine is both faster and exact, so the
# graph is skipped entirely. Above it the HNSW index amortises the build cost.
_ANN_MIN_VECTORS = 16
# Over-fetch factor: pull more ANN neighbours than requested so the exact-cosine
# re-score step has headroom to recover the true top-k from approximate ordering.
_ANN_OVERFETCH = 4


def _ann_distance(a: Any, b: Any) -> float:
    """Cosine *distance* in [0, 2] for HNSW (smaller = closer).

    Wraps the shared :func:`cosine_similarity` so the ANN graph and the
    brute-force fallback agree on the metric. Inputs arrive as numpy arrays from
    datasketch; ``cosine_similarity`` accepts any sequence of floats.
    """
    return 1.0 - cosine_similarity(list(a), list(b))


@dataclass(frozen=True)
class _StoredVector:
    symbol_id: str
    vector: list[float]


def ann_retrieval_enabled(env: Any | None = None) -> bool:
    """Return True when the opt-in ANN retrieval path is enabled.

    Default-off: with ``ATELIER_ANN_RETRIEVAL`` unset, the engine keeps its
    existing positional-scan + brute-force-cosine semantic path unchanged.
    """
    from atelier.core.environment import bool_env

    return bool_env("ATELIER_ANN_RETRIEVAL", default=False, env=env)


def ensure_symbol_vector_schema(conn: sqlite3.Connection) -> None:
    """Create the persistent per-symbol vector table (provenance-stamped).

    Created lazily (only on the opt-in path) so the default schema is unchanged.
    The ``embedder_name`` + ``embedding_dim`` columns are the N5 drift stamp;
    ``index_version`` is the N16 staleness key.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbol_vectors (
            repo_id        TEXT NOT NULL,
            symbol_id      TEXT NOT NULL,
            content_hash   TEXT NOT NULL,
            embedder_name  TEXT NOT NULL,
            embedding_dim  INTEGER NOT NULL,
            index_version  INTEGER NOT NULL,
            vector_json    TEXT NOT NULL,
            PRIMARY KEY (repo_id, symbol_id)
        )
        """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_symbol_vectors_provenance "
        "ON symbol_vectors(repo_id, embedder_name, embedding_dim, index_version)"
    )


class SymbolAnnIndex:
    """Persistent ANN over per-symbol embeddings with N5 + N16 + fallback guards.

    One instance is held per engine. It owns the persisted vectors (read/write
    through the engine's sqlite connection) and a lazily-built in-memory HNSW
    graph cached against ``(index_version, embedder_name, embedding_dim)``.
    """

    def __init__(self, repo_id: str) -> None:
        self.repo_id = repo_id
        self._lock = threading.Lock()
        self._graph: Any = None
        self._graph_key: tuple[int, str, int] | None = None
        self._graph_ids: set[str] = set()
        self._schema_ready: bool = False

    # -- schema guard ----------------------------------------------------

    def _ensure_vector_schema(self, conn: sqlite3.Connection) -> None:
        if self._schema_ready:
            return
        ensure_symbol_vector_schema(conn)
        self._schema_ready = True

    # -- persistence -----------------------------------------------------

    def upsert_vectors(
        self,
        conn: sqlite3.Connection,
        *,
        embedder_name: str,
        embedding_dim: int,
        index_version: int,
        vectors: dict[str, tuple[str, list[float]]],
    ) -> None:
        """Persist ``symbol_id -> (content_hash, vector)`` with provenance stamps.

        Vectors whose dim does not match ``embedding_dim`` are skipped (never
        stored in a foreign vector space). Re-storing a symbol overwrites its
        prior stamp, so a model/dim/version change cleanly supersedes the old
        row instead of mixing spaces.
        """
        if embedding_dim <= 0 or not vectors:
            return
        self._ensure_vector_schema(conn)
        rows = [
            (self.repo_id, symbol_id, content_hash, embedder_name, embedding_dim, index_version, json.dumps(vector))
            for symbol_id, (content_hash, vector) in vectors.items()
            if len(vector) == embedding_dim
        ]
        if not rows:
            return
        conn.executemany(
            """
            INSERT INTO symbol_vectors
                (repo_id, symbol_id, content_hash, embedder_name, embedding_dim, index_version, vector_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo_id, symbol_id) DO UPDATE SET
                content_hash  = excluded.content_hash,
                embedder_name = excluded.embedder_name,
                embedding_dim = excluded.embedding_dim,
                index_version = excluded.index_version,
                vector_json   = excluded.vector_json
            """,
            rows,
        )
        conn.commit()

    def load_current_vectors(
        self,
        conn: sqlite3.Connection,
        *,
        embedder_name: str,
        embedding_dim: int,
    ) -> list[_StoredVector]:
        """Return stored vectors that match the live embedder stamp (N5 gate).

        Only rows with the current ``embedder_name`` AND ``embedding_dim`` are
        returned, so neighbours are never recovered from a stale model or a
        foreign vector space.
        """
        if embedding_dim <= 0:
            return []
        try:
            self._ensure_vector_schema(conn)
            rows = conn.execute(
                """
                SELECT symbol_id, vector_json FROM symbol_vectors
                WHERE repo_id = ? AND embedder_name = ? AND embedding_dim = ?
                """,
                (self.repo_id, embedder_name, embedding_dim),
            ).fetchall()
        except sqlite3.Error:
            logging.exception("Recovered from broad exception handler")
            return []
        out: list[_StoredVector] = []
        for row in rows:
            try:
                payload = json.loads(str(row[1]))
            except (TypeError, ValueError, json.JSONDecodeError):
                logging.exception("Recovered from broad exception handler")
                continue
            if isinstance(payload, list) and len(payload) == embedding_dim:
                out.append(_StoredVector(symbol_id=str(row[0]), vector=[float(x) for x in payload]))
        return out

    def existing_stamped_ids(
        self,
        conn: sqlite3.Connection,
        *,
        embedder_name: str,
        embedding_dim: int,
    ) -> set[str]:
        """Symbol ids with a current-model/dim vector already stored.

        Freshness is content-based, not version-based: ``symbol_id`` encodes the
        file content hash, so an id present here is fresh by construction -- any
        content change yields a new id (its stale row is pruned when the file is
        re-indexed). ``index_version`` is provenance only and is deliberately
        NOT a filter here -- gating on it would treat every post-bump reindex as
        a full re-embed. This matches ``load_current_vectors``, which also keys
        eligibility on (embedder_name, embedding_dim) alone.
        """
        if embedding_dim <= 0:
            return set()
        try:
            self._ensure_vector_schema(conn)
            rows = conn.execute(
                """
                SELECT symbol_id FROM symbol_vectors
                WHERE repo_id = ? AND embedder_name = ? AND embedding_dim = ?
                """,
                (self.repo_id, embedder_name, embedding_dim),
            ).fetchall()
        except sqlite3.Error:
            logging.exception("Recovered from broad exception handler")
            return set()
        return {str(row[0]) for row in rows}

    # -- query -----------------------------------------------------------

    def query(
        self,
        query_vector: list[float],
        stored: list[_StoredVector],
        *,
        limit: int,
        index_version: int,
        embedder_name: str,
        embedding_dim: int,
    ) -> list[str]:
        """Return up to ``limit`` symbol ids ranked by cosine to the query.

        Approximate (HNSW) when there are enough vectors and the lib is present,
        otherwise exact brute-force cosine. The ANN result is always re-scored
        with exact cosine, so the returned ordering matches brute-force for the
        recovered neighbours (parity).
        """
        if not query_vector or not stored or len(query_vector) != embedding_dim:
            return []
        use_ann = _HNSW is not None and len(stored) >= _ANN_MIN_VECTORS
        candidate_ids: list[str]
        if use_ann:
            candidate_ids = self._ann_candidate_ids(
                query_vector,
                stored,
                limit=limit,
                index_version=index_version,
                embedder_name=embedder_name,
                embedding_dim=embedding_dim,
            )
            if not candidate_ids:
                candidate_ids = [sv.symbol_id for sv in stored]
        else:
            candidate_ids = [sv.symbol_id for sv in stored]
        by_id = {sv.symbol_id: sv.vector for sv in stored}
        scored: list[tuple[float, str]] = []
        for symbol_id in candidate_ids:
            vector = by_id.get(symbol_id)
            if vector is None:
                continue
            score = cosine_similarity(query_vector, vector)
            if score <= 0:
                continue
            scored.append((score, symbol_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [symbol_id for _, symbol_id in scored[:limit]]

    def _ann_candidate_ids(
        self,
        query_vector: list[float],
        stored: list[_StoredVector],
        *,
        limit: int,
        index_version: int,
        embedder_name: str,
        embedding_dim: int,
    ) -> list[str]:
        graph = self._ensure_graph(
            stored,
            index_version=index_version,
            embedder_name=embedder_name,
            embedding_dim=embedding_dim,
        )
        if graph is None:
            return []
        try:
            import numpy as np

            neighbours = graph.query(np.asarray(query_vector, dtype="float64"), k=max(limit * _ANN_OVERFETCH, limit))
        except Exception:
            # A graph query failure must degrade to brute-force, never break search.
            logging.exception("Recovered from broad exception handler")
            return []
        return [str(key) for key, _distance in neighbours]

    def _ensure_graph(
        self,
        stored: list[_StoredVector],
        *,
        index_version: int,
        embedder_name: str,
        embedding_dim: int,
    ) -> Any:
        """Return a cached HNSW graph, rebuilding on an N16/N5 key change.

        The cache key is ``(index_version, embedder_name, embedding_dim)``: a
        reindex (version bump), a model swap, or a dim change all force a fresh
        graph, so stale or cross-space neighbours can never be served. If the
        persisted vector set has grown/shrunk since the cached build (freshly
        stored symbols), the graph is also rebuilt rather than missing them.
        """
        if _HNSW is None:
            return None
        key = (index_version, embedder_name, embedding_dim)
        current_ids = {sv.symbol_id for sv in stored}
        with self._lock:
            if self._graph is not None and self._graph_key == key and self._graph_ids == current_ids:
                return self._graph
            try:
                import numpy as np

                graph = _HNSW(distance_func=_ann_distance)
                for sv in stored:
                    graph.insert(sv.symbol_id, np.asarray(sv.vector, dtype="float64"))
            except Exception:
                logging.exception("Recovered from broad exception handler")
                self._graph = None
                self._graph_key = None
                self._graph_ids = set()
                return None
            self._graph = graph
            self._graph_key = key
            self._graph_ids = current_ids
            return graph

    def invalidate(self) -> None:
        """Drop the cached graph (e.g. after a reindex). Persisted rows are kept."""
        with self._lock:
            self._graph = None
            self._graph_key = None
            self._graph_ids = set()


__all__ = [
    "SymbolAnnIndex",
    "ann_retrieval_enabled",
    "ensure_symbol_vector_schema",
]
