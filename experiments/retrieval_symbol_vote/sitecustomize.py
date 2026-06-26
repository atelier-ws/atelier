"""Opt-in retrieval experiment: discriminative symbol + line evidence fusion.

Activate with ``ATELIER_EXPERIMENT_SYMBOL_VOTE=1`` and put this directory on
``PYTHONPATH``. This module is benchmark-only; production retrieval is untouched.

V2 keeps the gain from rare exact-symbol voting, but separates code-shaped
identifiers from ordinary prose words. It adds a bounded line-FTS channel only
when a multi-identifier query has no multi-symbol exact file. Benchmark gold
files are loaded only for diagnostics and are never used for ranking.
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
_TEST_RE = re.compile(r"(^|/)(tests?|testing|specs?)(/|$)|(^|/)test_[^/]+$", re.IGNORECASE)
_AUX_RE = re.compile(
    r"(^|/)(docs?(?:-internal)?|documentation|examples?|galleries|benchmarks?|frontend|vendor|third_party)(/|$)"
    r"|\.(?:md|rst|ipynb|json|lock)$",
    re.IGNORECASE,
)
_STOP = {
    "and", "as", "assert", "async", "await", "break", "case", "class",
    "continue", "def", "del", "do", "else", "except", "false", "finally",
    "for", "from", "if", "import", "in", "is", "lambda", "none", "not",
    "or", "pass", "raise", "return", "self", "super", "true", "try",
    "while", "with", "yield",
}
_GOLD_CACHE: dict[tuple[str, str], list[str]] | None = None
_REPO_ID_TO_PREFIX: dict[str, str] | None = None


def _is_code_shaped(token: str) -> bool:
    return (
        "_" in token
        or token.isupper()
        or any(ch.isupper() for ch in token[1:])
        or token.startswith("__")
        or token.endswith("__")
    )


def _informative_tokens(query: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _IDENTIFIER_RE.findall(query):
        low = token.lower()
        if low in seen or low in _STOP or len(token) < 3:
            continue
        if not _is_code_shaped(token) and len(token) < 6:
            continue
        if low in {"__init__", "__call__", "__new__", "tests", "testing"}:
            continue
        seen.add(low)
        out.append(token)
    return out[:16]


def _path_parts(file_path: str) -> set[str]:
    return {part for part in re.split(r"[/._-]+", file_path.lower()) if part}


def _query_wants_tests(query: str) -> bool:
    return bool(re.search(r"\btest(?:s|ing)?\b|\bspec\b|pytest|unittest", query, re.IGNORECASE))


def _query_wants_aux(query: str) -> bool:
    return bool(
        re.search(
            r"\bdocs?|documentation|example|gallery|benchmark|frontend|javascript|typescript|readme\b",
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


def _load_gold_diagnostics() -> tuple[dict[str, str], dict[tuple[str, str], list[str]]]:
    global _GOLD_CACHE, _REPO_ID_TO_PREFIX
    if _GOLD_CACHE is not None and _REPO_ID_TO_PREFIX is not None:
        return _REPO_ID_TO_PREFIX, _GOLD_CACHE

    repo_ids: dict[str, str] = {}
    gold_map: dict[tuple[str, str], set[str]] = defaultdict(set)
    try:
        data = json.loads(Path("benchmarks/codebench/data/bench_pairs_multi.json").read_text())
        from atelier.core.foundation.paths import workspace_key

        for prefix, meta in data.get("repos", {}).items():
            repo_ids[str(workspace_key(Path(meta["ws"]).resolve()))] = str(prefix)
        true_map = data.get("true_map", {})
        for query, tid, prefix in data.get("pairs", []):
            for file_path in true_map.get(tid, []):
                gold_map[(str(prefix), str(query))].add(str(file_path).replace("\\", "/"))
    except Exception:
        pass

    _REPO_ID_TO_PREFIX = repo_ids
    _GOLD_CACHE = {key: sorted(value) for key, value in gold_map.items()}
    return _REPO_ID_TO_PREFIX, _GOLD_CACHE


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
        code_tokens = [token for token in _informative_tokens(query) if _is_code_shaped(token)]
        requested = 64 if code_tokens else 40
        overfetch = max(max_files, int(os.environ.get("ATELIER_EXPERIMENT_ZOEKT_FILES", str(requested))))
        files = original_zoekt(self, query, path=path, max_files=overfetch)
        self.__dict__["_symbol_vote_zoekt_capture"] = (query, files)
        return files[:max_files]

    def exact_file_evidence(
        self: Any,
        query: str,
    ) -> tuple[list[str], dict[str, float], dict[str, int], dict[str, dict[str, Any]]]:
        tokens = _informative_tokens(query)
        if not tokens:
            return [], {}, {}, {}

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
                eligible = {token for token, df in frequencies.items() if 0 < df <= 64}
                if not eligible:
                    return tokens, {}, frequencies, {}
                eligible_placeholders = ",".join("?" for _ in eligible)
                rows = conn.execute(
                    f"""
                    SELECT file_path, lower(symbol_name) AS token, kind
                    FROM symbols
                    WHERE repo_id = ? AND lower(symbol_name) IN ({eligible_placeholders})
                    ORDER BY file_path, start_line
                    """,
                    (self.repo_id, *sorted(eligible)),
                ).fetchall()
        except Exception:
            return tokens, {}, {}, {}

        definition_kinds = set(getattr(engine_mod, "_DEFINITION_KINDS", {"class", "function", "method"}))
        per_file_token: dict[str, dict[str, float]] = {}
        details: dict[str, dict[str, Any]] = {}
        for row in rows:
            file_path = str(row["file_path"] or "")
            token = str(row["token"] or "")
            kind = str(row["kind"] or "").lower()
            if not file_path or not token:
                continue

            original = token_by_lower.get(token, token)
            shaped = _is_code_shaped(original)
            if not shaped and kind not in definition_kinds:
                continue

            df = max(1, frequencies.get(token, 1))
            rarity = 1.0 / math.log2(df + 1.0)
            shape = 1.0 + min(len(original), 20) / 100.0
            if "_" in original:
                shape += 0.24
            if original.isupper() or any(ch.isupper() for ch in original[1:]):
                shape += 0.18
            kind_boost = 1.25 if kind in definition_kinds else 0.78
            base_weight = 0.30 if shaped else 0.07
            vote = base_weight * shape * rarity * kind_boost

            current = per_file_token.setdefault(file_path, {}).get(token, 0.0)
            if vote > current:
                per_file_token[file_path][token] = vote
            item = details.setdefault(file_path, {"tokens": set(), "shaped_tokens": set(), "kinds": set()})
            item["tokens"].add(token)
            if shaped:
                item["shaped_tokens"].add(token)
            item["kinds"].add(kind)

        votes: dict[str, float] = {}
        for file_path, token_votes in per_file_token.items():
            strongest = sorted(token_votes.values(), reverse=True)[:3]
            shaped_count = len(details[file_path]["shaped_tokens"])
            votes[file_path] = sum(strongest) + 0.065 * max(0, shaped_count - 1)
            details[file_path] = {
                "tokens": sorted(details[file_path]["tokens"]),
                "shaped_tokens": sorted(details[file_path]["shaped_tokens"]),
                "kinds": sorted(details[file_path]["kinds"]),
                "score": round(votes[file_path], 6),
            }
        return tokens, votes, frequencies, details

    def line_file_evidence(
        self: Any,
        query: str,
        tokens: list[str],
        exact_details: dict[str, dict[str, Any]],
        *,
        max_files: int = 36,
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        shaped = [token for token in tokens if _is_code_shaped(token)]
        if len(shaped) < 2 or any(len(item.get("shaped_tokens", ())) >= 2 for item in exact_details.values()):
            return [], {}

        terms = list(dict.fromkeys(token.lower() for token in shaped))[:8]
        fts_query = " OR ".join(f'"{term}"' for term in terms)
        try:
            with self._connect(readonly=True) as conn:
                rows = conn.execute(
                    """
                    SELECT file_path, line, text, bm25(file_line_fts) AS rank
                    FROM file_line_fts
                    WHERE file_line_fts MATCH ? AND repo_id = ?
                    ORDER BY rank ASC, file_path ASC, line ASC
                    LIMIT 500
                    """,
                    (fts_query, self.repo_id),
                ).fetchall()
        except Exception:
            return [], {}

        evidence: dict[str, dict[str, Any]] = {}
        wants_tests = _query_wants_tests(query)
        wants_aux = _query_wants_aux(query)
        for row in rows:
            file_path = str(row["file_path"] or "")
            if not file_path:
                continue
            if engine_mod.is_generated_path(file_path):
                continue
            if engine_mod._MINIFIED_FILE_RE.search(file_path) or engine_mod._VENDOR_PATH_RE.search(file_path):
                continue
            if not wants_tests and _TEST_RE.search(file_path):
                continue
            if not wants_aux and _AUX_RE.search(file_path):
                continue

            text = str(row["text"] or "").lower()
            covered = {term for term in terms if term in text}
            if not covered:
                continue
            item = evidence.setdefault(
                file_path,
                {"covered": set(), "hits": 0, "best_rank": float(row["rank"] or 0.0)},
            )
            item["covered"].update(covered)
            item["hits"] += 1
            item["best_rank"] = min(float(item["best_rank"]), float(row["rank"] or 0.0))

        scored: list[tuple[int, int, float, str]] = []
        for file_path, item in evidence.items():
            coverage = len(item["covered"])
            if coverage < 2:
                continue
            scored.append((-coverage, -min(int(item["hits"]), 8), float(item["best_rank"]), file_path))
        scored.sort()
        files = [file_path for *_rest, file_path in scored[:max_files]]
        serializable = {
            file_path: {
                "covered": sorted(evidence[file_path]["covered"]),
                "hits": int(evidence[file_path]["hits"]),
                "best_rank": round(float(evidence[file_path]["best_rank"]), 6),
            }
            for file_path in files
        }
        return files, serializable

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
        tokens, exact_votes, frequencies, exact_details = exact_file_evidence(self, query)
        line_files, line_details = line_file_evidence(self, query, tokens, exact_details)

        scores: dict[str, float] = {}
        for rank, file_path in enumerate(baseline_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + 1.0 / (8.0 + rank)
        for rank, file_path in enumerate(zoekt_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + 0.72 / (18.0 + rank)
        for rank, file_path in enumerate(line_files, start=1):
            scores[file_path] = scores.get(file_path, 0.0) + 0.58 / (18.0 + rank)
        for file_path, vote in exact_votes.items():
            scores[file_path] = scores.get(file_path, 0.0) + vote

        query_lowers = {token.lower() for token in tokens}
        wants_tests = _query_wants_tests(query)
        wants_aux = _query_wants_aux(query)
        baseline_set = set(baseline_files)
        zoekt_set = set(zoekt_files)
        for file_path in list(scores):
            scores[file_path] += 0.018 * len(query_lowers & _path_parts(file_path))
            if file_path in exact_votes and file_path in zoekt_set:
                scores[file_path] += 0.045
            unsupported = file_path not in baseline_set and file_path not in zoekt_set
            if unsupported and not wants_aux and _AUX_RE.search(file_path):
                scores[file_path] *= 0.32
            if unsupported and not wants_tests and _TEST_RE.search(file_path):
                scores[file_path] *= 0.58

        baseline_rank = {file_path: rank for rank, file_path in enumerate(baseline_files, start=1)}
        zoekt_rank = {file_path: rank for rank, file_path in enumerate(zoekt_files, start=1)}
        line_rank = {file_path: rank for rank, file_path in enumerate(line_files, start=1)}
        ordered = sorted(
            scores,
            key=lambda file_path: (
                -scores[file_path],
                baseline_rank.get(file_path, 10_000),
                zoekt_rank.get(file_path, 10_000),
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
                fused_entries.append({"path": file_path, "language": "unknown", "symbols": [], "source_sections": []})

        repo_ids, gold_map = _load_gold_diagnostics()
        prefix = repo_ids.get(str(getattr(self, "repo_id", "")), "")
        gold = gold_map.get((prefix, query), [])
        exact_files = sorted(exact_votes, key=lambda fp: (-exact_votes[fp], fp))
        _append_diagnostic({
            "repo": str(getattr(self, "repo_id", "")),
            "prefix": prefix,
            "query": query,
            "tokens": tokens,
            "token_df": frequencies,
            "baseline": baseline_files[:10],
            "zoekt": zoekt_files[:24],
            "exact": exact_files[:24],
            "line": line_files[:24],
            "final": ordered,
            "gold": gold,
            "ranks": {
                "baseline": _rank(baseline_files, gold),
                "zoekt": _rank(zoekt_files, gold),
                "exact": _rank(exact_files, gold),
                "line": _rank(line_files, gold),
                "final": _rank(ordered, gold),
            },
            "exact_details": {file_path: exact_details[file_path] for file_path in exact_files[:12]},
            "line_details": {file_path: line_details[file_path] for file_path in line_files[:12]},
            "scores": {file_path: round(scores[file_path], 6) for file_path in ordered},
        })

        result = dict(payload)
        result["files"] = fused_entries
        result["experiment"] = {
            "name": "discriminative_symbol_line_fusion_v2",
            "tokens": tokens,
            "line_candidates": len(line_files),
        }
        return result

    engine_cls._zoekt_candidate_files = capturing_zoekt
    engine_cls._symbol_vote_exact_file_evidence = exact_file_evidence
    engine_cls._symbol_vote_line_file_evidence = line_file_evidence
    engine_cls._symbol_vote_original_tool_explore = original_tool_explore
    engine_cls.tool_explore = fused_tool_explore
    engine_cls._symbol_vote_experiment_installed = True


_install()
