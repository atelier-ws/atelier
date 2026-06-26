"""Opt-in retrieval experiment: fast consensus symbol/Zoekt fusion.

Activate with ``ATELIER_EXPERIMENT_SYMBOL_VOTE=1`` and put this directory on
``PYTHONPATH``. This module is benchmark-only; production retrieval is untouched.

V3 removes the expensive line-FTS and Zoekt-overfetch paths. It keeps only the
normal Zoekt candidate list plus cached exact-symbol evidence. Exact matches are
routed by identifier confidence so generic SQL words/acronyms cannot overwhelm
the shipped ranker.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TEST_RE = re.compile(
    r"(^|/)(tests?|testing|specs?)(/|$)|(^|/)test_[^/]+$",
    re.IGNORECASE,
)
_AUX_RE = re.compile(
    r"(^|/)(docs?(?:-internal)?|documentation|examples?|galleries|benchmarks?|"
    r"frontend|vendor|third_party)(/|$)|\.(?:md|rst|ipynb|json|lock)$",
    re.IGNORECASE,
)
_STOP = {
    "and", "as", "assert", "async", "await", "break", "case", "class",
    "continue", "def", "del", "do", "else", "except", "false", "finally",
    "for", "from", "if", "import", "in", "is", "lambda", "none", "not",
    "or", "pass", "raise", "return", "self", "super", "true", "try",
    "while", "with", "yield",
}
# Fallback is diagnostics-only. Ranking never consults benchmark gold data.
_KNOWN_PREFIX_BY_REPO_ID = {
    "221445b350fc9bcf": "atelier__atelier",
    "0451fa59ffee9c3e": "matplotlib__matplotlib",
    "f22df2bf011f66ac": "django__django",
    "efe30f92e5fa9094": "pydata__xarray",
    "6f21e27917ff8018": "pylint-dev__pylint",
    "a2c6691d8841173a": "astropy__astropy",
    "3630fe89fc226a0e": "pytest-dev__pytest",
    "3e63d104d58fef81": "mwaskom__seaborn",
    "cea9dc05a2538421": "scikit-learn__scikit-learn",
    "b784d1fff1f95286": "pallets__flask",
}
_GOLD_CACHE: dict[tuple[str, str], list[str]] | None = None


def _identifier_strength(token: str, explicit: bool) -> float:
    """Return confidence that *token* is a real code identifier."""
    if "_" in token:
        return 1.0
    has_lower = any(ch.islower() for ch in token)
    has_upper = any(ch.isupper() for ch in token)
    if has_lower and has_upper:
        return 0.92
    # Bare SQL words/acronyms such as CAST, NUMERIC, CLI and MCP were a major
    # false-positive source in the previous diagnostic run.
    if token.isupper():
        return 0.38 if len(token) >= 5 else 0.28
    if explicit:
        return 0.76
    return 0.0


def _explicit_identifier_tokens(query: str) -> set[str]:
    explicit: set[str] = set()
    for segment in query.split("|"):
        segment = segment.strip()
        match = re.search(r"\b(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", segment)
        if match:
            explicit.add(match.group(1).lower())
        cleaned = re.sub(r"\\[bBAZz]$", "", segment)
        cleaned = re.sub(r"\(\??.*$", "", cleaned).strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cleaned):
            explicit.add(cleaned.lower())
    return explicit


def _query_tokens(query: str) -> tuple[list[str], set[str], dict[str, float]]:
    explicit = _explicit_identifier_tokens(query)
    out: list[str] = []
    strengths: dict[str, float] = {}
    seen: set[str] = set()
    for token in _IDENTIFIER_RE.findall(query):
        low = token.lower()
        if low in seen or low in _STOP or len(token) < 3:
            continue
        if low in {"__init__", "__call__", "__new__", "tests", "testing"}:
            continue
        strength = _identifier_strength(token, low in explicit)
        if strength <= 0:
            continue
        seen.add(low)
        out.append(token)
        strengths[low] = max(strengths.get(low, 0.0), strength)
    return out[:14], explicit, strengths


def _path_parts(file_path: str) -> set[str]:
    return {part for part in re.split(r"[/._-]+", file_path.lower()) if part}


def _query_wants_tests(query: str) -> bool:
    return bool(
        re.search(
            r"\btest(?:_|s\b|ing\b)|\bspec(?:_|s\b)|pytest|unittest|tearDown|setUp",
            query,
            re.IGNORECASE,
        )
    )


def _query_wants_aux(query: str) -> bool:
    return bool(
        re.search(
            r"\bdocs?|documentation|example|gallery|benchmark|frontend|"
            r"javascript|typescript|readme\b",
            query,
            re.IGNORECASE,
        )
    )


def _rank(paths: list[str], gold: list[str]) -> int | None:
    normalized = [g.replace("\\", "/") for g in gold]
    for index, path in enumerate(paths, 1):
        normalized_path = path.replace("\\", "/")
        if any(normalized_path.endswith(g) for g in normalized):
            return index
    return None


def _load_gold_diagnostics() -> dict[tuple[str, str], list[str]]:
    global _GOLD_CACHE
    if _GOLD_CACHE is not None:
        return _GOLD_CACHE

    gold_map: dict[tuple[str, str], set[str]] = defaultdict(set)
    try:
        data = json.loads(
            Path("benchmarks/codebench/data/bench_pairs_multi.json").read_text()
        )
        true_map = data.get("true_map", {})
        for query, tid, prefix in data.get("pairs", []):
            for file_path in true_map.get(tid, []):
                gold_map[(str(prefix), str(query))].add(
                    str(file_path).replace("\\", "/")
                )
    except Exception:
        pass
    _GOLD_CACHE = {key: sorted(value) for key, value in gold_map.items()}
    return _GOLD_CACHE


_DIAGNOSTIC_FD: int | None = None


def _append_diagnostic(payload: dict[str, Any]) -> None:
    global _DIAGNOSTIC_FD
    target = os.environ.get("ATELIER_EXPERIMENT_DIAGNOSTICS", "").strip()
    if not target:
        return
    try:
        if _DIAGNOSTIC_FD is None:
            _DIAGNOSTIC_FD = os.open(
                target, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644
            )
        line = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        os.write(_DIAGNOSTIC_FD, line)
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

    def capturing_zoekt(
        self: Any,
        query: str,
        *,
        path: str = ".",
        max_files: int = 40,
    ) -> list[str]:
        # Do not overfetch. The uploaded diagnostics showed that almost every
        # useful newly selected file was already in Zoekt's first ten results.
        files = original_zoekt(self, query, path=path, max_files=max_files)
        self.__dict__["_symbol_vote_zoekt_capture"] = (query, files)
        return files

    def _load_missing_token_rows(
        self: Any,
        missing: list[str],
        cache: dict[str, tuple[int, list[tuple[str, str]]]],
    ) -> None:
        if not missing:
            return
        placeholders = ",".join("?" for _ in missing)
        for token in missing:
            cache[token] = (0, [])
        try:
            with self._connect(readonly=True) as conn:
                rows = conn.execute(
                    f"""
                    WITH matched AS (
                        SELECT file_path, lower(symbol_name) AS token, kind
                        FROM symbols
                        WHERE repo_id = ?
                          AND lower(symbol_name) IN ({placeholders})
                    ),
                    frequencies AS (
                        SELECT token, COUNT(DISTINCT file_path) AS df
                        FROM matched
                        GROUP BY token
                    )
                    SELECT matched.file_path, matched.token, matched.kind,
                           frequencies.df
                    FROM matched
                    JOIN frequencies USING (token)
                    WHERE frequencies.df <= 64
                    ORDER BY matched.token, matched.file_path
                    """,
                    (self.repo_id, *missing),
                ).fetchall()
        except Exception:
            return

        grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
        frequencies: dict[str, int] = {}
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            file_path = str(row["file_path"] or "")
            token = str(row["token"] or "")
            kind = str(row["kind"] or "").lower()
            if not file_path or not token:
                continue
            key = (token, file_path, kind)
            if key in seen:
                continue
            seen.add(key)
            grouped[token].append((file_path, kind))
            frequencies[token] = int(row["df"] or 0)
        for token in missing:
            cache[token] = (frequencies.get(token, 0), grouped.get(token, []))

    def exact_file_evidence(
        self: Any,
        query: str,
    ) -> tuple[
        list[str],
        dict[str, float],
        dict[str, int],
        dict[str, dict[str, Any]],
    ]:
        tokens, explicit, strengths = _query_tokens(query)
        if not tokens:
            return [], {}, {}, {}

        token_by_lower = {token.lower(): token for token in tokens}
        cache: dict[str, tuple[int, list[tuple[str, str]]]] = self.__dict__.setdefault(
            "_symbol_vote_token_cache", {}
        )
        missing = [token for token in token_by_lower if token not in cache]
        _load_missing_token_rows(self, missing, cache)

        definition_kinds = set(
            getattr(
                engine_mod,
                "_DEFINITION_KINDS",
                {"class", "function", "method"},
            )
        )
        per_file_token: dict[str, dict[str, float]] = {}
        details: dict[str, dict[str, Any]] = {}
        frequencies: dict[str, int] = {}

        for token, original in token_by_lower.items():
            df, token_rows = cache.get(token, (0, []))
            frequencies[token] = df
            if not token_rows or df <= 0:
                continue
            strength = strengths.get(token, 0.0)
            rarity = 1.0 / math.log2(df + 1.0)
            for file_path, kind in token_rows:
                is_definition = kind in definition_kinds
                if not is_definition and strength < 0.90:
                    continue
                kind_boost = 1.22 if is_definition else 0.62
                vote = 0.30 * strength * rarity * kind_boost
                current = per_file_token.setdefault(file_path, {}).get(token, 0.0)
                if vote > current:
                    per_file_token[file_path][token] = vote
                item = details.setdefault(
                    file_path,
                    {
                        "tokens": set(),
                        "strong_tokens": set(),
                        "definitions": set(),
                    },
                )
                item["tokens"].add(token)
                if strength >= 0.75:
                    item["strong_tokens"].add(token)
                if is_definition:
                    item["definitions"].add(token)

        votes: dict[str, float] = {}
        for file_path, token_votes in per_file_token.items():
            strongest = sorted(token_votes.values(), reverse=True)[:3]
            strong_count = len(details[file_path]["strong_tokens"])
            definition_count = len(details[file_path]["definitions"])
            score = sum(strongest)
            score += 0.075 * max(0, strong_count - 1)
            score += 0.025 * max(0, definition_count - 1)
            votes[file_path] = score
            details[file_path] = {
                "tokens": sorted(details[file_path]["tokens"]),
                "strong_tokens": sorted(details[file_path]["strong_tokens"]),
                "definitions": sorted(details[file_path]["definitions"]),
                "score": round(score, 6),
            }
        return tokens, votes, frequencies, details

    def fused_tool_explore(
        self: Any,
        query: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
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
        zoekt_files = (
            list(captured[1])
            if isinstance(captured, tuple) and captured and captured[0] == query
            else []
        )
        tokens, exact_votes, frequencies, exact_details = exact_file_evidence(
            self, query
        )

        baseline_set = set(baseline_files)
        zoekt_set = set(zoekt_files)
        scores: dict[str, float] = {}
        for rank, file_path in enumerate(baseline_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + 1.0 / (8.0 + rank)
        for rank, file_path in enumerate(zoekt_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + 0.78 / (18.0 + rank)

        for file_path, raw_vote in exact_votes.items():
            detail = exact_details[file_path]
            strong_count = len(detail["strong_tokens"])
            definition_count = len(detail["definitions"])
            in_baseline = file_path in baseline_set
            in_zoekt = file_path in zoekt_set

            multiplier = 1.0
            if in_baseline and in_zoekt:
                multiplier = 1.18
            elif in_baseline or in_zoekt:
                multiplier = 1.06
            elif strong_count >= 2:
                multiplier = 0.90
            elif strong_count == 1 and definition_count:
                multiplier = 0.62
            else:
                multiplier = 0.22
            scores[file_path] = scores.get(file_path, 0.0) + raw_vote * multiplier

        query_lowers = {token.lower() for token in tokens}
        wants_tests = _query_wants_tests(query)
        wants_aux = _query_wants_aux(query)
        for file_path in list(scores):
            path_overlap = len(query_lowers & _path_parts(file_path))
            scores[file_path] += 0.026 * path_overlap
            if file_path in exact_votes and file_path in zoekt_set:
                scores[file_path] += 0.050
            unsupported = file_path not in baseline_set and file_path not in zoekt_set
            if unsupported and not wants_aux and _AUX_RE.search(file_path):
                scores[file_path] *= 0.25
            if unsupported and not wants_tests and _TEST_RE.search(file_path):
                scores[file_path] *= 0.50

        baseline_rank = {
            file_path: rank
            for rank, file_path in enumerate(baseline_files, start=1)
        }
        zoekt_rank = {
            file_path: rank
            for rank, file_path in enumerate(zoekt_files, start=1)
        }
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
                fused_entries.append(
                    {
                        "path": file_path,
                        "language": "unknown",
                        "symbols": [],
                        "source_sections": [],
                    }
                )

        repo_id = str(getattr(self, "repo_id", ""))
        prefix = _KNOWN_PREFIX_BY_REPO_ID.get(repo_id, "")
        gold = _load_gold_diagnostics().get((prefix, query), [])
        exact_files = sorted(
            exact_votes,
            key=lambda file_path: (-exact_votes[file_path], file_path),
        )
        _append_diagnostic(
            {
                "repo": repo_id,
                "prefix": prefix,
                "query": query,
                "tokens": tokens,
                "token_df": frequencies,
                "baseline": baseline_files[:10],
                "zoekt": zoekt_files[:20],
                "exact": exact_files[:20],
                "final": ordered,
                "gold": gold,
                "ranks": {
                    "baseline": _rank(baseline_files, gold),
                    "zoekt": _rank(zoekt_files, gold),
                    "exact": _rank(exact_files, gold),
                    "final": _rank(ordered, gold),
                },
                "exact_details": {
                    file_path: exact_details[file_path]
                    for file_path in exact_files[:12]
                },
                "scores": {
                    file_path: round(scores[file_path], 6)
                    for file_path in ordered
                },
                "token_cache_size": len(
                    self.__dict__.get("_symbol_vote_token_cache", {})
                ),
            }
        )

        result = dict(payload)
        result["files"] = fused_entries
        result["experiment"] = {
            "name": "fast_consensus_symbol_zoekt_v3",
            "tokens": tokens,
        }
        return result

    engine_cls._zoekt_candidate_files = capturing_zoekt
    engine_cls._symbol_vote_exact_file_evidence = exact_file_evidence
    engine_cls._symbol_vote_original_tool_explore = original_tool_explore
    engine_cls.tool_explore = fused_tool_explore
    engine_cls._symbol_vote_experiment_installed = True


_install()
