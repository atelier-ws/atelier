"""Opt-in retrieval experiment: post-retrieval whole-file FTS fusion.

Activated only when ``ATELIER_EXPERIMENT_LINE_FTS=1``.  The production engine
is left untouched: this module is loaded through ``PYTHONPATH``/sitecustomize
for benchmark runs only.

The previous experiment patched ``_zoekt_candidate_files`` by appending line-FTS
results after Zoekt and truncating to the original limit.  Zoekt normally filled
that limit, making the experiment effectively a no-op.  This version performs
file-level reciprocal-rank fusion *after* the normal explore result is built, so
whole-file evidence can actually enter and reorder the top-10 file list.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any


_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|pyi|js|jsx|ts|tsx|java|rb|go|rs|c|cc|cpp|h|hpp)", re.IGNORECASE)


def _install() -> None:
    if os.environ.get("ATELIER_EXPERIMENT_LINE_FTS") != "1":
        return

    from atelier.core.capabilities.code_context import engine as engine_mod

    engine_cls = engine_mod.CodeContextEngine
    if getattr(engine_cls, "_line_fts_experiment_installed", False):
        return

    original_tool_explore = engine_cls.tool_explore

    def line_fts_candidate_files(self: Any, query: str, *, max_files: int = 50) -> list[str]:
        normalized = query.strip()
        if not normalized or max_files <= 0:
            return []

        # Exact/symbol-shaped lookups are already the strongest part of the baseline.
        # File-body fusion is intended for issue-style concept queries.
        if engine_mod._is_precise_symbol_query(normalized):
            return []

        query_terms = list(dict.fromkeys(engine_mod._query_terms(normalized)))[:16]
        if len(query_terms) < 2:
            return []

        or_query = engine_mod._safe_fts_query(normalized)
        if not or_query:
            return []
        and_query = engine_mod._fts_and_query(normalized)
        query_term_set = {term.lower() for term in query_terms}
        mentioned_paths = {token.lower().lstrip("./") for token in _PATH_TOKEN_RE.findall(normalized)}

        and_limit = min(max(max_files * 20, 240), 1200)
        or_limit = min(max(max_files * 60, 800), 3000)
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

        query_wants_tests = bool(re.search(r"\btest(?:s|ing)?\b|\bspec\b", normalized, re.IGNORECASE))
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
                {
                    "best_rank": rank,
                    "hit_count": 0,
                    "covered_terms": set(),
                    "and_hit": False,
                },
            )
            item["best_rank"] = min(float(item["best_rank"]), rank)
            item["hit_count"] = int(item["hit_count"]) + 1
            item["and_hit"] = bool(item["and_hit"] or from_and)
            item["covered_terms"].update(term for term in query_term_set if term in text)

        scored: list[tuple[int, float, str]] = []
        for file_path, item in evidence.items():
            path_lower = file_path.lower().lstrip("./")
            path_terms = set(re.split(r"[/._-]+", path_lower))
            path_overlap = len(query_term_set & path_terms)
            coverage = len(item["covered_terms"]) / max(1, len(query_term_set))
            repeated_evidence = min(math.log1p(int(item["hit_count"])), 4.0)
            explicit_path = any(path_lower.endswith(token) or token.endswith(path_lower) for token in mentioned_paths)
            score = (
                float(item["best_rank"])
                - 1.80 * coverage
                - 0.18 * repeated_evidence
                - 0.45 * path_overlap
                - (1.10 if item["and_hit"] else 0.0)
                - (5.00 if explicit_path else 0.0)
            )
            test_bucket = 1 if not query_wants_tests and engine_mod._TEST_PATH_RE.search(file_path) else 0
            scored.append((test_bucket, score, file_path))

        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        return [file_path for _, _, file_path in scored[:max_files]]

    def fused_tool_explore(self: Any, query: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = original_tool_explore(self, query, *args, **kwargs)
        if not isinstance(payload, dict):
            return payload

        raw_files = payload.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            return payload

        max_files = max(1, min(int(kwargs.get("max_files", 6)), 10))
        baseline_entries: dict[str, dict[str, Any]] = {}
        baseline_files: list[str] = []
        for entry in raw_files:
            if not isinstance(entry, dict):
                continue
            file_path = str(entry.get("path") or entry.get("file_path") or "")
            if file_path and file_path not in baseline_entries:
                baseline_entries[file_path] = entry
                baseline_files.append(file_path)

        line_files = line_fts_candidate_files(self, query, max_files=max(40, max_files * 6))
        if not line_files:
            return payload

        mode = os.environ.get("ATELIER_EXPERIMENT_FUSION_MODE", "balanced").strip().lower()
        line_weight = {
            "conservative": 0.55,
            "balanced": 0.90,
            "aggressive": 1.25,
        }.get(mode, 0.90)
        baseline_weight = 1.0
        rrf_k = 20.0

        scores: dict[str, float] = {}
        for rank, file_path in enumerate(baseline_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + baseline_weight / (rrf_k + rank)
        for rank, file_path in enumerate(line_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + line_weight / (rrf_k + rank)

        query_terms = {term.lower() for term in engine_mod._query_terms(query)}
        mentioned_paths = {token.lower().lstrip("./") for token in _PATH_TOKEN_RE.findall(query)}
        query_wants_tests = bool(re.search(r"\btest(?:s|ing)?\b|\bspec\b", query, re.IGNORECASE))
        for file_path in list(scores):
            path_lower = file_path.lower().lstrip("./")
            path_terms = set(re.split(r"[/._-]+", path_lower))
            scores[file_path] += 0.0025 * len(query_terms & path_terms)
            if any(path_lower.endswith(token) or token.endswith(path_lower) for token in mentioned_paths):
                scores[file_path] += 0.08
            if not query_wants_tests and engine_mod._TEST_PATH_RE.search(file_path):
                scores[file_path] *= 0.72

        baseline_rank = {file_path: rank for rank, file_path in enumerate(baseline_files, start=1)}
        line_rank = {file_path: rank for rank, file_path in enumerate(line_files, start=1)}
        ordered = sorted(
            scores,
            key=lambda file_path: (
                -scores[file_path],
                baseline_rank.get(file_path, 10_000),
                line_rank.get(file_path, 10_000),
                file_path,
            ),
        )[:max_files]

        fused_entries: list[dict[str, Any]] = []
        for file_path in ordered:
            existing = baseline_entries.get(file_path)
            if existing is not None:
                fused_entries.append(existing)
            else:
                # Keep the experiment output schema-compatible while avoiding a
                # second symbol/source hydration pass.  The benchmark scores files,
                # and production code remains unchanged.
                fused_entries.append(
                    {
                        "path": file_path,
                        "language": "unknown",
                        "symbols": [],
                        "source_sections": [],
                    }
                )

        result = dict(payload)
        result["files"] = fused_entries
        result["experiment"] = {
            "name": "post_retrieval_line_fts_rrf",
            "mode": mode,
            "line_weight": line_weight,
        }
        return result

    engine_cls._line_fts_candidate_files = line_fts_candidate_files
    engine_cls._file_fusion_original_tool_explore = original_tool_explore
    engine_cls.tool_explore = fused_tool_explore
    engine_cls._line_fts_experiment_installed = True


_install()
