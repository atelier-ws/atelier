"""Opt-in retrieval experiment: rare-symbol voting + captured Zoekt fusion.

Activate with ``ATELIER_EXPERIMENT_SYMBOL_VOTE=1`` and put this directory on
``PYTHONPATH``. This is benchmark-only code: production retrieval is unchanged.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TEST_RE = re.compile(r"(^|/)(tests?|testing|specs?)(/|$)|(^|/)test_[^/]+$", re.IGNORECASE)
_STOP = {
    "and", "as", "assert", "async", "await", "break", "case", "class",
    "continue", "def", "del", "do", "else", "except", "false", "finally",
    "for", "from", "if", "import", "in", "is", "lambda", "none", "not",
    "or", "pass", "raise", "return", "self", "super", "true", "try",
    "while", "with", "yield",
}


def _informative_tokens(query: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _IDENTIFIER_RE.findall(query):
        low = token.lower()
        if low in seen or low in _STOP or len(token) < 3:
            continue
        compound = "_" in token or any(ch.isupper() for ch in token[1:]) or token.isupper()
        if not compound and len(token) < 6:
            continue
        if low in {"__init__", "__call__", "__new__", "tests", "testing"}:
            continue
        seen.add(low)
        out.append(token)
    return out[:16]


def _path_parts(file_path: str) -> set[str]:
    return {part for part in re.split(r"[/._-]+", file_path.lower()) if part}


def _append_diagnostic(payload: dict[str, Any]) -> None:
    target = os.environ.get("ATELIER_EXPERIMENT_DIAGNOSTICS", "").strip()
    if not target:
        return
    try:
        line = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fd = os.open(target, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        pass


def _install() -> None:
    if os.environ.get("ATELIER_EXPERIMENT_SYMBOL_VOTE") != "1":
        return

    from atelier.core.capabilities.code_context import engine as engine_mod

    engine_cls = engine_mod.CodeContextEngine
    if getattr(engine_cls, "_symbol_vote_experiment_installed", False):
        return

    original_tool_explore = engine_cls.tool_explore
    original_zoekt = engine_cls._zoekt_candidate_files

    def capturing_zoekt(self: Any, query: str, *, path: str = ".", max_files: int = 40) -> list[str]:
        overfetch = max(max_files, int(os.environ.get("ATELIER_EXPERIMENT_ZOEKT_FILES", "80")))
        files = original_zoekt(self, query, path=path, max_files=overfetch)
        self.__dict__["_symbol_vote_zoekt_capture"] = (query, files)
        return files[:max_files]

    def exact_file_votes(self: Any, query: str) -> tuple[list[str], dict[str, float], dict[str, int]]:
        tokens = _informative_tokens(query)
        if not tokens:
            return [], {}, {}

        token_by_lower = {token.lower(): token for token in tokens}
        placeholders = ",".join("?" for _ in token_by_lower)
        try:
            with self._connect(readonly=True) as conn:
                freq_rows = conn.execute(
                    f"""
                    SELECT lower(symbol_name) AS token, COUNT(DISTINCT file_path) AS df
                    FROM symbols
                    WHERE repo_id = ? AND lower(symbol_name) IN ({placeholders})
                    GROUP BY lower(symbol_name)
                    """,
                    (self.repo_id, *token_by_lower),
                ).fetchall()
                frequencies = {str(row["token"]): int(row["df"]) for row in freq_rows}
                rare = {token for token, df in frequencies.items() if 0 < df <= 48}
                if not rare:
                    return tokens, {}, frequencies
                rare_placeholders = ",".join("?" for _ in rare)
                rows = conn.execute(
                    f"""
                    SELECT file_path, lower(symbol_name) AS token, kind
                    FROM symbols
                    WHERE repo_id = ? AND lower(symbol_name) IN ({rare_placeholders})
                    ORDER BY file_path, start_line
                    """,
                    (self.repo_id, *sorted(rare)),
                ).fetchall()
        except Exception:
            return tokens, {}, {}

        per_file_token: dict[str, dict[str, float]] = {}
        definition_kinds = set(getattr(engine_mod, "_DEFINITION_KINDS", {"class", "function", "method"}))
        for row in rows:
            file_path = str(row["file_path"] or "")
            token = str(row["token"] or "")
            if not file_path or not token:
                continue
            df = max(1, frequencies.get(token, 1))
            original = token_by_lower.get(token, token)
            shape = 1.0
            if "_" in original:
                shape += 0.20
            if original.isupper() or any(ch.isupper() for ch in original[1:]):
                shape += 0.15
            shape += min(len(original), 20) / 100.0
            rarity = 1.0 / math.log2(df + 1.0)
            kind_boost = 1.20 if str(row["kind"] or "").lower() in definition_kinds else 0.85
            vote = 0.22 * shape * rarity * kind_boost
            current = per_file_token.setdefault(file_path, {}).get(token, 0.0)
            if vote > current:
                per_file_token[file_path][token] = vote

        votes: dict[str, float] = {}
        for file_path, token_votes in per_file_token.items():
            votes[file_path] = sum(token_votes.values()) + 0.045 * max(0, len(token_votes) - 1)
        return tokens, votes, frequencies

    def fused_tool_explore(self: Any, query: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.__dict__.pop("_symbol_vote_zoekt_capture", None)
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

        captured = self.__dict__.get("_symbol_vote_zoekt_capture")
        zoekt_files = list(captured[1]) if isinstance(captured, tuple) and captured and captured[0] == query else []
        tokens, exact_votes, frequencies = exact_file_votes(self, query)

        scores: dict[str, float] = {}
        for rank, file_path in enumerate(baseline_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + 1.0 / (8.0 + rank)
        for rank, file_path in enumerate(zoekt_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + 0.72 / (18.0 + rank)
        for file_path, vote in exact_votes.items():
            scores[file_path] = scores.get(file_path, 0.0) + vote

        query_lowers = {token.lower() for token in tokens}
        query_wants_tests = bool(re.search(r"\btest(?:s|ing)?\b|\bspec\b", query, re.IGNORECASE))
        for file_path in list(scores):
            scores[file_path] += 0.012 * len(query_lowers & _path_parts(file_path))
            if not query_wants_tests and _TEST_RE.search(file_path):
                scores[file_path] *= 0.92

        baseline_rank = {file_path: rank for rank, file_path in enumerate(baseline_files, start=1)}
        zoekt_rank = {file_path: rank for rank, file_path in enumerate(zoekt_files, start=1)}
        ordered = sorted(
            scores,
            key=lambda file_path: (
                -scores[file_path],
                baseline_rank.get(file_path, 10_000),
                zoekt_rank.get(file_path, 10_000),
                file_path,
            ),
        )[:max_files]

        fused_entries: list[dict[str, Any]] = []
        for file_path in ordered:
            existing = baseline_entries.get(file_path)
            if existing is not None:
                fused_entries.append(existing)
            else:
                fused_entries.append({"path": file_path, "language": "unknown", "symbols": [], "source_sections": []})

        _append_diagnostic({
            "repo": str(getattr(self, "repo_id", "")),
            "query": query,
            "tokens": tokens,
            "token_df": frequencies,
            "baseline": baseline_files[:10],
            "zoekt": zoekt_files[:20],
            "exact": sorted(exact_votes, key=lambda fp: (-exact_votes[fp], fp))[:20],
            "final": ordered,
        })

        result = dict(payload)
        result["files"] = fused_entries
        result["experiment"] = {"name": "rare_symbol_vote_zoekt_fusion", "tokens": tokens}
        return result

    engine_cls._zoekt_candidate_files = capturing_zoekt
    engine_cls._symbol_vote_exact_file_votes = exact_file_votes
    engine_cls._symbol_vote_original_tool_explore = original_tool_explore
    engine_cls.tool_explore = fused_tool_explore
    engine_cls._symbol_vote_experiment_installed = True


_install()
