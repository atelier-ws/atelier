"""Load V6 retrieval and optionally rerank only its existing top-five files.

Setup:
1. Keep the restored V6 implementation beside this file as ``v6_base.py``.
2. Run ``train_self_supervised_reranker.py`` once to create repository-local models.
3. The benchmark runner activates this file with ATELIER_EXPERIMENT_SYMBOL_VOTE=1.

The online wrapper performs no retrieval, database queries, or training. It only
extracts cheap features from the file entries V6 already returned.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
from pathlib import Path
from typing import Any

_EXPERIMENT_DIR = Path(__file__).resolve().parent
_BASE_FILE = _EXPERIMENT_DIR / "v6_base.py"
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|testing|specs?)(/|$)|(^|/)test_[^/]+$|_test\.[^/]+$",
    re.IGNORECASE,
)
_DOC_PATH_RE = re.compile(
    r"(^|/)(docs?|documentation|examples?|galleries)(/|$)|"
    r"\.(?:md|rst|ipynb)$",
    re.IGNORECASE,
)
_QUERY_TEST_RE = re.compile(
    r"\btests?\b|\btesting\b|\bpytest\b|\bunittest\b|\bspecs?\b|"
    r"\btest_[A-Za-z0-9_]+",
    re.IGNORECASE,
)
_QUERY_DOC_RE = re.compile(
    r"\bdocs?\b|\bdocumentation\b|\bexamples?\b|\bgallery\b|\breadme\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "class",
    "def",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "return",
    "self",
    "the",
    "to",
    "with",
}
_FEATURE_NAMES = (
    "reciprocal_rank",
    "rank_one",
    "path_term_coverage",
    "path_identifier_exact",
    "basename_similarity",
    "symbol_term_coverage",
    "symbol_identifier_exact",
    "source_term_coverage",
    "source_best_line_coverage",
    "test_scope_match",
    "test_scope_mismatch",
    "doc_scope_match",
    "doc_scope_mismatch",
    "path_depth",
)
_MODEL_CACHE: dict[str, dict[str, Any] | None] = {}
_DIAGNOSTIC_FD: int | None = None


def _dedupe(values: list[str], limit: int) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
        if len(output) >= limit:
            break
    return tuple(output)


def _identifier_parts(value: str) -> list[str]:
    parts: list[str] = []
    for raw in re.split(r"[./:_-]+", value):
        for camel_part in _CAMEL_RE.split(raw):
            normalized = camel_part.strip().lower()
            if len(normalized) >= 2 and normalized not in _STOPWORDS:
                parts.append(normalized)
    return parts


def _query_features(query: str) -> tuple[tuple[str, ...], tuple[str, ...], bool, bool]:
    identifiers = [
        token
        for token in _IDENTIFIER_RE.findall(query)
        if len(token) >= 3
        and token.lower() not in _STOPWORDS
        and ("_" in token or "." in token or token.isupper() or any(character.isupper() for character in token[1:]))
    ]
    terms: list[str] = []
    for raw in _TOKEN_RE.findall(query):
        terms.extend(_identifier_parts(raw))
        normalized = raw.lower()
        if len(normalized) >= 3 and normalized not in _STOPWORDS:
            terms.append(normalized)
    return (
        _dedupe(terms, 20),
        _dedupe(identifiers, 12),
        bool(_QUERY_TEST_RE.search(query)),
        bool(_QUERY_DOC_RE.search(query)),
    )


def _flatten_text(value: Any, limit: int = 12_000) -> str:
    chunks: list[str] = []
    remaining = limit

    def visit(item: Any) -> None:
        nonlocal remaining
        if remaining <= 0 or item is None:
            return
        if isinstance(item, str):
            text = item[:remaining]
            chunks.append(text)
            remaining -= len(text)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key) in {"content_hash", "symbol_id", "repo_id"}:
                    continue
                visit(child)
                if remaining <= 0:
                    break
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
                if remaining <= 0:
                    break

    visit(value)
    return "\n".join(chunks)


def _coverage(text: str, terms: tuple[str, ...]) -> float:
    if not terms:
        return 0.0
    lowered = text.lower()
    return sum(term in lowered for term in terms) / len(terms)


def _trigrams(value: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", "", value.lower())
    if not normalized:
        return set()
    if len(normalized) < 3:
        return {normalized}
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def _similarity(left: str, right: str) -> float:
    left_grams = _trigrams(left)
    right_grams = _trigrams(right)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


def _entry_path(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("path") or entry.get("file_path") or "")


def _entry_features(
    query: str,
    entry: dict[str, Any],
    rank: int,
) -> list[float]:
    terms, identifiers, wants_tests, wants_docs = _query_features(query)
    file_path = _entry_path(entry).replace("\\", "/")
    path_text = file_path.lower()
    basename = Path(file_path).stem

    symbol_text = _flatten_text(entry.get("symbols"))
    source_text = _flatten_text(entry.get("source_sections"))
    source_lines = source_text.splitlines()
    best_line_coverage = max(
        (_coverage(line, terms) for line in source_lines[:400]),
        default=0.0,
    )

    path_identifier_exact = max(
        (float(identifier in path_text) for identifier in identifiers),
        default=0.0,
    )
    symbol_identifier_exact = max(
        (float(identifier in symbol_text.lower()) for identifier in identifiers),
        default=0.0,
    )
    basename_similarity = max(
        (_similarity(identifier, basename) for identifier in identifiers),
        default=0.0,
    )

    is_test = bool(_TEST_PATH_RE.search(file_path))
    is_doc = bool(_DOC_PATH_RE.search(file_path))
    depth = min(1.0, file_path.count("/") / 12.0)

    return [
        1.0 / max(1, rank),
        float(rank == 1),
        _coverage(path_text, terms),
        path_identifier_exact,
        basename_similarity,
        _coverage(symbol_text, terms),
        symbol_identifier_exact,
        _coverage(source_text, terms),
        best_line_coverage,
        float(wants_tests and is_test),
        float(not wants_tests and is_test),
        float(wants_docs and is_doc),
        float(not wants_docs and is_doc),
        depth,
    ]


def _repo_key(repo_root: Path) -> str:
    return hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:16]


def _model_for(engine: Any) -> dict[str, Any] | None:
    repo_id = str(getattr(engine, "repo_id", "") or "")
    key = repo_id or _repo_key(Path(engine.repo_root))
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    # Primary path: train_real_retrieval_reranker.py writes
    # self_supervised_models/<repo_id>.json (keyed by repo, no /tmp conflicts).
    candidates: list[Path] = []
    if repo_id:
        candidates.append(_EXPERIMENT_DIR / "self_supervised_models" / f"{repo_id}.json")
    # Legacy path: model written alongside the workspace DB.
    candidates.append(Path(engine.db_path).parent / "explore_reranker.json")

    for model_path in candidates:
        try:
            model = json.loads(model_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if (
            isinstance(model, dict)
            and model.get("enabled")
            and model.get("feature_names") == list(_FEATURE_NAMES)
            and len(model.get("weights", [])) == len(_FEATURE_NAMES)
        ):
            _MODEL_CACHE[key] = model
            return model

    _MODEL_CACHE[key] = None
    return None


def _linear_score(weights: list[float], features: list[float]) -> float:
    return sum(weight * value for weight, value in zip(weights, features, strict=True))


def _rerank_entries(
    query: str,
    entries: list[dict[str, Any]],
    model: dict[str, Any],
) -> list[dict[str, Any]]:
    window_size = min(5, len(entries))
    if window_size < 2:
        return entries

    weights = [float(value) for value in model["weights"]]
    blend = float(model.get("blend", 1.0))
    margin = float(model.get("margin", 0.0))
    window = entries[:window_size]

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for rank, entry in enumerate(window, 1):
        features = _entry_features(query, entry, rank)
        learned = _linear_score(weights, features)
        combined = blend * learned + (1.0 - blend) * (1.0 / rank)
        scored.append((combined, rank, entry))

    proposed = sorted(scored, key=lambda item: (-item[0], item[1]))
    if proposed[0][1] != 1:
        original_top_score = next(score for score, rank, _entry in scored if rank == 1)
        if proposed[0][0] - original_top_score < margin:
            return entries

    reranked_window = [entry for _score, _rank, entry in proposed]
    return [*reranked_window, *entries[window_size:]]


def _append_diagnostic(
    engine: Any,
    query: str,
    entries: list[dict[str, Any]],
    model: dict[str, Any],
) -> None:
    global _DIAGNOSTIC_FD

    target = os.environ.get("ATELIER_EXPERIMENT_DIAGNOSTICS", "").strip()
    if not target:
        return

    payload = {
        "version": "v6_self_supervised_top5",
        "repo_root": str(Path(engine.repo_root).resolve()),
        "repo_id": str(getattr(engine, "repo_id", "")),
        "query": query,
        "final": [path for entry in entries if (path := _entry_path(entry))],
        "model": {
            "blend": model.get("blend"),
            "margin": model.get("margin"),
            "validation": model.get("validation"),
        },
    }
    try:
        if _DIAGNOSTIC_FD is None:
            _DIAGNOSTIC_FD = os.open(
                target,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY,
                0o644,
            )
        line = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        os.write(_DIAGNOSTIC_FD, f"{line}\n".encode())
    except OSError:
        return


def _install_scoring_wrapper() -> None:
    if os.environ.get("ATELIER_EXPERIMENT_SYMBOL_VOTE") != "1":
        return
    if os.environ.get("ATELIER_SELF_SUPERVISED_TRAINING") == "1":
        return

    from atelier.core.capabilities.code_context import (
        engine as engine_mod,
    )

    engine_cls = engine_mod.CodeContextEngine
    if getattr(engine_cls, "_self_supervised_top5_installed", False):
        return

    original_tool_explore = engine_cls.tool_explore

    def reranked_tool_explore(
        self: Any,
        query: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = original_tool_explore(self, query, *args, **kwargs)
        if not isinstance(payload, dict):
            return payload

        raw_entries = payload.get("files")
        if not isinstance(raw_entries, list):
            return payload
        entries = [entry for entry in raw_entries if isinstance(entry, dict)]
        if len(entries) != len(raw_entries):
            return payload

        model = _model_for(self)
        if model is None:
            return payload

        reranked = _rerank_entries(query, entries, model)
        if reranked == entries:
            return payload

        result = dict(payload)
        result["files"] = reranked
        result["experiment"] = {
            "name": "v6_self_supervised_top5",
            "base": payload.get("experiment"),
        }
        _append_diagnostic(self, query, reranked, model)
        return result

    engine_cls.tool_explore = reranked_tool_explore
    engine_cls._self_supervised_top5_installed = True


if os.environ.get("ATELIER_EXPERIMENT_SYMBOL_VOTE") == "1":
    if not _BASE_FILE.exists():
        raise RuntimeError(
            "Missing experiments/retrieval_symbol_vote/v6_base.py. "
            "Rename the restored V6 sitecustomize.py to v6_base.py before "
            "installing this loader."
        )
    runpy.run_path(str(_BASE_FILE), run_name="_atelier_retrieval_v6_base")
    _install_scoring_wrapper()
