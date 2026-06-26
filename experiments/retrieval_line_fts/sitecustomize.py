"""Opt-in retrieval experiment: fuse whole-file line FTS into explore anchors.

Activated only when ATELIER_EXPERIMENT_LINE_FTS=1. Keeping this as a
sitecustomize hook lets the benchmark run the normal public CLI unchanged while
isolating the experiment from production code.
"""

from __future__ import annotations

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
        fts_query = engine_mod._safe_fts_query(normalized)
        if not fts_query:
            return []

        try:
            with self._connect(readonly=True) as conn:
                self._init_schema(conn)
                rows = conn.execute(
                    """
                    SELECT file_path, bm25(file_line_fts) AS rank
                    FROM file_line_fts
                    WHERE file_line_fts MATCH ? AND repo_id = ?
                    ORDER BY rank ASC, file_path ASC, line ASC
                    LIMIT ?
                    """,
                    (fts_query, self.repo_id, max(max_files * 24, 120)),
                ).fetchall()
        except Exception:
            return []

        query_wants_tests = bool(re.search(r"\btest\b|\bspec\b", normalized, re.IGNORECASE))
        preferred: list[str] = []
        test_fallback: list[str] = []
        seen: set[str] = set()
        for row in rows:
            file_path = str(row["file_path"] or "")
            if not file_path or file_path in seen:
                continue
            if engine_mod.is_generated_path(file_path):
                continue
            if engine_mod._MINIFIED_FILE_RE.search(file_path) or engine_mod._VENDOR_PATH_RE.search(file_path):
                continue
            seen.add(file_path)
            if not query_wants_tests and engine_mod._TEST_PATH_RE.search(file_path):
                test_fallback.append(file_path)
            else:
                preferred.append(file_path)
            if len(preferred) >= max_files:
                break
        return (preferred + test_fallback)[:max_files]

    def zoekt_plus_line_fts(self: Any, query: str, *, path: str = ".", max_files: int = 40) -> list[str]:
        zoekt_files = original_zoekt(self, query, path=path, max_files=max_files)
        line_files = line_fts_candidate_files(self, query, max_files=max_files)
        return list(dict.fromkeys([*zoekt_files, *line_files]))[:max_files]

    engine_cls._line_fts_candidate_files = line_fts_candidate_files
    engine_cls._zoekt_candidate_files = zoekt_plus_line_fts
    engine_cls._line_fts_experiment_installed = True


_install()
