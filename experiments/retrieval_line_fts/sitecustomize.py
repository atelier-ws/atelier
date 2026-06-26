"""Opt-in retrieval experiment: fuse whole-file line FTS into explore anchors.

Activated only when ``ATELIER_EXPERIMENT_LINE_FTS=1``. Keeping this as a
``sitecustomize`` hook lets the benchmark run the normal CLI unchanged while
isolating the experiment from production code.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any


def _install() -> None:
    if os.environ.get("ATELIER_EXPERIMENT_LINE_FTS") != "1":
        return

    from atelier.core.capabilities.code_context import engine as engine_mod

    engine_cls = engine_mod.CodeContextEngine
    if getattr(engine_cls, "_line_fts_experiment_installed", False):
        return

    original_zoekt = engine_cls._zoekt_candidate_files

    def line_fts_candidate_files(self: Any, query: str, *, max_files: int = 40) -> list[str]:
        normalized = query.strip()
        if not normalized or max_files <= 0:
            return []

        query_terms = list(dict.fromkeys(engine_mod._query_terms(normalized)))[:12]
        if engine_mod._is_precise_symbol_query(normalized) or "|" in normalized or len(query_terms) < 5:
            return []

        or_query = engine_mod._safe_fts_query(normalized)
        if not or_query:
            return []
        and_query = engine_mod._fts_and_query(normalized)
        query_term_set = set(query_terms)
        and_limit = min(max(max_files * 16, 160), 640)
        or_limit = min(max(max_files * 40, 320), 1600)

        rows: list[tuple[Any, bool]] = []
        try:
            with self._connect(readonly=True) as conn:
                self._init_schema(conn)
                if and_query:
                    and_rows = conn.execute(
                        """
                        SELECT file_path, line, text, bm25(file_line_fts) AS rank
                        FROM file_line_fts
                        WHERE file_line_fts MATCH ? AND repo_id = ?
                        ORDER BY rank ASC, file_path ASC, line ASC
                        LIMIT ?
                        """,
                        (and_query, self.repo_id, and_limit),
                    ).fetchall()
                    rows.extend((row, True) for row in and_rows)

                or_rows = conn.execute(
                    """
                    SELECT file_path, line, text, bm25(file_line_fts) AS rank
                    FROM file_line_fts
                    WHERE file_line_fts MATCH ? AND repo_id = ?
                    ORDER BY rank ASC, file_path ASC, line ASC
                    LIMIT ?
                    """,
                    (or_query, self.repo_id, or_limit),
                ).fetchall()
                rows.extend((row, False) for row in or_rows)
        except Exception:
            return []

        query_wants_tests = bool(re.search(r"\btest\b|\bspec\b", normalized, re.IGNORECASE))
        evidence: dict[str, dict[str, Any]] = {}
        for row, from_and in rows:
            file_path = str(row["file_path"] or "")
            if not file_path:
                continue
            if engine_mod.is_generated_path(file_path):
                continue
            if engine_mod._MINIFIED_FILE_RE.search(file_path) or engine_mod._VENDOR_PATH_RE.search(file_path):
                continue

            rank = float(row["rank"] or 0.0)
            text = str(row["text"] or "").lower()
            item = evidence.setdefault(
                file_path,
                {"best_rank": rank, "hit_count": 0, "covered_terms": set(), "and_hit": False},
            )
            item["best_rank"] = min(float(item["best_rank"]), rank)
            item["hit_count"] = int(item["hit_count"]) + 1
            item["and_hit"] = bool(item["and_hit"] or from_and)
            item["covered_terms"].update(term for term in query_terms if term in text)

        scored: list[tuple[int, float, str]] = []
        for file_path, item in evidence.items():
            path_terms = set(re.split(r"[/._-]+", file_path.lower()))
            path_overlap = len(query_term_set & path_terms)
            coverage = len(item["covered_terms"]) / max(1, len(query_term_set))
            repeated_evidence = min(math.log1p(int(item["hit_count"])), 3.0)
            score = (
                float(item["best_rank"])
                - 1.20 * coverage
                - 0.12 * repeated_evidence
                - 0.40 * path_overlap
                - (0.75 if item["and_hit"] else 0.0)
            )
            test_bucket = 1 if not query_wants_tests and engine_mod._TEST_PATH_RE.search(file_path) else 0
            scored.append((test_bucket, score, file_path))

        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        return [file_path for _, _, file_path in scored[:max_files]]

    def zoekt_plus_line_fts(self: Any, query: str, *, path: str = ".", max_files: int = 40) -> list[str]:
        zoekt_files = original_zoekt(self, query, path=path, max_files=max_files)
        line_files = line_fts_candidate_files(self, query, max_files=max_files)
        return list(dict.fromkeys([*zoekt_files, *line_files]))[:max_files]

    engine_cls._line_fts_candidate_files = line_fts_candidate_files
    engine_cls._zoekt_candidate_files = zoekt_plus_line_fts
    engine_cls._line_fts_experiment_installed = True


_install()
