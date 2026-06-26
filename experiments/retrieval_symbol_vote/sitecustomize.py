"""Opt-in retrieval experiment: aggressive multi-channel quality fusion.

Activate with ``ATELIER_EXPERIMENT_SYMBOL_VOTE=1`` and put this directory on
``PYTHONPATH``. This module is benchmark-only; production retrieval is untouched.

V4 optimizes ranking quality first:
* exact definition/symbol coverage,
* full-query and decomposed Zoekt searches,
* whole-file line co-occurrence for prose, literals, and regex-like queries.

Benchmark gold data is used only for diagnostics after ranking.
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
    "while", "with", "yield", "self", "cls",
}
_PROSE_STOP = _STOP | {
    "the", "this", "that", "these", "those", "then", "than", "into", "onto",
    "when", "where", "which", "what", "with", "without", "within", "should",
    "could", "would", "have", "has", "had", "does", "did", "done", "make",
    "using", "used", "use", "value", "values", "result", "results", "return",
    "file", "files", "code", "name", "string", "object", "method", "function",
}
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
_DIAGNOSTIC_FD: int | None = None


def _is_code_shaped(token: str) -> bool:
    return (
        "_" in token
        or token.isupper()
        or any(ch.isupper() for ch in token[1:])
        or token.startswith("__")
        or token.endswith("__")
    )


def _explicit_targets(query: str) -> dict[str, str]:
    targets: dict[str, str] = {}
    for kind, token in re.findall(
        r"\b(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
        query,
    ):
        targets[token.lower()] = kind
    return targets


def _query_tokens(query: str) -> tuple[list[str], dict[str, str]]:
    explicit = _explicit_targets(query)
    out: list[str] = []
    seen: set[str] = set()
    for token in _IDENTIFIER_RE.findall(query):
        low = token.lower()
        if low in seen or low in _STOP or len(token) < 3:
            continue
        if not _is_code_shaped(token) and low not in explicit and len(token) < 6:
            continue
        if low in {"__init__", "__call__", "__new__"} and low not in explicit:
            continue
        seen.add(low)
        out.append(token)
    return out[:18], explicit


def _line_terms(query: str, tokens: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens + _IDENTIFIER_RE.findall(query):
        low = token.lower()
        if low in seen or low in _PROSE_STOP or len(low) < 3:
            continue
        if low.isdigit():
            continue
        seen.add(low)
        terms.append(low)
    order = {term: index for index, term in enumerate(terms)}
    terms.sort(
        key=lambda term: (
            0 if _is_code_shaped(next((t for t in tokens if t.lower() == term), term)) else 1,
            -len(term),
            order[term],
        )
    )
    return terms[:12]


def _zoekt_subqueries(query: str, tokens: list[str], explicit: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    candidates.extend(explicit)
    candidates.extend(token for token in tokens if _is_code_shaped(token))
    for segment in query.split("|"):
        segment = segment.strip()
        segment = re.sub(r"\\[bBAZz]", "", segment)
        match = re.search(r"\b(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", segment)
        if match:
            candidates.append(match.group(1))
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", segment):
            candidates.append(segment)

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        low = candidate.lower()
        if low in seen or low in _STOP or len(candidate) < 3:
            continue
        seen.add(low)
        out.append(candidate)
    return out[:10]


def _path_parts(file_path: str) -> set[str]:
    return {part for part in re.split(r"[/._-]+", file_path.lower()) if part}


def _query_wants_tests(query: str) -> bool:
    return bool(
        re.search(
            r"\btest(?:_|s\b|ing\b)|\bspec(?:_|s\b)|pytest|unittest|"
            r"tearDown|setUp|TestCase|Tests\b",
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
        os.write(
            _DIAGNOSTIC_FD,
            (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
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
        overfetch = max(max_files, 120)
        files = original_zoekt(self, query, path=path, max_files=overfetch)
        self.__dict__["_symbol_vote_zoekt_capture"] = (query, files)
        return files[:max_files]

    def exact_file_evidence(
        self: Any,
        query: str,
        tokens: list[str],
        explicit: dict[str, str],
    ) -> tuple[dict[str, float], dict[str, int], dict[str, dict[str, Any]]]:
        if not tokens:
            return {}, {}, {}

        token_by_lower = {token.lower(): token for token in tokens}
        placeholders = ",".join("?" for _ in token_by_lower)
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
                    WHERE frequencies.df <= 96
                    ORDER BY matched.file_path, matched.token
                    """,
                    (self.repo_id, *token_by_lower),
                ).fetchall()
        except Exception:
            return {}, {}, {}

        definition_kinds = set(
            getattr(
                engine_mod,
                "_DEFINITION_KINDS",
                {"class", "function", "method"},
            )
        )
        per_file: dict[str, dict[str, float]] = defaultdict(dict)
        details: dict[str, dict[str, Any]] = {}
        frequencies: dict[str, int] = {}
        seen: set[tuple[str, str, str]] = set()

        for row in rows:
            file_path = str(row["file_path"] or "")
            token = str(row["token"] or "")
            kind = str(row["kind"] or "").lower()
            df = int(row["df"] or 0)
            if not file_path or not token or df <= 0:
                continue
            dedup_key = (file_path, token, kind)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            frequencies[token] = df

            original = token_by_lower.get(token, token)
            shaped = _is_code_shaped(original)
            is_definition = kind in definition_kinds
            target_kind = explicit.get(token)
            if not shaped and not is_definition and not target_kind:
                continue

            rarity = 1.0 / math.log2(df + 1.0)
            shape = 1.0
            if "_" in original:
                shape += 0.28
            if original.isupper() or any(ch.isupper() for ch in original[1:]):
                shape += 0.20
            shape += min(len(original), 24) / 120.0

            kind_boost = 1.28 if is_definition else 0.62
            if target_kind == "class":
                kind_boost *= 2.2 if kind == "class" else 0.35
            elif target_kind == "def":
                kind_boost *= 1.9 if kind in {"function", "method"} else 0.40

            base = 0.42 if shaped or target_kind else 0.14
            vote = base * shape * rarity * kind_boost
            per_file[file_path][token] = max(
                per_file[file_path].get(token, 0.0),
                vote,
            )

            item = details.setdefault(
                file_path,
                {
                    "tokens": set(),
                    "definitions": set(),
                    "explicit": set(),
                    "kinds": set(),
                },
            )
            item["tokens"].add(token)
            if is_definition:
                item["definitions"].add(token)
            if target_kind:
                item["explicit"].add(token)
            item["kinds"].add(kind)

        votes: dict[str, float] = {}
        for file_path, token_votes in per_file.items():
            values = sorted(token_votes.values(), reverse=True)[:5]
            token_count = len(token_votes)
            definition_count = len(details[file_path]["definitions"])
            explicit_count = len(details[file_path]["explicit"])
            score = sum(values)
            score += 0.14 * max(0, token_count - 1)
            score += 0.06 * max(0, definition_count - 1)
            score += 0.60 * explicit_count
            votes[file_path] = score
            details[file_path] = {
                "tokens": sorted(details[file_path]["tokens"]),
                "definitions": sorted(details[file_path]["definitions"]),
                "explicit": sorted(details[file_path]["explicit"]),
                "kinds": sorted(details[file_path]["kinds"]),
                "score": round(score, 6),
            }
        return votes, frequencies, details

    def decomposed_zoekt_evidence(
        self: Any,
        query: str,
        tokens: list[str],
        explicit: dict[str, str],
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        subqueries = _zoekt_subqueries(query, tokens, explicit)
        if not subqueries:
            return [], {}

        cache: dict[str, list[str]] = self.__dict__.setdefault(
            "_quality_zoekt_subquery_cache", {}
        )
        evidence: dict[str, dict[str, Any]] = {}
        for subquery in subqueries:
            files = cache.get(subquery)
            if files is None:
                try:
                    files = original_zoekt(
                        self,
                        subquery,
                        path=".",
                        max_files=32,
                    )
                except Exception:
                    files = []
                cache[subquery] = files
            for rank, file_path in enumerate(files, 1):
                item = evidence.setdefault(
                    file_path,
                    {"queries": set(), "rrf": 0.0, "best_rank": rank},
                )
                item["queries"].add(subquery.lower())
                item["rrf"] += 1.0 / (8.0 + rank)
                item["best_rank"] = min(int(item["best_rank"]), rank)

        ordered = sorted(
            evidence,
            key=lambda file_path: (
                -len(evidence[file_path]["queries"]),
                -float(evidence[file_path]["rrf"]),
                int(evidence[file_path]["best_rank"]),
                file_path,
            ),
        )
        serializable = {
            file_path: {
                "queries": sorted(evidence[file_path]["queries"]),
                "rrf": round(float(evidence[file_path]["rrf"]), 6),
                "best_rank": int(evidence[file_path]["best_rank"]),
            }
            for file_path in ordered
        }
        return ordered[:80], serializable

    def line_file_evidence(
        self: Any,
        query: str,
        tokens: list[str],
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        terms = _line_terms(query, tokens)
        if not terms:
            return [], {}

        if len(terms) == 1 and not _is_code_shaped(
            next((token for token in tokens if token.lower() == terms[0]), terms[0])
        ):
            return [], {}

        or_query = " OR ".join(f'"{term}"' for term in terms)
        and_query = " AND ".join(f'"{term}"' for term in terms[:8])
        rows: list[tuple[Any, bool]] = []
        try:
            with self._connect(readonly=True) as conn:
                if len(terms) >= 2:
                    and_rows = conn.execute(
                        """
                        SELECT file_path, line, text, bm25(file_line_fts) AS rank
                        FROM file_line_fts
                        WHERE file_line_fts MATCH ? AND repo_id = ?
                        ORDER BY rank ASC, file_path ASC, line ASC
                        LIMIT 500
                        """,
                        (and_query, self.repo_id),
                    ).fetchall()
                    rows.extend((row, True) for row in and_rows)
                or_rows = conn.execute(
                    """
                    SELECT file_path, line, text, bm25(file_line_fts) AS rank
                    FROM file_line_fts
                    WHERE file_line_fts MATCH ? AND repo_id = ?
                    ORDER BY rank ASC, file_path ASC, line ASC
                    LIMIT 2400
                    """,
                    (or_query, self.repo_id),
                ).fetchall()
                rows.extend((row, False) for row in or_rows)
        except Exception:
            return [], {}

        wants_tests = _query_wants_tests(query)
        wants_aux = _query_wants_aux(query)
        evidence: dict[str, dict[str, Any]] = {}
        term_set = set(terms)
        for row, from_and in rows:
            file_path = str(row["file_path"] or "")
            if not file_path:
                continue
            if engine_mod.is_generated_path(file_path):
                continue
            if engine_mod._MINIFIED_FILE_RE.search(file_path):
                continue
            if engine_mod._VENDOR_PATH_RE.search(file_path):
                continue
            text = str(row["text"] or "").lower()
            covered = {term for term in term_set if term in text}
            if not covered:
                continue
            item = evidence.setdefault(
                file_path,
                {
                    "covered": set(),
                    "hits": 0,
                    "and_hit": False,
                    "best_rank": float(row["rank"] or 0.0),
                },
            )
            item["covered"].update(covered)
            item["hits"] += 1
            item["and_hit"] = bool(item["and_hit"] or from_and)
            item["best_rank"] = min(
                float(item["best_rank"]),
                float(row["rank"] or 0.0),
            )

        scored: list[tuple[float, str]] = []
        for file_path, item in evidence.items():
            coverage_count = len(item["covered"])
            coverage = coverage_count / max(1, len(term_set))
            repeated = min(math.log1p(int(item["hits"])), 4.5)
            path_overlap = len(term_set & _path_parts(file_path))
            score = (
                2.20 * coverage
                + 0.22 * repeated
                + 0.34 * path_overlap
                + (0.85 if item["and_hit"] else 0.0)
            )
            if not wants_tests and _TEST_RE.search(file_path):
                score *= 0.70
            if not wants_aux and _AUX_RE.search(file_path):
                score *= 0.55
            scored.append((-score, file_path))
        scored.sort()

        files = [file_path for _score, file_path in scored[:100]]
        serializable = {
            file_path: {
                "covered": sorted(evidence[file_path]["covered"]),
                "coverage": round(
                    len(evidence[file_path]["covered"]) / max(1, len(term_set)),
                    6,
                ),
                "hits": int(evidence[file_path]["hits"]),
                "and_hit": bool(evidence[file_path]["and_hit"]),
                "best_rank": round(float(evidence[file_path]["best_rank"]), 6),
                "score": round(-score, 6),
            }
            for score, file_path in scored[:100]
        }
        return files, serializable

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
        full_zoekt = (
            list(captured[1])
            if isinstance(captured, tuple) and captured and captured[0] == query
            else []
        )
        tokens, explicit = _query_tokens(query)
        exact_votes, frequencies, exact_details = exact_file_evidence(
            self,
            query,
            tokens,
            explicit,
        )
        subquery_files, subquery_details = decomposed_zoekt_evidence(
            self,
            query,
            tokens,
            explicit,
        )
        line_files, line_details = line_file_evidence(self, query, tokens)

        scores: dict[str, float] = {}
        reasons: dict[str, dict[str, float]] = defaultdict(dict)

        def add(file_path: str, channel: str, value: float) -> None:
            scores[file_path] = scores.get(file_path, 0.0) + value
            reasons[file_path][channel] = reasons[file_path].get(channel, 0.0) + value

        for rank, file_path in enumerate(baseline_files, 1):
            add(file_path, "baseline", 1.05 / (8.0 + rank))
        for rank, file_path in enumerate(full_zoekt, 1):
            add(file_path, "zoekt", 0.85 / (16.0 + rank))
        for rank, file_path in enumerate(subquery_files, 1):
            detail = subquery_details[file_path]
            coverage = len(detail["queries"])
            add(
                file_path,
                "subquery",
                0.38 * float(detail["rrf"]) + 0.11 * min(coverage, 5),
            )
        for rank, file_path in enumerate(line_files, 1):
            detail = line_details[file_path]
            add(
                file_path,
                "line",
                0.24 * float(detail["score"]) + 0.35 / (10.0 + rank),
            )
        for file_path, value in exact_votes.items():
            add(file_path, "exact", value)

        baseline_set = set(baseline_files)
        zoekt_set = set(full_zoekt)
        subquery_set = set(subquery_files)
        line_set = set(line_files)
        exact_set = set(exact_votes)
        wants_tests = _query_wants_tests(query)
        wants_aux = _query_wants_aux(query)
        query_lowers = {token.lower() for token in tokens}

        for file_path in list(scores):
            overlap = len(query_lowers & _path_parts(file_path))
            if overlap:
                add(file_path, "path", 0.045 * overlap)

            channel_count = sum(
                file_path in channel
                for channel in (
                    baseline_set,
                    zoekt_set,
                    subquery_set,
                    line_set,
                    exact_set,
                )
            )
            if channel_count >= 2:
                add(file_path, "consensus", 0.10 * (channel_count - 1))

            detail = exact_details.get(file_path, {})
            explicit_count = len(detail.get("explicit", ()))
            token_count = len(detail.get("tokens", ()))
            definition_count = len(detail.get("definitions", ()))
            if explicit_count:
                add(file_path, "explicit_pin", 1.20 * explicit_count)
            if token_count >= 2:
                add(file_path, "exact_coverage", 0.22 * (token_count - 1))
            if definition_count >= 2:
                add(file_path, "definition_coverage", 0.08 * (definition_count - 1))

            if file_path.endswith(".pyi") and not re.search(r"\bpyi|stub\b", query, re.I):
                scores[file_path] *= 0.72
            unsupported = (
                file_path not in baseline_set
                and file_path not in zoekt_set
                and file_path not in subquery_set
            )
            if unsupported and not wants_tests and _TEST_RE.search(file_path):
                scores[file_path] *= 0.48
            if unsupported and not wants_aux and _AUX_RE.search(file_path):
                scores[file_path] *= 0.38

        baseline_rank = {
            file_path: rank for rank, file_path in enumerate(baseline_files, 1)
        }
        zoekt_rank = {
            file_path: rank for rank, file_path in enumerate(full_zoekt, 1)
        }
        subquery_rank = {
            file_path: rank for rank, file_path in enumerate(subquery_files, 1)
        }
        line_rank = {
            file_path: rank for rank, file_path in enumerate(line_files, 1)
        }
        ordered = sorted(
            scores,
            key=lambda file_path: (
                -scores[file_path],
                baseline_rank.get(file_path, 10_000),
                zoekt_rank.get(file_path, 10_000),
                subquery_rank.get(file_path, 10_000),
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
                "explicit": explicit,
                "token_df": frequencies,
                "baseline": baseline_files[:10],
                "zoekt": full_zoekt[:30],
                "subquery": subquery_files[:30],
                "exact": exact_files[:30],
                "line": line_files[:30],
                "final": ordered,
                "gold": gold,
                "ranks": {
                    "baseline": _rank(baseline_files, gold),
                    "zoekt": _rank(full_zoekt, gold),
                    "subquery": _rank(subquery_files, gold),
                    "exact": _rank(exact_files, gold),
                    "line": _rank(line_files, gold),
                    "final": _rank(ordered, gold),
                },
                "exact_details": {
                    file_path: exact_details[file_path]
                    for file_path in exact_files[:15]
                },
                "subquery_details": {
                    file_path: subquery_details[file_path]
                    for file_path in subquery_files[:15]
                },
                "line_details": {
                    file_path: line_details[file_path]
                    for file_path in line_files[:15]
                },
                "scores": {
                    file_path: round(scores[file_path], 6)
                    for file_path in ordered
                },
                "reasons": {
                    file_path: {
                        channel: round(value, 6)
                        for channel, value in reasons[file_path].items()
                    }
                    for file_path in ordered
                },
            }
        )

        result = dict(payload)
        result["files"] = fused_entries
        result["experiment"] = {
            "name": "aggressive_quality_fusion_v4",
            "tokens": tokens,
            "explicit": explicit,
        }
        return result

    engine_cls._zoekt_candidate_files = capturing_zoekt
    engine_cls._symbol_vote_exact_file_evidence = exact_file_evidence
    engine_cls._symbol_vote_original_tool_explore = original_tool_explore
    engine_cls.tool_explore = fused_tool_explore
    engine_cls._symbol_vote_experiment_installed = True


_install()
