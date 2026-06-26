"""Opt-in retrieval experiment: generic score-aware hybrid code retrieval.

Activate with ``ATELIER_EXPERIMENT_SYMBOL_VOTE=1`` and put this directory on
``PYTHONPATH``. This module is benchmark-only; production retrieval is untouched.

The design is repository- and benchmark-agnostic:
* preserve complete code identifiers during query analysis;
* retrieve from baseline, Zoekt, exact symbols, decomposed anchors, and line FTS;
* retain each channel's internal confidence instead of flattening everything to rank;
* combine robust rank evidence with normalized coverage, proximity, and kind signals.

No benchmark pairs, issue IDs, repository names, or gold files are imported.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFINITION_RE = re.compile(
    r"\b(?P<kind>def|class)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_QUOTED_RE = re.compile(r"""(?P<quote>["'])(?P<value>.*?)(?P=quote)""")
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
_PROSE_STOP = _STOP | {
    "the", "this", "that", "these", "those", "then", "than", "into", "onto",
    "when", "where", "which", "what", "with", "without", "within", "should",
    "could", "would", "have", "has", "had", "does", "did", "done", "make",
    "using", "used", "use", "value", "values", "result", "results", "file",
    "files", "code", "name", "string", "object", "method", "function",
}
_DIAGNOSTIC_FD: int | None = None


@dataclass(frozen=True)
class QueryPlan:
    intent: str
    definitions: tuple[tuple[str, str], ...]
    identifiers: tuple[str, ...]
    anchors: tuple[str, ...]
    terms: tuple[str, ...]
    literals: tuple[str, ...]
    wants_tests: bool
    wants_auxiliary: bool


def _is_code_shaped(token: str) -> bool:
    return (
        "_" in token
        or token.isupper()
        or any(ch.isupper() for ch in token[1:])
        or token.startswith("__")
        or token.endswith("__")
    )


def _dedupe(values: list[str], *, limit: int) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        low = value.lower()
        if not value or low in seen:
            continue
        seen.add(low)
        out.append(value)
        if len(out) >= limit:
            break
    return tuple(out)


def _bare_alternative(segment: str) -> str | None:
    segment = segment.strip()
    segment = re.sub(r"\\[bBAZz]$", "", segment)
    segment = re.sub(r"^\^|\$$", "", segment)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", segment):
        return segment
    return None


def _parse_query(engine_mod: Any, query: str) -> QueryPlan:
    definitions = tuple(
        (match.group("kind"), match.group("name"))
        for match in _DEFINITION_RE.finditer(query)
    )
    definition_names = [name for _kind, name in definitions]

    identifiers: list[str] = []
    alternatives: list[str] = []
    for segment in query.split("|"):
        match = _DEFINITION_RE.search(segment)
        if match:
            alternatives.append(match.group("name"))
        else:
            bare = _bare_alternative(segment)
            if bare is not None:
                alternatives.append(bare)

    for token in _IDENTIFIER_RE.findall(query):
        low = token.lower()
        if low in _STOP or len(token) < 3:
            continue
        if _is_code_shaped(token):
            identifiers.append(token)

    normalized = query.strip()
    if engine_mod._is_precise_symbol_query(normalized):
        alternatives.append(normalized.rsplit(".", 1)[-1])

    literals = [
        match.group("value").strip()
        for match in _QUOTED_RE.finditer(query)
        if match.group("value").strip()
    ]
    prose_terms = [
        str(term)
        for term in engine_mod._query_terms(query)
        if len(str(term)) >= 3 and str(term).lower() not in _PROSE_STOP
    ]

    identifier_tuple = _dedupe(
        [*definition_names, *alternatives, *identifiers],
        limit=18,
    )
    anchor_tuple = _dedupe(
        [*definition_names, *alternatives, *identifiers],
        limit=10,
    )
    literal_tuple = _dedupe(literals, limit=8)

    if definitions:
        intent = "definition"
    elif engine_mod._is_precise_symbol_query(normalized):
        intent = "symbol"
    elif identifier_tuple or "|" in query:
        intent = "code"
    else:
        intent = "prose"

    # Preserve complete identifiers. Splitting file_path into file/path destroys
    # the strongest lexical signal and creates broad false positives.
    if intent in {"definition", "symbol"}:
        term_values = [*identifier_tuple, *literal_tuple]
    elif intent == "code":
        term_values = [*identifier_tuple, *literal_tuple, *prose_terms]
    else:
        term_values = [*literal_tuple, *prose_terms]

    wants_tests = bool(
        re.search(
            r"\btest(?:_|s\b|ing\b)|\bspec(?:_|s\b)|pytest|unittest|"
            r"tearDown|setUp|TestCase|Tests\b",
            query,
            re.IGNORECASE,
        )
    )
    wants_auxiliary = bool(
        re.search(
            r"\bdocs?|documentation|example|gallery|benchmark|frontend|"
            r"javascript|typescript|readme\b",
            query,
            re.IGNORECASE,
        )
    )
    return QueryPlan(
        intent=intent,
        definitions=definitions,
        identifiers=identifier_tuple,
        anchors=anchor_tuple,
        terms=_dedupe(term_values, limit=16),
        literals=literal_tuple,
        wants_tests=wants_tests,
        wants_auxiliary=wants_auxiliary,
    )


def _path_parts(file_path: str) -> set[str]:
    return {
        part
        for part in re.split(r"[/._-]+", file_path.lower())
        if part
    }


def _fts_phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _append_diagnostic(payload: dict[str, Any]) -> None:
    global _DIAGNOSTIC_FD
    target = os.environ.get("ATELIER_EXPERIMENT_DIAGNOSTICS", "").strip()
    if not target:
        return
    try:
        if _DIAGNOSTIC_FD is None:
            _DIAGNOSTIC_FD = os.open(
                target,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY,
                0o644,
            )
        os.write(
            _DIAGNOSTIC_FD,
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode(),
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
        files = original_zoekt(
            self,
            query,
            path=path,
            max_files=max(max_files, 96),
        )
        self.__dict__["_hybrid_zoekt_capture"] = (query, files)
        return files[:max_files]

    def exact_symbol_candidates(
        self: Any,
        plan: QueryPlan,
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        if not plan.identifiers:
            return [], {}

        tokens = {token.lower(): token for token in plan.identifiers}
        placeholders = ",".join("?" for _ in tokens)
        try:
            with self._connect(readonly=True) as conn:
                rows = conn.execute(
                    f"""
                    WITH matched AS (
                        SELECT file_path,
                               lower(symbol_name) AS token,
                               lower(kind) AS kind
                        FROM symbols
                        WHERE repo_id = ?
                          AND lower(symbol_name) IN ({placeholders})
                    ),
                    frequencies AS (
                        SELECT token, COUNT(DISTINCT file_path) AS df
                        FROM matched
                        GROUP BY token
                    )
                    SELECT matched.file_path,
                           matched.token,
                           matched.kind,
                           frequencies.df
                    FROM matched
                    JOIN frequencies USING (token)
                    ORDER BY matched.file_path, matched.token, matched.kind
                    """,
                    (self.repo_id, *tokens),
                ).fetchall()
        except Exception:
            return [], {}

        definition_kinds = set(
            getattr(
                engine_mod,
                "_DEFINITION_KINDS",
                {"class", "function", "method"},
            )
        )
        expected = {
            name.lower(): kind
            for kind, name in plan.definitions
        }
        per_file: dict[str, dict[str, Any]] = {}
        seen: set[tuple[str, str, str]] = set()

        for row in rows:
            file_path = str(row["file_path"] or "")
            token = str(row["token"] or "")
            kind = str(row["kind"] or "").lower()
            df = max(1, int(row["df"] or 1))
            if not file_path or not token:
                continue
            key = (file_path, token, kind)
            if key in seen:
                continue
            seen.add(key)

            expected_kind = expected.get(token)
            kind_match = (
                expected_kind == "class" and kind == "class"
            ) or (
                expected_kind == "def"
                and kind in {"function", "method"}
            )
            item = per_file.setdefault(
                file_path,
                {
                    "tokens": set(),
                    "definition_tokens": set(),
                    "kind_matches": set(),
                    "idf": 0.0,
                    "best_df": df,
                },
            )
            item["tokens"].add(token)
            if kind in definition_kinds:
                item["definition_tokens"].add(token)
            if kind_match:
                item["kind_matches"].add(token)
            item["idf"] += math.log1p(1.0 + 1.0 / df)
            item["best_df"] = min(int(item["best_df"]), df)

        identifier_count = max(1, len(plan.identifiers))
        definition_count = max(1, len(plan.definitions))
        for item in per_file.values():
            token_coverage = len(item["tokens"]) / identifier_count
            kind_coverage = len(item["kind_matches"]) / definition_count
            definition_coverage = (
                len(item["definition_tokens"]) / identifier_count
            )
            rarity = min(1.0, float(item["idf"]) / identifier_count)
            item["confidence"] = min(
                1.0,
                0.42 * token_coverage
                + 0.30 * kind_coverage
                + 0.16 * definition_coverage
                + 0.12 * rarity,
            )

        ordered = sorted(
            per_file,
            key=lambda file_path: (
                -float(per_file[file_path]["confidence"]),
                -len(per_file[file_path]["kind_matches"]),
                -len(per_file[file_path]["tokens"]),
                int(per_file[file_path]["best_df"]),
                file_path,
            ),
        )
        details = {
            file_path: {
                "tokens": sorted(per_file[file_path]["tokens"]),
                "definition_tokens": sorted(
                    per_file[file_path]["definition_tokens"]
                ),
                "kind_matches": sorted(
                    per_file[file_path]["kind_matches"]
                ),
                "idf": round(float(per_file[file_path]["idf"]), 6),
                "best_df": int(per_file[file_path]["best_df"]),
                "confidence": round(
                    float(per_file[file_path]["confidence"]),
                    6,
                ),
            }
            for file_path in ordered
        }
        return ordered[:96], details

    def anchor_zoekt_candidates(
        self: Any,
        plan: QueryPlan,
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        if not plan.anchors:
            return [], {}

        cache: dict[str, list[str]] = self.__dict__.setdefault(
            "_hybrid_anchor_cache",
            {},
        )
        per_file: dict[str, dict[str, Any]] = {}
        for anchor in plan.anchors:
            files = cache.get(anchor)
            if files is None:
                try:
                    files = original_zoekt(
                        self,
                        anchor,
                        path=".",
                        max_files=40,
                    )
                except Exception:
                    files = []
                cache[anchor] = files
            for rank, file_path in enumerate(files, 1):
                item = per_file.setdefault(
                    file_path,
                    {
                        "anchors": set(),
                        "rrf": 0.0,
                        "best_rank": rank,
                    },
                )
                item["anchors"].add(anchor.lower())
                item["rrf"] += 1.0 / (8.0 + rank)
                item["best_rank"] = min(
                    int(item["best_rank"]),
                    rank,
                )

        anchor_count = max(1, len(plan.anchors))
        max_rrf = sum(1.0 / 9.0 for _ in plan.anchors)
        for item in per_file.values():
            coverage = len(item["anchors"]) / anchor_count
            normalized_rrf = min(1.0, float(item["rrf"]) / max_rrf)
            item["confidence"] = min(
                1.0,
                0.72 * coverage + 0.28 * normalized_rrf,
            )

        ordered = sorted(
            per_file,
            key=lambda file_path: (
                -float(per_file[file_path]["confidence"]),
                -len(per_file[file_path]["anchors"]),
                int(per_file[file_path]["best_rank"]),
                file_path,
            ),
        )
        details = {
            file_path: {
                "anchors": sorted(per_file[file_path]["anchors"]),
                "rrf": round(float(per_file[file_path]["rrf"]), 6),
                "best_rank": int(per_file[file_path]["best_rank"]),
                "confidence": round(
                    float(per_file[file_path]["confidence"]),
                    6,
                ),
            }
            for file_path in ordered
        }
        return ordered[:96], details

    def line_fts_candidates(
        self: Any,
        plan: QueryPlan,
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        if not plan.terms:
            return [], {}

        terms = [term.lower() for term in plan.terms]
        or_query = " OR ".join(_fts_phrase(term) for term in terms)
        and_query = " AND ".join(
            _fts_phrase(term)
            for term in terms[: min(8, len(terms))]
        )
        rows: list[tuple[Any, bool]] = []
        try:
            with self._connect(readonly=True) as conn:
                if len(terms) >= 2:
                    and_rows = conn.execute(
                        """
                        SELECT file_path,
                               line,
                               text,
                               bm25(file_line_fts) AS rank
                        FROM file_line_fts
                        WHERE file_line_fts MATCH ?
                          AND repo_id = ?
                        ORDER BY rank ASC, file_path ASC, line ASC
                        LIMIT 700
                        """,
                        (and_query, self.repo_id),
                    ).fetchall()
                    rows.extend((row, True) for row in and_rows)

                or_rows = conn.execute(
                    """
                    SELECT file_path,
                           line,
                           text,
                           bm25(file_line_fts) AS rank
                    FROM file_line_fts
                    WHERE file_line_fts MATCH ?
                      AND repo_id = ?
                    ORDER BY rank ASC, file_path ASC, line ASC
                    LIMIT 2600
                    """,
                    (or_query, self.repo_id),
                ).fetchall()
                rows.extend((row, False) for row in or_rows)
        except Exception:
            return [], {}

        term_set = set(terms)
        literal_set = {literal.lower() for literal in plan.literals}
        per_file: dict[str, dict[str, Any]] = {}
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
            line_coverage = len(covered) / max(1, len(term_set))
            literal_hits = sum(1 for literal in literal_set if literal in text)
            item = per_file.setdefault(
                file_path,
                {
                    "covered": set(),
                    "hit_count": 0,
                    "and_hit": False,
                    "best_rank": float(row["rank"] or 0.0),
                    "max_line_coverage": 0.0,
                    "multi_term_lines": 0,
                    "literal_hits": 0,
                },
            )
            item["covered"].update(covered)
            item["hit_count"] += 1
            item["and_hit"] = bool(item["and_hit"] or from_and)
            item["best_rank"] = min(
                float(item["best_rank"]),
                float(row["rank"] or 0.0),
            )
            item["max_line_coverage"] = max(
                float(item["max_line_coverage"]),
                line_coverage,
            )
            if len(covered) >= 2:
                item["multi_term_lines"] += 1
            item["literal_hits"] += literal_hits

        for file_path, item in per_file.items():
            file_coverage = len(item["covered"]) / max(1, len(term_set))
            repeat_conf = min(
                1.0,
                math.log1p(int(item["hit_count"])) / math.log(13.0),
            )
            proximity_conf = min(
                1.0,
                float(item["max_line_coverage"])
                + 0.08 * min(int(item["multi_term_lines"]), 4),
            )
            literal_conf = min(
                1.0,
                int(item["literal_hits"]) / max(1, len(literal_set)),
            ) if literal_set else 0.0
            confidence = (
                0.44 * file_coverage
                + 0.26 * proximity_conf
                + 0.12 * repeat_conf
                + 0.10 * float(bool(item["and_hit"]))
                + 0.08 * literal_conf
            )
            if not plan.wants_tests and _TEST_RE.search(file_path):
                confidence *= 0.78
            if not plan.wants_auxiliary and _AUX_RE.search(file_path):
                confidence *= 0.68
            item["file_coverage"] = file_coverage
            item["confidence"] = min(1.0, confidence)

        ordered = sorted(
            per_file,
            key=lambda file_path: (
                -float(per_file[file_path]["confidence"]),
                -float(per_file[file_path]["file_coverage"]),
                -float(per_file[file_path]["max_line_coverage"]),
                -int(per_file[file_path]["and_hit"]),
                float(per_file[file_path]["best_rank"]),
                file_path,
            ),
        )
        details = {
            file_path: {
                "covered": sorted(per_file[file_path]["covered"]),
                "file_coverage": round(
                    float(per_file[file_path]["file_coverage"]),
                    6,
                ),
                "max_line_coverage": round(
                    float(per_file[file_path]["max_line_coverage"]),
                    6,
                ),
                "multi_term_lines": int(
                    per_file[file_path]["multi_term_lines"]
                ),
                "hit_count": int(per_file[file_path]["hit_count"]),
                "and_hit": bool(per_file[file_path]["and_hit"]),
                "literal_hits": int(per_file[file_path]["literal_hits"]),
                "best_rank": round(
                    float(per_file[file_path]["best_rank"]),
                    6,
                ),
                "confidence": round(
                    float(per_file[file_path]["confidence"]),
                    6,
                ),
            }
            for file_path in ordered
        }
        return ordered[:128], details

    def fused_tool_explore(
        self: Any,
        query: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.__dict__.pop("_hybrid_zoekt_capture", None)
        payload = original_tool_explore(
            self,
            query,
            *args,
            **kwargs,
        )
        if not isinstance(payload, dict):
            return payload
        raw_files = payload.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            return payload

        max_files = max(
            1,
            min(int(kwargs.get("max_files", 6)), 10),
        )
        baseline_entries: dict[str, dict[str, Any]] = {}
        baseline_files: list[str] = []
        for entry in raw_files:
            if not isinstance(entry, dict):
                continue
            file_path = str(
                entry.get("path")
                or entry.get("file_path")
                or ""
            )
            if file_path and file_path not in baseline_entries:
                baseline_entries[file_path] = entry
                baseline_files.append(file_path)

        captured = self.__dict__.get("_hybrid_zoekt_capture")
        full_zoekt = (
            list(captured[1])
            if isinstance(captured, tuple)
            and captured
            and captured[0] == query
            else []
        )
        plan = _parse_query(engine_mod, query)
        exact_files, exact_details = exact_symbol_candidates(self, plan)
        anchor_files, anchor_details = anchor_zoekt_candidates(self, plan)
        line_files, line_details = line_fts_candidates(self, plan)

        channels = {
            "baseline": baseline_files,
            "zoekt": full_zoekt,
            "exact": exact_files,
            "anchors": anchor_files,
            "line": line_files,
        }
        # Intent routing is semantic, not repository-specific. Rank evidence is
        # deliberately modest; confidence features below carry the fine ordering.
        rank_weights = {
            "definition": {
                "baseline": 1.0,
                "zoekt": 0.9,
                "exact": 1.4,
                "anchors": 1.1,
                "line": 1.2,
            },
            "symbol": {
                "baseline": 1.2,
                "zoekt": 1.1,
                "exact": 1.4,
                "anchors": 1.1,
                "line": 0.8,
            },
            "code": {
                "baseline": 0.9,
                "zoekt": 0.9,
                "exact": 0.9,
                "anchors": 1.1,
                "line": 1.5,
            },
            "prose": {
                "baseline": 0.8,
                "zoekt": 1.0,
                "exact": 0.3,
                "anchors": 0.4,
                "line": 1.8,
            },
        }[plan.intent]
        confidence_weights = {
            "definition": {
                "exact": 1.25,
                "anchors": 0.60,
                "line": 1.05,
            },
            "symbol": {
                "exact": 1.10,
                "anchors": 0.55,
                "line": 0.55,
            },
            "code": {
                "exact": 0.70,
                "anchors": 0.75,
                "line": 1.20,
            },
            "prose": {
                "exact": 0.15,
                "anchors": 0.20,
                "line": 1.40,
            },
        }[plan.intent]

        scores: dict[str, float] = {}
        channel_ranks: dict[str, dict[str, int]] = {}
        rrf_k = 8.0
        for channel, files in channels.items():
            channel_ranks[channel] = {
                file_path: rank
                for rank, file_path in enumerate(files, 1)
            }
            weight = rank_weights[channel]
            for rank, file_path in enumerate(files, 1):
                scores[file_path] = (
                    scores.get(file_path, 0.0)
                    + weight / (rrf_k + rank)
                )

        for file_path, detail in exact_details.items():
            scores[file_path] = (
                scores.get(file_path, 0.0)
                + confidence_weights["exact"]
                * float(detail["confidence"])
            )
        for file_path, detail in anchor_details.items():
            scores[file_path] = (
                scores.get(file_path, 0.0)
                + confidence_weights["anchors"]
                * float(detail["confidence"])
            )
        for file_path, detail in line_details.items():
            scores[file_path] = (
                scores.get(file_path, 0.0)
                + confidence_weights["line"]
                * float(detail["confidence"])
            )

        top_sets = {
            channel: set(files[:32])
            for channel, files in channels.items()
        }
        explicit_names = {
            name.lower()
            for _kind, name in plan.definitions
        }
        identifier_names = {
            token.lower()
            for token in plan.identifiers
        }
        for file_path in list(scores):
            support = sum(
                file_path in top_set
                for top_set in top_sets.values()
            )
            if support >= 2:
                scores[file_path] += 0.08 * (support - 1)

            exact_detail = exact_details.get(file_path, {})
            kind_matches = set(exact_detail.get("kind_matches", ()))
            if explicit_names and kind_matches:
                scores[file_path] += (
                    0.90 * len(explicit_names & kind_matches)
                )

            path_overlap = len(
                identifier_names & _path_parts(file_path)
            )
            if path_overlap:
                scores[file_path] += 0.035 * path_overlap

            if (
                not plan.wants_tests
                and _TEST_RE.search(file_path)
                and file_path not in baseline_entries
            ):
                scores[file_path] *= 0.78
            if (
                not plan.wants_auxiliary
                and _AUX_RE.search(file_path)
                and file_path not in baseline_entries
            ):
                scores[file_path] *= 0.68
            if (
                file_path.endswith(".pyi")
                and not re.search(r"\bpyi|stub\b", query, re.I)
            ):
                scores[file_path] *= 0.82

        ordered = sorted(
            scores,
            key=lambda file_path: (
                -scores[file_path],
                channel_ranks["baseline"].get(file_path, 10_000),
                channel_ranks["zoekt"].get(file_path, 10_000),
                channel_ranks["exact"].get(file_path, 10_000),
                channel_ranks["anchors"].get(file_path, 10_000),
                channel_ranks["line"].get(file_path, 10_000),
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

        _append_diagnostic(
            {
                "query": query,
                "plan": {
                    "intent": plan.intent,
                    "definitions": plan.definitions,
                    "identifiers": plan.identifiers,
                    "anchors": plan.anchors,
                    "terms": plan.terms,
                    "literals": plan.literals,
                    "wants_tests": plan.wants_tests,
                    "wants_auxiliary": plan.wants_auxiliary,
                },
                "channels": {
                    name: files[:32]
                    for name, files in channels.items()
                },
                "final": ordered,
                "scores": {
                    file_path: round(scores[file_path], 6)
                    for file_path in ordered
                },
                "rank_weights": rank_weights,
                "confidence_weights": confidence_weights,
                "exact_details": {
                    file_path: exact_details[file_path]
                    for file_path in exact_files[:12]
                },
                "anchor_details": {
                    file_path: anchor_details[file_path]
                    for file_path in anchor_files[:12]
                },
                "line_details": {
                    file_path: line_details[file_path]
                    for file_path in line_files[:12]
                },
            }
        )

        result = dict(payload)
        result["files"] = fused_entries
        result["experiment"] = {
            "name": "generic_score_aware_hybrid_v6",
            "intent": plan.intent,
        }
        return result

    engine_cls._zoekt_candidate_files = capturing_zoekt
    engine_cls._generic_fusion_original_tool_explore = original_tool_explore
    engine_cls.tool_explore = fused_tool_explore
    engine_cls._symbol_vote_experiment_installed = True


_install()
