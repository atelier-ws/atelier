"""Persistent symbol index and token-budgeted retrieval for local code."""

from __future__ import annotations

import ast
import atexit
import concurrent.futures
import contextlib
import fnmatch
import hashlib
import itertools
import json
import logging
import multiprocessing
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, cast, overload

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

from rapidfuzz import process as rapidfuzz_process
from rapidfuzz.distance import DamerauLevenshtein

from atelier.core.capabilities.code_context.ann_symbol_index import (
    SymbolAnnIndex,
    ann_retrieval_enabled,
)
from atelier.core.capabilities.code_context.budget import (
    PROTECTED_TOP_RANK,
    BudgetPacker,
)
from atelier.core.capabilities.code_context.cache import RetrievalCache
from atelier.core.capabilities.code_context.call_graph import (
    CallGraphDirection,
    CallGraphEdge,
    CallGraphNode,
    CallGraphTraversalResult,
    build_call_graph_payload,
    traverse_call_graph,
)
from atelier.core.capabilities.code_context.call_graph_centrality import compute_call_graph_centrality
from atelier.core.capabilities.code_context.embedding import (
    SearchMode,
    SemanticSearchRanker,
    resolve_search_mode,
    semantic_candidate_limit,
)
from atelier.core.capabilities.code_context.generated_files import is_generated_path
from atelier.core.capabilities.code_context.intel_store import ProviderHealth, SymbolIntelStore
from atelier.core.capabilities.code_context.models import (
    ContextPack,
    CrossLangReference,
    IndexedFileRecord,
    IndexStats,
    RouteRecord,
    SymbolRecord,
    TextMatch,
    UsageReference,
)
from atelier.core.capabilities.code_context.output_policy import (
    hard_cap_chars,
    resolve_output_policy,
)
from atelier.core.capabilities.code_context.rerank import SearchReranker
from atelier.core.capabilities.repo_map import build_repo_map
from atelier.core.capabilities.repo_map.budget import count_tokens, estimate_tokens
from atelier.core.capabilities.repo_map.graph import iter_source_files, should_skip_relative_path
from atelier.core.foundation.paths import default_store_root
from atelier.core.service.telemetry import emit_product_local
from atelier.infra.code_intel.astgrep import (
    AstGrepAdapter,
    AstGrepToolUnavailable,
    PatternMatch,
    PatternRewriteResult,
    PatternSearchResult,
)
from atelier.infra.code_intel.cross_lang import CrossLangEdge, CrossLangEdgeStore
from atelier.infra.internal_llm.exceptions import OllamaUnavailable
from atelier.infra.tree_sitter.tags import Tag, detect_language, extract_tags

if TYPE_CHECKING:
    from atelier.core.capabilities.code_context.search_verdict import ChannelHealth
    from atelier.infra.code_intel.git_history.adapter import DeletedHistorySearchAdapter

_MAX_FILE_BYTES = 1_000_000
# G4: hard cap on symbols embedded/persisted for the opt-in ANN store per query,
# bounding embed cost and graph build time on first (cold) use.
_ANN_SYMBOL_CANDIDATE_CAP = 2000
logger = logging.getLogger(__name__)

_DB_LOCKS_GUARD = threading.Lock()
_DB_LOCKS: dict[str, threading.RLock] = {}


def _shared_db_lock(db_path: Path) -> threading.RLock:
    key = str(db_path.resolve())
    with _DB_LOCKS_GUARD:
        lock = _DB_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _DB_LOCKS[key] = lock
        return lock


_FTS_TERM_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_PRECISE_SYMBOL_QUERY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SINCE_RELATIVE_RE = re.compile(r"^(?P<amount>\d+)(?P<unit>[dwmy])$")
_JS_IMPORT_RE = re.compile(
    r"(?:from\s+['\"]([^'\"]+)['\"]|import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)|require\(\s*['\"]([^'\"]+)['\"]\s*\))"
)
_RUST_MOD_RE = re.compile(r"^\s*(?:pub\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", re.M)
_GO_IMPORT_RE = re.compile(r"^\s*import\s+(?:\((.*?)\)|\"([^\"]+)\")", re.M | re.S)
_FASTAPI_DECORATOR_RE = re.compile(
    r"^\s*@(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.(?P<verb>get|post|put|patch|delete|options|head|trace|websocket)\(\s*['\"](?P<route>[^'\"]+)['\"]"
)
_FASTAPI_API_ROUTE_RE = re.compile(
    r"^\s*@(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.api_route\(\s*['\"](?P<route>[^'\"]+)['\"](?P<rest>.*)\)\s*$"
)
_FLASK_ROUTE_RE = re.compile(
    r"^\s*@(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.route\(\s*['\"](?P<route>[^'\"]+)['\"](?P<rest>.*)\)\s*$"
)
_FLASK_ADD_URL_RULE_RE = re.compile(
    r"^\s*(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.add_url_rule\(\s*['\"](?P<route>[^'\"]+)['\"](?P<rest>.*)\)\s*$"
)
_DJANGO_PATH_RE = re.compile(
    r"^\s*(?:re_)?path\(\s*['\"](?P<route>[^'\"]+)['\"]\s*,\s*(?P<handler>[A-Za-z_][A-Za-z0-9_\.]*)"
)
_DJANGO_URL_RE = re.compile(
    r"^\s*url\(\s*(?:r)?['\"](?P<route>[^'\"]+)['\"]\s*,\s*(?P<handler>[A-Za-z_][A-Za-z0-9_\.]*)"
)
_EXPRESS_ROUTE_RE = re.compile(
    r"(?P<router>app|router)\.(?P<verb>get|post|put|patch|delete|options|head|all|use)\(\s*[`'\"](?P<route>[^`'\"]+)[`'\"]\s*(?:,\s*(?P<handler>[A-Za-z_$][A-Za-z0-9_$.]*))?"
)
_EXPRESS_ROUTE_CHAIN_RE = re.compile(
    r"(?P<router>app|router)\.route\(\s*[`'\"](?P<route>[^`'\"]+)[`'\"]\s*\)(?P<chain>.+)$"
)
_EXPRESS_CHAIN_METHOD_RE = re.compile(
    r"\.(?P<verb>get|post|put|patch|delete|options|head|all|use)\(\s*(?P<handler>[A-Za-z_$][A-Za-z0-9_$.]*)?"
)
_METHOD_LITERAL_RE = re.compile(r"['\"](?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|TRACE|CONNECT)['\"]", re.I)
_LOCAL_PROVENANCE = "local"
_SEARCH_ESSENTIAL_KEYS = [
    "symbol_id",
    "symbol_name",
    "qualified_name",
    "file_path",
    "kind",
    "start_line",
    "signature",
    "provenance",
]
# Fields stripped from each item for repo-scope searches where they are
# always uniform or unnecessary ("origin" is always "internal"; per-item
# "provenance" is redundant with top-level; "symbol_id" is internal only).
_SEARCH_REPO_STRIP_ITEM_KEYS: frozenset[str] = frozenset({"origin", "provenance", "symbol_id"})
_SEARCH_OPTIONAL_KEYS = [
    "snippet",
    "doc_summary",
    "score",
    "repo_id",
    "content_hash",
    "parent_symbol",
    "start_byte",
    "end_byte",
]
_DELETED_SEARCH_ESSENTIAL_KEYS = [
    *_SEARCH_ESSENTIAL_KEYS,
    "deleted_at",
    "deleted_at_sha",
    "last_author",
]
_DELETED_SEARCH_OPTIONAL_KEYS = [
    "rename_target",
    "rename_note",
    "last_commit_msg",
    "matched_on",
]
_SEARCH_COMPACT_DEFAULT_KEYS = set([*_SEARCH_ESSENTIAL_KEYS, "score", "commit_sha"])
_LINEAGE_INDEX_VERSION = 2
_LINEAGE_DEFAULT_SCORE_PENALTY = 0.1
_DELETED_SEARCH_COMPACT_DEFAULT_KEYS = set(
    [*_DELETED_SEARCH_ESSENTIAL_KEYS, "score", "matched_on", "rename_target", "rename_note"]
)
_FILES_ESSENTIAL_KEYS = ["file_path"]
_FILES_OPTIONAL_KEYS = ["top_symbols", "symbol_count", "language"]
_ROUTES_ESSENTIAL_KEYS = ["framework", "method", "route", "file_path", "line", "provenance"]
_ROUTES_OPTIONAL_KEYS = ["handler", "router", "language"]
_SYMBOL_ESSENTIAL_KEYS = ["symbol_name"]
_SYMBOL_OPTIONAL_KEYS = [
    "source",
    "doc_summary",
    "content_hash",
    "parent_symbol",
    "start_byte",
    "end_byte",
    "repo_id",
    "score",
    "cross_lang_refs",
]
_INDEX_ESSENTIAL_KEYS = [
    "repo_id",
    "files_indexed",
    "symbols_indexed",
    "imports_indexed",
    "index_version",
    "provenance",
]
_CONTEXT_ESSENTIAL_KEYS = [
    "task",
    "symbols",
]
_EXPLORE_ESSENTIAL_KEYS = [
    "query",
    "entry_points",
    "truncated",
    "provenance",
]
# `files` is the primary content -- drop it LAST (after relationships/metadata) so a
# budget-pressured explore degrades to fewer files rather than collapsing to nothing.
_EXPLORE_OPTIONAL_KEYS = [
    "relationships",
    "additional_relevant_files",
    "skeletonized",
    "skeleton_tokens_saved",
    "files",
]
_EXPLORE_SOURCE_SECTION_MAX_CHARS = resolve_output_policy("context").max_code_block_chars

# Index-free sibling skeletonization for tool_explore: when an explore result
# pulls >=3 same-kind symbols that share a name affix (e.g. *Embedder, *Resolver),
# the highest-scored member is kept full and the rest render signatures-only.
# Heuristic over the already-selected symbols -- no new index/SCIP queries.
_SKELETON_KINDS = frozenset({"class", "struct", "interface", "trait", "protocol", "enum", "method", "function"})
_SKELETON_STOPWORDS = frozenset(
    {
        "make",
        "handle",
        "data",
        "base",
        "util",
        "utils",
        "test",
        "tests",
        "impl",
        "main",
        "value",
        "values",
        "name",
        "names",
        "type",
        "types",
        "node",
        "item",
        "items",
        "list",
        "dict",
        "async",
        "await",
        "none",
        "true",
        "false",
        "self",
        "func",
        "call",
        "args",
        "kwargs",
        "init",
        "build",
        "create",
        "update",
        "delete",
        "result",
        "config",
        "client",
        "server",
        "model",
        "models",
        "error",
        "errors",
    }
)
_SKELETON_MIN_FAMILY = 3
_SKELETON_MIN_BODY_LINES = 12
# Family-completion retrieval: surface sibling families that name-ranked search
# misses (FTS tokenization splits camelCase, so 'embedder' finds the base class
# but not 'OpenAIEmbedder'). Bounded substring lookups over the symbol index.
_EXPLORE_FAMILY_PROBE_SYMBOLS = 12
_EXPLORE_FAMILY_TOTAL_CAP = 12
_EXPLORE_FAMILY_PER_FAMILY_CAP = 8
_EXPLORE_FAMILY_FILE_CAP = 16
# Definitional kinds outrank trivial variables/constants when explore decides which
# files survive the file/budget caps -- a class/function is higher signal than a const.
_DEFINITION_KINDS = frozenset(
    {"class", "struct", "interface", "trait", "protocol", "enum", "function", "method", "type_alias", "namespace"}
)
# Kinds probed by query-driven family completion (the definition families a query names).
_QUERY_PROBE_KINDS = ("class", "function", "method")


def _explore_skeleton_enabled() -> bool:
    """Whether tool_explore sibling skeletonization is active (env override)."""
    import os

    value = os.environ.get("ATELIER_EXPLORE_SKELETON")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


# Callee short-names that resolve to language builtins / ubiquitous container
# methods. As callees they have no navigable definition and only add noise +
# tokens, so they are dropped when no same-language definition is indexed.
_PY_CALLEE_NOISE: frozenset[str] = frozenset(
    {
        "abs",
        "all",
        "any",
        "ascii",
        "bin",
        "bool",
        "bytearray",
        "bytes",
        "callable",
        "chr",
        "classmethod",
        "compile",
        "complex",
        "delattr",
        "dict",
        "dir",
        "divmod",
        "enumerate",
        "eval",
        "exec",
        "filter",
        "float",
        "format",
        "frozenset",
        "getattr",
        "globals",
        "hasattr",
        "hash",
        "help",
        "hex",
        "id",
        "input",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "locals",
        "map",
        "max",
        "memoryview",
        "min",
        "next",
        "object",
        "oct",
        "open",
        "ord",
        "pow",
        "print",
        "property",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "setattr",
        "slice",
        "sorted",
        "staticmethod",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "vars",
        "zip",
        "append",
        "extend",
        "insert",
        "pop",
        "remove",
        "clear",
        "copy",
        "get",
        "keys",
        "values",
        "items",
        "update",
        "setdefault",
        "add",
        "discard",
        "join",
        "split",
        "rsplit",
        "splitlines",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "startswith",
        "endswith",
        "lower",
        "upper",
        "title",
        "encode",
        "decode",
        "read",
        "write",
        "readline",
        "readlines",
        "close",
        "flush",
        "seek",
        "format_map",
        "index",
        "count",
        "sort",
        "reverse",
        "find",
        "rfind",
        "group",
    }
)

_USAGES_ESSENTIAL_KEYS = ["file_path", "line", "provenance"]
_USAGES_OPTIONAL_KEYS = ["snippet", "caller", "edge_kind", "confidence"]
_PATTERN_ESSENTIAL_KEYS = ["file_path", "line", "snippet"]
_PATTERN_OPTIONAL_KEYS = ["captures", "column", "end_line", "end_column"]
_STATUS_ESSENTIAL_KEYS = [
    "repo_id",
    "repo_root",
    "db_path",
    "index_version",
    "index",
    "cache",
    "providers",
    "provider_freshness",
    "warnings",
    "freshness",
    "autosync",
    "provenance",
]
_CACHE_STATUS_ESSENTIAL_KEYS = [
    "repo_id",
    "index_version",
    "entry_count",
    "entries_by_tool",
    "total_bytes",
    "max_bytes",
]
_CACHE_INVALIDATE_ESSENTIAL_KEYS = ["invalidated_entries"]
_CALL_GRAPH_ESSENTIAL_KEYS = [
    "target",
    "direction",
    "related",
    "related_count",
    "data_status",
    "provenance",
]
_CALL_GRAPH_OPTIONAL_KEYS = [
    "depth",
    "related",
    "related_count",
    "truncated",
    "edges",
    "edge_count",
    "data_status",
    "ambiguity",
    "message",
    "snapshot",
]
_BLAME_ESSENTIAL_KEYS = [
    "symbol_name",
    "file_path",
    "provenance",
]
_BLAME_OPTIONAL_KEYS = [
    "index_sha",
    "head_sha",
    "last_modified",
    "last_commit_summary",
    "hunks",
    "churn",
]
_OVERFLOW_SPILL_MIN_EXCESS_TOKENS = 128
_OVERFLOW_SPILL_MIN_REDUCTION_TOKENS = 256
DeletedHistoryItem = dict[str, Any]
_CACHE_TOOL_ALIASES = {
    "all": None,
    "explore": "code.explore",
    "files": "code.files",
    "status": "code.status",
    "routes": "code.routes",
    "search": "code.search",
    "symbol": "code.symbol",
    "context": "code.context",
    "usages": "code.usages",
    "callers": "code.callers",
    "callees": "code.callees",
    "pattern": "code.pattern",
}
_OPERATION_TOKEN_CAPS = {
    "cache_status": 50,
    "index": 80,
    "search": 800,
    "symbol": 800,
    "pattern": 800,
    "callers": 700,
    "callees": 300,
    "usages": 700,
    "context": 2400,
    "blame": 50,
    "cache_invalidate": 35,
}
# Map internal field names to shortened MCP output names to reduce token bloat.
# Applied post-processing in _short_item_keys().
_FIELD_NAME_SHORTMAP = {
    "file_path": "path",
    "symbol_name": "name",
    "symbol_id": "id",
    "start_line": "line",
    "doc_summary": "doc",
    "deleted_at": "deleted",
    "deleted_at_sha": "deleted_sha",
    "last_author": "author",
    "last_commit_msg": "msg",
    "matched_on": "match",
    "rename_target": "renamed_to",
    "rename_note": "rename",
}


def apply_field_name_shortening(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply field-name shortening to reduce token bloat in MCP responses.
    Maps internal names (file_path, start_line, etc.) to compact forms (path, line, etc.).
    Applies recursively to all nested structures.
    """

    def shorten_dict(item: dict[str, Any]) -> dict[str, Any]:
        """Recursively shorten field names in a dict."""
        result: dict[str, Any] = {}
        for k, v in item.items():
            short_key = _FIELD_NAME_SHORTMAP.get(k, k)
            if isinstance(v, dict):
                result[short_key] = shorten_dict(v)
            elif isinstance(v, list):
                if v and isinstance(v[0], dict):
                    result[short_key] = [shorten_dict(i) if isinstance(i, dict) else i for i in v]
                else:
                    result[short_key] = v
            else:
                result[short_key] = v
        return result

    # Shorten entire payload recursively, but handle snapshot specially
    result = {}
    for k, v in payload.items():
        short_key = _FIELD_NAME_SHORTMAP.get(k, k)
        if isinstance(v, dict):
            # Don't shorten top-level snapshot dict as it has specific structure
            if k != "snapshot":
                result[short_key] = shorten_dict(v)
            else:
                result[short_key] = v
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            result[short_key] = [shorten_dict(item) for item in v]  # type: ignore[assignment]
        else:
            result[short_key] = v
    return result


_SEARCH_SNIPPET_FORCE_COMPACT_LIMIT = 50


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


@dataclass(frozen=True)
class _ExtractedSymbol:
    name: str
    qualified_name: str
    kind: str
    signature: str
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    parent_symbol: str | None = None
    doc_summary: str | None = None


@dataclass(frozen=True)
class _IndexedReference:
    """A local, index-time reference extracted from Python AST."""

    file_path: str
    symbol_name: str
    line: int
    column: int
    end_column: int
    enclosing_symbol_name: str | None
    enclosing_qualified_name: str | None
    snippet: str


@dataclass(frozen=True)
class _IndexedCallEdge:
    """A local, index-time function/method call edge extracted from Python AST."""

    caller_symbol_name: str
    caller_qualified_name: str
    caller_file_path: str
    caller_start_line: int
    caller_end_line: int
    callee_name: str
    call_line: int
    call_column: int
    snippet: str


@dataclass
class _FileIndexData:
    """Pure extraction result for one file — no DB handles."""

    rel: str
    language: str
    content_hash: str
    size_bytes: int
    text_lines: list[tuple[int, str]]
    symbols: list[_ExtractedSymbol]
    symbol_sources: list[str]  # source slices for FTS (parallel to symbols)
    imports: list[tuple[str, str | None]]
    references: list[_IndexedReference]
    call_edges: list[_IndexedCallEdge]
    mtime_ns: int = 0


class IndexLockTimeout(RuntimeError):
    """A required index-write lock could not be acquired before the timeout.

    Raised only when a caller passes ``require_lock=True`` (e.g. the CLI
    ``atelier code index`` prewarm), so a contended/failed build fails loudly
    instead of silently returning a stale snapshot.
    """

    def __init__(self, db_path: Path) -> None:
        super().__init__(
            f"index-write lock not acquired for {db_path}: another atelier process "
            "is indexing. Increase ATELIER_INDEX_LOCK_TIMEOUT_S or retry."
        )


def _index_lock_timeout_s() -> float:
    """Seconds a blocking index-write-lock acquisition waits before giving up.

    Defaults to 10s (unchanged); override via ATELIER_INDEX_LOCK_TIMEOUT_S for
    long prewarm builds that must win the lock before serving tool calls.
    """
    raw = os.environ.get("ATELIER_INDEX_LOCK_TIMEOUT_S")
    if not raw:
        return 10.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 10.0


def _repo_id(repo_root: Path) -> str:
    return hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:16]


def _default_db_path(repo_root: Path) -> Path:
    from atelier.core.foundation.paths import workspace_key

    workspace_hash = workspace_key(repo_root.resolve())
    return default_store_root() / "workspaces" / workspace_hash / "code_context.sqlite"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    total = 0
    for line in text.splitlines(keepends=True):
        total += len(line.encode("utf-8"))
        offsets.append(total)
    if not text.endswith(("\n", "\r")):
        offsets.append(total)
    return offsets


def _safe_relpath(repo_root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(repo_root))
    except ValueError:
        return str(resolved)


def _safe_fts_query(query: str) -> str:
    # Quote each term as an FTS5 string literal so natural-language queries whose
    # words happen to be FTS operators (or/and/near/not) are treated as literal
    # terms instead of breaking the MATCH grammar. Terms are [A-Za-z0-9_]+ only,
    # so no embedded-quote escaping is required.
    terms = _FTS_TERM_RE.findall(query)
    return " OR ".join(f'"{term[:64]}"' for term in terms[:12] if term)


def _fts_prefix_query(query: str) -> str:
    terms = _FTS_TERM_RE.findall(query)
    return " OR ".join(f'"{term[:64]}"*' for term in terms[:12] if term)


def _identifier_terms(text: str) -> list[str]:
    terms: list[str] = []
    for raw in _FTS_TERM_RE.findall(text):
        for split in _CAMEL_BOUNDARY_RE.split(raw):
            lowered = split.strip().lower()
            if lowered:
                terms.append(lowered)
    return terms


# Damerau-Levenshtein normalized-similarity floor for fuzzy symbol recovery. A
# single transposition/typo in a >=4-char name stays above this; shorter noise is
# rejected. Scale is 0..1 (1.0 == identical).
_FUZZY_SIMILARITY_CUTOFF = 0.75


def _is_precise_symbol_query(query: str) -> bool:
    return bool(_PRECISE_SYMBOL_QUERY_RE.fullmatch(query.strip()))


def _should_run_full_fuzzy_symbol_scan(query: str) -> bool:
    normalized = query.strip()
    if not _is_precise_symbol_query(normalized):
        return False
    # Digit-bearing generated identifiers are common no-hit probes and rare
    # typo targets; avoid the expensive full-symbol fuzzy scan for them.
    return not any(char.isdigit() for char in normalized)


def _matches_file_glob(path: str, pattern: str) -> bool:
    normalized_path = path.replace("\\", "/")
    normalized_pattern = pattern.replace("\\", "/")
    pure_path = PurePosixPath(normalized_path)
    if pure_path.match(normalized_pattern):
        return True
    if "**/" in normalized_pattern and pure_path.match(normalized_pattern.replace("**/", "")):
        return True
    if fnmatch.fnmatch(normalized_path, normalized_pattern):
        return True
    regex = re.escape(normalized_pattern)
    regex = regex.replace(r"\*\*/", r"(?:.*/)?")
    regex = regex.replace(r"\*\*", r".*")
    regex = regex.replace(r"\*", r"[^/]*")
    regex = regex.replace(r"\?", r"[^/]")
    if re.fullmatch(regex, normalized_path):
        return True
    return False


def _exact_symbol_hits(hits: list[SymbolRecord], query: str) -> list[SymbolRecord]:
    normalized_query = query.strip()
    normalized_query_lower = normalized_query.lower()
    case_sensitive = [
        hit for hit in hits if hit.symbol_name == normalized_query or hit.qualified_name == normalized_query
    ]
    if case_sensitive:
        return case_sensitive
    return [
        hit
        for hit in hits
        if hit.symbol_name.lower() == normalized_query_lower or hit.qualified_name.lower() == normalized_query_lower
    ]


# A query is "symbol-like" when it is a bare identifier or dotted path (no
# spaces) -- the shape worth an explicit exact-name lookup. Multi-word concept
# queries skip that lookup so they never pay an extra search.
_SYMBOL_QUERY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _query_implies_test_scope(query: str) -> bool:
    lowered = query.lower()
    return any(token in lowered for token in ("test", "tests", "spec", "pytest", "unittest"))


def _is_test_file_path(file_path: str) -> bool:
    lowered = file_path.lower()
    name = Path(file_path).name.lower()
    return "/test" in lowered or "/tests/" in lowered or name.startswith("test_") or name.endswith("_test.py")


def _camel_case_match(query: str, symbol_name: str, qualified_name: str) -> bool:
    query_terms = _identifier_terms(query)
    if not query_terms:
        return False
    symbol_terms = _identifier_terms(f"{symbol_name}.{qualified_name}")
    if not symbol_terms:
        return False
    if all(any(term.startswith(query_term) for term in symbol_terms) for query_term in query_terms):
        return True
    initials = "".join(term[0] for term in symbol_terms if term)
    query_compact = "".join(query_terms)
    if not initials or not query_compact:
        return False
    return initials.startswith(query_compact)


def _parse_since_filter(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("since must not be empty")
    match = _SINCE_RELATIVE_RE.fullmatch(normalized.lower())
    if match:
        amount = int(match.group("amount"))
        unit = match.group("unit")
        delta = {
            "d": timedelta(days=amount),
            "w": timedelta(weeks=amount),
            "m": timedelta(days=amount * 30),
            "y": timedelta(days=amount * 365),
        }[unit]
        return int((datetime.now(UTC) - delta).timestamp())
    iso_value = normalized.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("since must be an ISO date/datetime or relative duration like 30d") from exc
        parsed = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _normalize_touched_by(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("touched_by must not be empty")
    return normalized


def _row_to_symbol(row: sqlite3.Row) -> SymbolRecord:
    row_keys = set(row.keys())
    return SymbolRecord(
        symbol_id=str(row["symbol_id"]),
        repo_id=str(row["repo_id"]),
        file_path=str(row["file_path"]),
        language=str(row["language"]),
        symbol_name=str(row["symbol_name"]),
        qualified_name=str(row["qualified_name"]),
        kind=str(row["kind"]),
        signature=str(row["signature"]),
        start_byte=int(row["start_byte"]),
        end_byte=int(row["end_byte"]),
        start_line=int(row["start_line"]),
        end_line=int(row["end_line"]),
        parent_symbol=cast(str | None, row["parent_symbol"]),
        doc_summary=cast(str | None, row["doc_summary"]),
        content_hash=str(row["content_hash"]),
        score=float(row["score"]) if "score" in row_keys and row["score"] is not None else None,
    )


def _git_repo_class() -> Any:
    try:
        from git import Repo
    except Exception:  # pragma: no cover - optional dependency fallback
        logging.exception("Recovered from broad exception handler")
        return None
    return Repo


# Minimum address space (MB) a spawn worker needs to re-import the full package
# (interpreter + tree-sitter grammars + gitpython + glibc arenas, which scale
# with core count). Measured: ~2.5 GB OOMs on import, ~4 GB is safe. RLIMIT_AS
# caps *virtual* address space, which runs well ahead of actual RSS, so the
# per-worker cap must never drop below this floor or workers die on startup.
_WORKER_MIN_MB = 4096


def _available_memory_mb() -> int | None:
    """Best-effort memory we may use, in MB: the lesser of host MemAvailable and
    any cgroup memory ceiling. Returns ``None`` when it can't be determined."""
    candidates: list[int] = []
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    candidates.append(int(line.split()[1]) // 1024)  # kB -> MB
                    break
    except Exception:  # noqa: BLE001  # non-Linux / unreadable -- fall through
        pass
    for cg in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(cg).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw and raw != "max" and raw.isdigit():
            val = int(raw)
            if 0 < val < (1 << 62):  # cgroup v1 uses a huge sentinel for "unlimited"
                candidates.append(val // (1024 * 1024))
    return min(candidates) if candidates else None


def _resolve_index_max_workers() -> int:
    """Worker count for the indexing ProcessPool.

    Honors ``ATELIER_INDEX_MAX_WORKERS`` first. Otherwise defaults to half the
    CPUs, then caps that by available memory: each spawn worker is a fresh
    interpreter that re-imports the full package (~4 GB of address space), so on
    a memory-constrained host one-per-CPU OOM-kills the pool on import. The pool
    is sized so its total address-space budget stays within ~80% of available
    memory (OS- and cgroup-aware).
    """
    override = os.environ.get("ATELIER_INDEX_MAX_WORKERS", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    cpu_workers = max(1, (os.cpu_count() or 1) // 2)
    avail_mb = _available_memory_mb()
    if avail_mb is None:
        return cpu_workers
    mem_workers = max(1, int(avail_mb * 0.8) // _WORKER_MIN_MB)
    return max(1, min(cpu_workers, mem_workers))


def _resolve_serial_extract_threshold() -> int:
    """File count at/below which indexing extracts serially, in-process.

    A spawned ``ProcessPoolExecutor`` pays a fixed ~1-2s spawn+shutdown cost
    (each worker is a fresh interpreter that re-imports the whole package). For
    small repos that overhead dwarfs the millisecond-scale parsing, so serial
    extraction is faster and produces byte-for-byte identical results. Honors
    ``ATELIER_INDEX_SERIAL_MAX_FILES`` (set to 0 to always use the pool).
    """
    override = os.environ.get("ATELIER_INDEX_SERIAL_MAX_FILES", "").strip()
    if override.isdigit():
        return int(override)
    return 64


# ---------------------------------------------------------------------------
# Shared process pool — one pool for the lifetime of the process so that
# repeated index calls don't each spawn a fresh set of interpreter workers.
# ---------------------------------------------------------------------------

_PROCESS_POOL: concurrent.futures.ProcessPoolExecutor | None = None
_PROCESS_POOL_LOCK = threading.Lock()


def _worker_memory_guard() -> None:
    """Worker-process initializer: cap virtual address space to prevent runaway OOM.

    The cap is this worker's share of ~80% of available memory (OS- and
    cgroup-aware), never below the per-worker import floor (``_WORKER_MIN_MB``) --
    so a worker can't false-OOM just re-importing the package, while a
    pathological parse still can't grow it unbounded. Override with
    ``ATELIER_INDEX_WORKER_MAX_MEM_MB`` (0 disables); skipped silently where
    ``resource`` / memory detection is unavailable.
    """
    try:
        import resource as _resource

        override = os.environ.get("ATELIER_INDEX_WORKER_MAX_MEM_MB", "").strip()
        if override.lstrip("-").isdigit():
            mb = int(override)
        else:
            avail_mb = _available_memory_mb()
            if avail_mb is None:
                return  # can't size safely -> don't cap (a too-low RLIMIT_AS OOMs on import)
            mb = max(_WORKER_MIN_MB, int(avail_mb * 0.8) // _resolve_index_max_workers())
        if mb <= 0:
            return
        limit = mb * 1024 * 1024
        _resource.setrlimit(_resource.RLIMIT_AS, (limit, limit))
    except Exception:  # noqa: BLE001 — non-POSIX or resource unavailable, skip silently
        pass


def _get_index_process_pool() -> concurrent.futures.ProcessPoolExecutor:
    """Return the shared ProcessPoolExecutor, creating it lazily on first use."""
    global _PROCESS_POOL
    if _PROCESS_POOL is not None:
        return _PROCESS_POOL
    with _PROCESS_POOL_LOCK:
        if _PROCESS_POOL is None:
            mp_ctx = multiprocessing.get_context("spawn")
            _PROCESS_POOL = concurrent.futures.ProcessPoolExecutor(
                max_workers=_resolve_index_max_workers(),
                mp_context=mp_ctx,
                # Recycle each worker after N tasks so accumulated garbage
                # (AST nodes, interned strings, module caches) is freed by
                # the OS rather than growing indefinitely.
                max_tasks_per_child=256,
                initializer=_worker_memory_guard,
            )
            atexit.register(_shutdown_index_process_pool)
    return _PROCESS_POOL


def _reset_index_process_pool() -> None:
    """Tear down a broken pool so the next call recreates it."""
    global _PROCESS_POOL
    with _PROCESS_POOL_LOCK:
        if _PROCESS_POOL is not None:
            _PROCESS_POOL.shutdown(wait=False, cancel_futures=True)
            _PROCESS_POOL = None


def _shutdown_index_process_pool() -> None:  # atexit handler
    global _PROCESS_POOL
    if _PROCESS_POOL is not None:
        _PROCESS_POOL.shutdown(wait=False, cancel_futures=True)
        _PROCESS_POOL = None


def _process_one_file(
    repo_root_str: str,
    path_str: str,
    source_bytes: bytes | None = None,
) -> _FileIndexData | None:
    """Worker entry-point for ``ProcessPoolExecutor`` — pure extraction, no DB.

    Standalone module-level function (pickleable) that does all the extraction
    work for a single file in a subprocess.
    """
    repo_root = Path(repo_root_str)
    path = Path(path_str)

    try:
        st = path.stat()
    except OSError:
        return None
    if st.st_size > _MAX_FILE_BYTES:
        return None

    payload = source_bytes if source_bytes is not None else path.read_bytes()
    source = payload.decode("utf-8", errors="replace")
    language = detect_language(path) or "text"
    rel = _safe_relpath(repo_root, path)
    content_hash = _sha256_bytes(payload)

    # ---- pre-parse AST for Python (parsed once, reused below) ----
    py_tree: ast.Module | None = None
    if language == "python":
        try:
            py_tree = ast.parse(source)
        except SyntaxError:
            py_tree = None

    # ---- extract symbols ----
    tag_list: list[Tag] = []
    if language == "python":
        if py_tree is not None:
            extracted = _extract_python_symbols(source, tree=py_tree)
        else:
            extracted = []
    elif language == "markdown":
        from atelier.infra.code_intel.markdown import extract_markdown_symbols

        extracted = [_ExtractedSymbol(**s) for s in extract_markdown_symbols(source)]
    else:
        try:
            tag_list = extract_tags(path)
        except (OSError, SyntaxError):
            tag_list = []
        extracted = _extract_tag_symbols_worker(path, source, language, tags=tag_list)

    # Pre-read symbol source slices for FTS5 (avoids re-reading during write)
    symbol_sources: list[str] = []
    for sym in extracted:
        s = payload[sym.start_byte : sym.end_byte].decode("utf-8", errors="replace")
        symbol_sources.append(s[:20_000])

    # ---- extract imports ----
    imports_list: list[tuple[str, str | None]] = []
    if language == "python":
        if py_tree is not None:
            imports_list.extend(_python_imports_worker(repo_root, path, source, tree=py_tree))
    elif language in {"typescript", "javascript"}:
        imports_list.extend(_javascript_imports_worker(repo_root, path, source))
    elif language == "rust":
        for match in _RUST_MOD_RE.finditer(source):
            raw = match.group(1)
            imports_list.append((raw, _resolve_relative_module_worker(repo_root, path.parent, raw, [".rs"])))
    elif language == "go":
        for match in _GO_IMPORT_RE.finditer(source):
            raw_block = match.group(1) or match.group(2) or ""
            for raw in re.findall(r"\"([^\"]+)\"", raw_block) or [raw_block]:
                imports_list.append((raw, None))
    imports_list = sorted(set((raw, target) for raw, target in imports_list if raw and target != rel))

    # ---- extract references / call edges ----
    # Python: rich AST references + call edges. Every other tree-sitter language:
    # reference rows from the same tag parse used for symbols, so query-time
    # find_references is a pure index lookup (no whole-repo re-parse).
    references: list[_IndexedReference] = []
    call_edges: list[_IndexedCallEdge] = []
    if language == "python" and py_tree is not None:
        references, call_edges = _extract_python_reference_index_worker(rel, source, extracted, tree=py_tree)
    elif tag_list:
        references = _extract_tag_reference_index_worker(rel, source, tag_list, extracted)

    return _FileIndexData(
        rel=rel,
        language=language,
        content_hash=content_hash,
        size_bytes=st.st_size,
        text_lines=[(idx, line[:20_000]) for idx, line in enumerate(source.splitlines(), start=1)],
        symbols=extracted,
        symbol_sources=symbol_sources,
        imports=imports_list,
        references=references,
        call_edges=call_edges,
        mtime_ns=st.st_mtime_ns,
    )


def _extract_python_symbols(source: str, tree: ast.Module | None = None) -> list[_ExtractedSymbol]:
    """Extract Python symbols from source (module-level, pickleable).

    If *tree* is provided (pre-parsed AST), it is used instead of parsing *source*.
    """
    if tree is None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
    offsets = _line_offsets(source)
    lines = source.splitlines()
    symbols: list[_ExtractedSymbol] = []

    def line_text(line_no: int) -> str:
        if 1 <= line_no <= len(lines):
            return lines[line_no - 1].strip()
        return ""

    def add_node(node: ast.AST, name: str, kind: str, parent: str | None) -> None:
        start_line = int(getattr(node, "lineno", 1))
        end_line = int(getattr(node, "end_lineno", start_line))
        col = int(getattr(node, "col_offset", 0))
        end_col = int(getattr(node, "end_col_offset", 0))
        start_byte = offsets[max(0, start_line - 1)] + col
        end_byte = offsets[max(0, end_line - 1)] + end_col if end_col else offsets[min(end_line, len(offsets) - 1)]
        qualified = f"{parent}.{name}" if parent else name
        doc = (
            ast.get_docstring(node) if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) else None
        )
        symbols.append(
            _ExtractedSymbol(
                name=name,
                qualified_name=qualified,
                kind=kind,
                signature=line_text(start_line),
                start_byte=start_byte,
                end_byte=max(start_byte, end_byte),
                start_line=start_line,
                end_line=end_line,
                parent_symbol=parent,
                doc_summary=(stripped.splitlines()[0][:200] if doc and (stripped := doc.strip()) else None),
            )
        )

    def walk_body(body: list[ast.stmt], parent: str | None = None) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                add_node(node, node.name, "class", parent)
                walk_body(node.body, node.name if parent is None else f"{parent}.{node.name}")
            elif isinstance(node, ast.AsyncFunctionDef):
                add_node(node, node.name, "method" if parent else "async_function", parent)
            elif isinstance(node, ast.FunctionDef):
                add_node(node, node.name, "method" if parent else "function", parent)
            elif parent is None and isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        add_node(node, target.id, "variable", None)
            elif parent is None and isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                add_node(node, node.target.id, "variable", None)

    walk_body(tree.body)
    return sorted(symbols, key=lambda item: (item.start_line, item.qualified_name))


def _kind_from_signature_worker(signature: str) -> str:
    stripped = signature.lstrip()
    if stripped.startswith("class "):
        return "class"
    if stripped.startswith(("interface ", "type ")):
        return "type"
    if stripped.startswith(("function ", "func ", "fn ")):
        return "function"
    if stripped.startswith(("struct ", "enum ", "trait ")):
        return "class"
    return "variable"


def _extract_tag_symbols_worker(
    path: Path, source: str, language: str, tags: list[Tag] | None = None
) -> list[_ExtractedSymbol]:
    del language
    if tags is None:
        try:
            tags = extract_tags(path)
        except (OSError, SyntaxError):
            return []
    tags = [tag for tag in tags if tag.kind == "definition"]
    offsets = _line_offsets(source)
    lines = source.splitlines()
    sorted_tags = sorted(tags, key=lambda tag: (tag.line, tag.name))
    symbols: list[_ExtractedSymbol] = []
    for index, tag in enumerate(sorted_tags):
        start_line = max(1, tag.line)
        next_line = sorted_tags[index + 1].line - 1 if index + 1 < len(sorted_tags) else start_line
        end_line = max(start_line, min(next_line, len(lines)))
        start_byte = offsets[start_line - 1] if start_line - 1 < len(offsets) else tag.byte_range[0]
        end_byte = offsets[end_line] if end_line < len(offsets) else tag.byte_range[1]
        signature = lines[start_line - 1].strip() if start_line <= len(lines) else tag.name
        symbols.append(
            _ExtractedSymbol(
                name=tag.name,
                qualified_name=tag.name,
                kind=_kind_from_signature_worker(signature),
                signature=signature,
                start_byte=start_byte,
                end_byte=max(start_byte, end_byte),
                start_line=start_line,
                end_line=end_line,
            )
        )
    return symbols


def _extract_tag_reference_index_worker(
    rel: str,
    source: str,
    tags: list[Tag],
    symbols: list[_ExtractedSymbol],
) -> list[_IndexedReference]:
    """Index reference tags for any tree-sitter language.

    Mirrors the Python AST reference worker, reusing the tree-sitter tags already
    parsed for symbol extraction, so query-time find_references is a pure index
    lookup instead of re-parsing the whole repo.
    """
    lines = source.splitlines()

    def containing(line: int) -> _ExtractedSymbol | None:
        candidates = [sym for sym in symbols if sym.start_line <= line <= sym.end_line]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item.end_line - item.start_line, -item.start_line))[0]

    references: list[_IndexedReference] = []
    seen: set[tuple[str, int, int]] = set()
    for tag in tags:
        if tag.kind != "reference":
            continue
        name = tag.name
        line = tag.line
        if line <= 0:
            continue
        line_text = lines[line - 1] if 1 <= line <= len(lines) else ""
        column = max(1, line_text.find(name) + 1) if line_text else 1
        key = (name, line, column)
        if key in seen:
            continue
        seen.add(key)
        enclosing = containing(line)
        references.append(
            _IndexedReference(
                file_path=rel,
                symbol_name=name,
                line=line,
                column=column,
                end_column=column + len(name) - 1,
                enclosing_symbol_name=enclosing.name if enclosing else None,
                enclosing_qualified_name=enclosing.qualified_name if enclosing else None,
                snippet=line_text.strip(),
            )
        )
    return references


def _python_call_name_worker(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _python_call_name_worker(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _python_call_name_worker(node.func)
    return None


def _extract_python_reference_index_worker(
    rel: str,
    source: str,
    symbols: list[_ExtractedSymbol],
    tree: ast.Module | None = None,
) -> tuple[list[_IndexedReference], list[_IndexedCallEdge]]:
    if tree is None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return [], []

    lines = source.splitlines()
    references: list[_IndexedReference] = []
    call_edges: list[_IndexedCallEdge] = []
    seen_refs: set[tuple[str, int, int, str | None]] = set()
    seen_edges: set[tuple[str, int, int, str]] = set()

    def snippet_for(line: int) -> str:
        return lines[line - 1].strip() if 1 <= line <= len(lines) else ""

    def containing_symbol(line: int) -> _ExtractedSymbol | None:
        candidates = [
            sym
            for sym in symbols
            if sym.start_line <= line <= sym.end_line and sym.kind in {"function", "async_function", "method", "class"}
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item.end_line - item.start_line, -item.start_line))[0]

    def add_reference(name: str, node: ast.AST) -> None:
        line = int(getattr(node, "lineno", 0) or 0)
        if line <= 0:
            return
        column = int(getattr(node, "col_offset", 0) or 0) + 1
        end_column = int(getattr(node, "end_col_offset", column + len(name) - 1) or (column + len(name) - 1))
        enclosing = containing_symbol(line)
        key = (name, line, column, enclosing.qualified_name if enclosing else None)
        if key in seen_refs:
            return
        seen_refs.add(key)
        references.append(
            _IndexedReference(
                file_path=rel,
                symbol_name=name,
                line=line,
                column=column,
                end_column=max(column, end_column),
                enclosing_symbol_name=enclosing.name if enclosing else None,
                enclosing_qualified_name=enclosing.qualified_name if enclosing else None,
                snippet=snippet_for(line),
            )
        )

    class _Visitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Load):
                add_reference(node.id, node)
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            add_reference(node.attr, node)
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            callee = _python_call_name_worker(node.func)
            caller = containing_symbol(int(getattr(node, "lineno", 0) or 0))
            if callee and caller is not None:
                line = int(getattr(node, "lineno", caller.start_line) or caller.start_line)
                column = int(getattr(node, "col_offset", 0) or 0) + 1
                edge_key = (caller.qualified_name, line, column, callee)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    call_edges.append(
                        _IndexedCallEdge(
                            caller_symbol_name=caller.name,
                            caller_qualified_name=caller.qualified_name,
                            caller_file_path=rel,
                            caller_start_line=caller.start_line,
                            caller_end_line=caller.end_line,
                            callee_name=callee,
                            call_line=line,
                            call_column=column,
                            snippet=snippet_for(line),
                        )
                    )
            self.generic_visit(node)

    _Visitor().visit(tree)
    return references, call_edges


@cache
def _resolve_python_module_worker(repo_root: Path, base: Path, module: str) -> str | None:
    parts = module.split(".")
    search_bases: list[Path] = []
    for candidate in [base, *base.parents, repo_root, repo_root / "src"]:
        resolved = candidate.resolve()
        if resolved not in search_bases:
            search_bases.append(resolved)
    for search_base in search_bases:
        candidate = search_base / Path(*parts).with_suffix(".py")
        if candidate.is_file():
            return _safe_relpath(repo_root, candidate)
        package = search_base / Path(*parts) / "__init__.py"
        if package.is_file():
            return _safe_relpath(repo_root, package)
        src_candidate = repo_root / "src" / Path(*parts).with_suffix(".py")
        if src_candidate.is_file():
            return _safe_relpath(repo_root, src_candidate)
        src_package = repo_root / "src" / Path(*parts) / "__init__.py"
        if src_package.is_file():
            return _safe_relpath(repo_root, src_package)
    return None


def _resolve_relative_module_worker(repo_root: Path, base: Path, raw: str, suffixes: list[str]) -> str | None:
    candidate_base = (base / raw).resolve()
    candidates: list[Path] = []
    if candidate_base.suffix:
        candidates.append(candidate_base)
    else:
        candidates.extend(candidate_base.with_suffix(suffix) for suffix in suffixes)
        candidates.extend(candidate_base / f"index{suffix}" for suffix in suffixes)
        candidates.extend(candidate_base / f"mod{suffix}" for suffix in suffixes)
    for candidate in candidates:
        if candidate.is_file():
            return _safe_relpath(repo_root, candidate)
    return None


def _python_imports_worker(
    repo_root: Path, path: Path, source: str, tree: ast.Module | None = None
) -> list[tuple[str, str | None]]:
    if tree is None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
    imports: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, _resolve_python_module_worker(repo_root, path.parent, alias.name)))
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.module, _resolve_python_module_worker(repo_root, path.parent, node.module)))
    return imports


def _javascript_imports_worker(repo_root: Path, path: Path, source: str) -> list[tuple[str, str | None]]:
    imports: list[tuple[str, str | None]] = []
    for match in _JS_IMPORT_RE.finditer(source):
        raw = next(group for group in match.groups() if group)
        target = None
        if raw.startswith("."):
            target = _resolve_relative_module_worker(repo_root, path.parent, raw, [".ts", ".tsx", ".js", ".jsx"])
        imports.append((raw, target))
    return imports


class CodeContextEngine:
    """Local code intelligence using tree-sitter tags, SQLite FTS5, rg, and repo-map ranking."""

    def __init__(
        self,
        repo_root: str | Path = ".",
        *,
        db_path: str | Path | None = None,
        autosync_enabled: bool | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.repo_id = _repo_id(self.repo_root)
        self.db_path = Path(db_path).resolve() if db_path is not None else _default_db_path(self.repo_root)
        self._db_lock = _shared_db_lock(self.db_path)
        self._schema_ready = False
        self._cache = RetrievalCache(self.db_path)
        self._budget = BudgetPacker()
        self._semantic_ranker = SemanticSearchRanker(self.repo_root, store_root=default_store_root())
        self._search_reranker = SearchReranker()
        # G4/N5/N16: persistent ANN over per-symbol embeddings. Opt-in via
        # ATELIER_ANN_RETRIEVAL; with the flag off this object is never
        # consulted and the semantic path is byte-identical to today.
        self._ann_symbol_index = SymbolAnnIndex(self.repo_id)
        self.intel_store = SymbolIntelStore(
            cache=self._cache,
            packer=self._budget,
            local_search=self._search_symbols_local,
            local_get_symbol=self._get_symbol_local,
            local_find_references=self._find_references_local,
            local_find_callers=self._find_callers_local,
            local_find_callees=self._find_callees_local,
        )
        self._deleted_history_search_adapter: DeletedHistorySearchAdapter | None = None
        # Autosync disabled for one-shot CLI commands, enabled for services/daemons
        self._autosync_enabled = autosync_enabled if autosync_enabled is not None else True
        self._autosync_debounce_ms = self._parse_autosync_debounce(os.getenv("ATELIER_CODE_AUTOSYNC_DEBOUNCE_MS"))
        self._autosync_poll_ms = self._parse_autosync_poll_ms(os.getenv("ATELIER_CODE_AUTOSYNC_POLL_MS"))
        self._autosync_state = "idle"
        self._autosync_signature: str | None = None
        self._autosync_last_sync_ms = 0
        self._autosync_last_event_at: str | None = None
        self._autosync_pending_events = 0
        self._autosync_reindex_count = 0
        self._autosync_history: list[dict[str, Any]] = []
        self._autosync_lock = threading.RLock()
        self._autosync_stop = threading.Event()
        self._autosync_thread: threading.Thread | None = None
        self._lineage_thread: threading.Thread | None = None
        self._lineage_lock = threading.Lock()
        self._index_ready_cached = False
        # Cache the engine_state index_version so a single tool call (which probes
        # it ~once per sub-query) does not reopen the DB and re-query for a value
        # that only changes on reindex. Invalidated in _bump_index_version.
        self._index_version_cached: int | None = None
        # G6/N16: symbol-level call-graph centrality cache, keyed to the index
        # version so a graph mutation (any reindex bumps index_version) forces a
        # recompute and stale rankings are never served. Guarded by its own lock.
        self._centrality_cache: dict[tuple[int, int], dict[str, Any]] = {}
        self._centrality_cache_lock = threading.Lock()
        self._lineage_rebuild_full = False
        self._lineage_score_penalty: float = float(
            os.getenv("ATELIER_LINEAGE_COMMIT_SCORE_PENALTY", str(_LINEAGE_DEFAULT_SCORE_PENALTY))
        )
        # G7: optional churn provider. When set, it maps a candidate set of
        # symbols to a per-symbol churn score in [0, 1]. It is consulted ONLY as
        # a low-priority ranking tiebreaker (see _context_symbol_rank), never as
        # an override of match quality. It defaults to unset so ranking never
        # incurs git/blame cost in the hot path; callers/tests may inject one.
        self._churn_score_provider: Callable[[list[SymbolRecord]], dict[str, float]] | None = None
        self._register_symbol_intel_providers()
        if self._autosync_enabled:
            self._start_autosync_worker()

    def index_repo(
        self,
        *,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        force: bool = True,
        block: bool = True,
        require_lock: bool = False,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> IndexStats:
        """Build or refresh the persistent symbol/import index for this repository.

        Args:
            include_globs: Glob patterns to include (default source-code patterns).
            exclude_globs: Glob patterns to exclude.
            force: If True (default), wipe and rebuild the full index. Pass
                ``force=False`` for an incremental update (skip unchanged files).
            block: If True (default), wait for the cross-process index-write lock.
                Pass ``block=False`` to skip indexing (returning the current
                snapshot) when another process is already rebuilding.
            require_lock: If True, raise ``IndexLockTimeout`` when the lock cannot
                be acquired instead of silently returning a stale snapshot. Use
                for explicit, must-succeed builds (e.g. the CLI prewarm).
            progress_callback: Optional callback ``fn(current, total)`` called
                after each file is processed during indexing.
        """
        if self._autosync_enabled:
            with self._db_lock, self._autosync_lock:
                with self._index_write_lock(block=block) as acquired:
                    if not acquired:
                        if require_lock:
                            raise IndexLockTimeout(self.db_path)
                        # Another process holds the cross-process index-write lock.
                        # Don't pile on a redundant concurrent rebuild — return the
                        # current on-disk snapshot and let the other writer finish.
                        return self._current_index_stats()
                    return self._index_repo_unsafe(
                        include_globs=include_globs,
                        exclude_globs=exclude_globs,
                        force=force,
                        progress_callback=progress_callback,
                    )
        else:
            # CLI mode: no autosync, skip the autosync lock to avoid contention
            # with background services that have autosync enabled.
            with self._db_lock:
                with self._index_write_lock(block=block) as acquired:
                    if not acquired:
                        if require_lock:
                            raise IndexLockTimeout(self.db_path)
                        return self._current_index_stats()
                    return self._index_repo_unsafe(
                        include_globs=include_globs,
                        exclude_globs=exclude_globs,
                        force=force,
                        progress_callback=progress_callback,
                    )

    @contextlib.contextmanager
    def _index_write_lock(self, *, block: bool) -> Iterator[bool]:
        """Serialize index writes across separate processes sharing this DB.

        ``_db_lock`` only guards threads inside one process; multiple ``atelier``
        processes (MCP servers, background service, CLI) each hold their own. This
        advisory ``flock`` ensures only one of them rebuilds the index at a time.
        Yields ``True`` when the lock was acquired (always so when ``block`` is
        True) and ``False`` when a non-blocking attempt found another process
        already indexing.
        """
        if fcntl is None:  # pragma: no cover - non-POSIX platforms
            yield True
            return
        lock_path = self.db_path.with_name(self.db_path.name + ".indexlock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        acquired = False
        try:
            if not block:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    acquired = False
            else:
                # Poll with LOCK_NB so we don't block the process forever.
                # Default 10s: if another atelier process holds the lock (e.g. a
                # running MCP server) we skip indexing rather than hang. Override
                # via ATELIER_INDEX_LOCK_TIMEOUT_S for long prewarm builds that
                # must win the lock before serving.
                _LOCK_TIMEOUT = _index_lock_timeout_s()
                _POLL_INTERVAL = 0.5
                deadline = time.monotonic() + _LOCK_TIMEOUT
                logging.info("Waiting for index write lock (another process may be indexing)...")
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        logging.debug("Index write lock acquired")
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            logging.warning(
                                "Index write lock timeout after %.0fs — "
                                "another process is indexing; skipping this run.",
                                _LOCK_TIMEOUT,
                            )
                            break
                        time.sleep(_POLL_INTERVAL)
            yield acquired
        finally:
            if acquired:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _current_index_stats(self) -> IndexStats:
        snapshot = self._index_snapshot()
        return IndexStats(
            repo_id=self.repo_id,
            repo_root=str(self.repo_root),
            db_path=str(self.db_path),
            files_indexed=int(snapshot["files_indexed"]),
            symbols_indexed=int(snapshot["symbols_indexed"]),
            imports_indexed=int(snapshot["imports_indexed"]),
            index_version=self._current_index_version(),
        )

    def _apply_file_data_batch(
        self,
        conn: sqlite3.Connection,
        results: list[_FileIndexData],
    ) -> None:
        """Batch-insert all extracted data using ``executemany`` (single writer)."""
        # --- files ---
        conn.executemany(
            """
            INSERT INTO files(repo_id, file_path, language, content_hash, size_bytes, mtime_ns, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT(repo_id, file_path) DO UPDATE SET
                language = excluded.language,
                content_hash = excluded.content_hash,
                size_bytes = excluded.size_bytes,
                mtime_ns = excluded.mtime_ns,
                indexed_at = excluded.indexed_at
            """,
            [(self.repo_id, d.rel, d.language, d.content_hash, d.size_bytes, d.mtime_ns) for d in results],
        )

        # --- symbols + FTS ---
        symbol_rows: list[
            tuple[
                str,
                str,
                str,
                str,
                str,
                str,
                str,
                str,
                int,
                int,
                int,
                int,
                str | None,
                str | None,
                str,
            ]
        ] = []
        fts_rows: list[tuple[str, str, str, str, str, str]] = []
        for d in results:
            for i, sym in enumerate(d.symbols):
                raw_id = f"{self.repo_id}:{d.rel}:{sym.qualified_name}:{sym.start_byte}:{d.content_hash}"
                sid = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24]
                symbol_rows.append(
                    (
                        sid,
                        self.repo_id,
                        d.rel,
                        d.language,
                        sym.name,
                        sym.qualified_name,
                        sym.kind,
                        sym.signature,
                        sym.start_byte,
                        sym.end_byte,
                        sym.start_line,
                        sym.end_line,
                        sym.parent_symbol,
                        sym.doc_summary,
                        d.content_hash,
                    )
                )
                fts_rows.append((sid, sym.name, sym.qualified_name, sym.signature, d.rel, d.symbol_sources[i]))

        conn.executemany(
            """
            INSERT OR IGNORE INTO symbols(
                symbol_id, repo_id, file_path, language, symbol_name, qualified_name, kind,
                signature, start_byte, end_byte, start_line, end_line, parent_symbol,
                doc_summary, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            symbol_rows,
        )
        conn.executemany(
            "INSERT INTO symbol_fts(symbol_id, name, qualified_name, signature, file_path, source) VALUES (?, ?, ?, ?, ?, ?)",
            fts_rows,
        )

        # --- line text + FTS ---
        line_rows: list[tuple[str, str, int, str]] = []
        for d in results:
            line_rows.extend((self.repo_id, d.rel, line_no, text) for line_no, text in d.text_lines if text.strip())
        conn.executemany(
            "INSERT INTO file_line_fts(repo_id, file_path, line, text) VALUES (?, ?, ?, ?)",
            line_rows,
        )

        # --- imports ---
        rows: list[tuple[str, str, str, str | None]] = []
        for d in results:
            rows.extend((self.repo_id, d.rel, raw, target) for raw, target in d.imports)
        conn.executemany(
            "INSERT OR IGNORE INTO imports(repo_id, source_file, raw_import, target_file) VALUES (?, ?, ?, ?)",
            rows,
        )

        # --- references ---
        ref_rows: list[tuple[str, str, str, int, int, int, str | None, str | None, str]] = []
        for d in results:
            ref_rows.extend(
                (
                    self.repo_id,
                    r.symbol_name,
                    r.file_path,
                    r.line,
                    r.column,
                    r.end_column,
                    r.enclosing_symbol_name,
                    r.enclosing_qualified_name,
                    r.snippet,
                )
                for r in d.references
            )
        conn.executemany(
            """INSERT OR IGNORE INTO "references"(
                repo_id, symbol_name, file_path, line, column, end_column,
                enclosing_symbol_name, enclosing_qualified_name, snippet
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ref_rows,
        )

        # --- call_edges ---
        edge_rows: list[tuple[str, str, str, str, int, int, str, int, int, str]] = []
        for d in results:
            edge_rows.extend(
                (
                    self.repo_id,
                    e.caller_symbol_name,
                    e.caller_qualified_name,
                    e.caller_file_path,
                    e.caller_start_line,
                    e.caller_end_line,
                    e.callee_name,
                    e.call_line,
                    e.call_column,
                    e.snippet,
                )
                for e in d.call_edges
            )
        conn.executemany(
            """INSERT OR IGNORE INTO call_edges(
                repo_id, caller_symbol_name, caller_qualified_name, caller_file_path,
                caller_start_line, caller_end_line, callee_name, call_line, call_column, snippet
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            edge_rows,
        )

    def _parallel_extract(
        self,
        files: list[Path],
        *,
        total: int = 0,
        progress_callback: Callable[[int, int], None] | None = None,
        source_bytes_map: dict[str, bytes] | None = None,
    ) -> list[_FileIndexData]:
        """Extract index data from *files* using ``ProcessPoolExecutor``.

        Each file is processed in a subprocess (true CPU parallelism).
        Results are sorted deterministically by relative path.
        *total* is the denominator for *progress_callback* (defaults to ``len(files)``).
        """
        max_workers = _resolve_index_max_workers()
        total_count = total or len(files)

        # Build argument tuples for the pickleable worker function
        args_list: list[tuple[str, str, bytes | None]] = []
        for path in files:
            sb = source_bytes_map.get(str(path)) if source_bytes_map else None
            args_list.append((str(self.repo_root), str(path), sb))

        # Small repos: skip the ProcessPoolExecutor entirely. Spawning fresh
        # interpreters (each re-imports the whole package) and joining the pool
        # costs a fixed ~1-2s that dwarfs the millisecond-scale parsing of a
        # handful of files. Serial in-process extraction is byte-for-byte
        # identical, just without the process churn.
        if max_workers <= 1 or len(args_list) <= _resolve_serial_extract_threshold():
            serial_results: list[_FileIndexData] = []
            for completed, args in enumerate(args_list, start=1):
                data = _process_one_file(*args)
                if data is not None:
                    serial_results.append(data)
                if progress_callback is not None:
                    progress_callback(completed, total_count)
            serial_results.sort(key=lambda r: r.rel)
            return serial_results

        # Use the shared pool (spawn context, single instance per process).
        # Workers never inherit this process's locks or open fds.
        # Chunked submission: keep at most (max_workers x 4) futures in flight
        # so input pickles and result objects don't all accumulate in the parent
        # at once — important when source_bytes_map is provided.
        # On BrokenProcessPool (worker crash/OOM), reset and retry once.
        results: list[_FileIndexData] = []
        for attempt in range(2):
            executor = _get_index_process_pool()
            try:
                backlog = max(8, max_workers * 4)
                args_iter = iter(args_list)
                pending: dict[concurrent.futures.Future[_FileIndexData | None], None] = {}
                completed_count = 0

                for args in itertools.islice(args_iter, backlog):
                    pending[executor.submit(_process_one_file, *args)] = None

                while pending:
                    done, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        del pending[future]
                        data = future.result()
                        if data is not None:
                            results.append(data)
                        completed_count += 1
                        if progress_callback is not None:
                            progress_callback(completed_count, total_count)
                        next_args = next(args_iter, None)
                        if next_args is not None:
                            pending[executor.submit(_process_one_file, *next_args)] = None
                break  # success
            except concurrent.futures.process.BrokenProcessPool:
                logging.warning("Index process pool broken — resetting (attempt %d/2)", attempt + 1)
                _reset_index_process_pool()
                results.clear()
                if attempt == 1:
                    raise

        results.sort(key=lambda r: r.rel)
        return results

    def _index_repo_unsafe(
        self,
        *,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        force: bool = True,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> IndexStats:
        """Unlocked inner — callers must hold ``self._autosync_lock``."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        all_files = [
            path
            for path in iter_source_files(
                self.repo_root, include_globs=include_globs, progress_callback=progress_callback
            )
            if not self._excluded(path, exclude_globs or [])
        ]
        total = len(all_files)
        if progress_callback is not None:
            progress_callback(0, total)  # Signal: discovery done, real total known

        with self._connect() as conn:
            self._init_schema(conn)

            if force:
                # --- Full rebuild: wipe everything, then parallel-extract + batch-write ---
                conn.execute("DELETE FROM file_line_fts")
                conn.execute("DELETE FROM symbol_fts")
                conn.execute("DELETE FROM symbols")
                conn.execute("DELETE FROM imports")
                conn.execute('DELETE FROM "references"')
                conn.execute("DELETE FROM call_edges")
                conn.execute("DELETE FROM files")

                results = self._parallel_extract(all_files, total=total, progress_callback=progress_callback)
                self._apply_file_data_batch(conn, results)

                index_version = self._bump_index_version(conn)
                files_indexed = len(results)
                symbols_indexed = sum(len(r.symbols) for r in results)
                imports_indexed = sum(len(r.imports) for r in results)

            else:
                # --- Incremental: detect changes, then parallel-extract + batch-write ---
                existing = {}
                for row in conn.execute(
                    "SELECT file_path, content_hash, size_bytes, mtime_ns FROM files WHERE repo_id = ?",
                    (self.repo_id,),
                ):
                    existing[str(row["file_path"])] = (
                        str(row["content_hash"]),
                        int(row["size_bytes"]),
                        int(row["mtime_ns"] or 0),
                    )
                line_index_empty = (
                    conn.execute("SELECT 1 FROM file_line_fts WHERE repo_id = ? LIMIT 1", (self.repo_id,)).fetchone()
                    is None
                )

                to_extract: list[tuple[Path, bytes]] = []  # (path, source_bytes)
                current_paths: set[str] = set()

                for path in all_files:
                    rel = _safe_relpath(self.repo_root, path)
                    current_paths.add(rel)
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    if stat.st_size > _MAX_FILE_BYTES:
                        if rel in existing:
                            self._delete_file_index(conn, rel)
                        continue
                    previous = existing.get(rel)
                    # Fast path: a file whose (size, mtime) matches the indexed row
                    # is already current -- skip the read + sha256 entirely. This
                    # keeps the background incremental resync cheap on large repos
                    # instead of O(repo bytes) on every poll.
                    if (
                        previous is not None
                        and not line_index_empty
                        and previous[1] == int(stat.st_size)
                        and previous[2] == int(stat.st_mtime_ns)
                        and previous[2] != 0
                    ):
                        continue
                    source_bytes = path.read_bytes()
                    content_hash = _sha256_bytes(source_bytes)
                    if (
                        previous is not None
                        and not line_index_empty
                        and previous[0] == content_hash
                        and previous[1] == int(stat.st_size)
                    ):
                        # Content identical (e.g. a touch changed only mtime).
                        # Refresh the stored mtime so the next pass fast-skips,
                        # then move on without re-extracting.
                        conn.execute(
                            "UPDATE files SET mtime_ns = ? WHERE repo_id = ? AND file_path = ?",
                            (int(stat.st_mtime_ns), self.repo_id, rel),
                        )
                        continue
                    self._delete_file_index(conn, rel)
                    to_extract.append((path, source_bytes))

                removed_paths = set(existing.keys()) - current_paths
                for rel in sorted(removed_paths):
                    self._delete_file_index(conn, rel)

                if to_extract:
                    paths = [item[0] for item in to_extract]
                    source_map = {str(p): b for p, b in to_extract}
                    results = self._parallel_extract(
                        paths,
                        total=total,
                        progress_callback=progress_callback,
                        source_bytes_map=source_map,
                    )
                    self._apply_file_data_batch(conn, results)
                else:
                    results = []

                if to_extract or removed_paths:
                    index_version = self._bump_index_version(conn)
                else:
                    row = conn.execute("SELECT value FROM engine_state WHERE key = 'index_version'").fetchone()
                    index_version = int(row["value"]) if row is not None else 0

                files_indexed = len(to_extract)
                symbols_indexed = sum(len(r.symbols) for r in results)
                imports_indexed = sum(len(r.imports) for r in results)

        emit_product_local(
            "code_index_completed",
            repo_id=self.repo_id,
            files_indexed=files_indexed,
            symbols_indexed=symbols_indexed,
        )
        return IndexStats(
            repo_id=self.repo_id,
            repo_root=str(self.repo_root),
            db_path=str(self.db_path),
            files_indexed=files_indexed,
            symbols_indexed=symbols_indexed,
            imports_indexed=imports_indexed,
            index_version=index_version,
        )

    def _delete_file_index(self, conn: sqlite3.Connection, rel: str) -> None:
        conn.execute("DELETE FROM file_line_fts WHERE repo_id = ? AND file_path = ?", (self.repo_id, rel))
        conn.execute(
            """
            DELETE FROM symbol_fts
            WHERE symbol_id IN (
                SELECT symbol_id FROM symbols WHERE repo_id = ? AND file_path = ?
            )
            """,
            (self.repo_id, rel),
        )
        conn.execute("DELETE FROM symbols WHERE repo_id = ? AND file_path = ?", (self.repo_id, rel))
        conn.execute("DELETE FROM imports WHERE repo_id = ? AND source_file = ?", (self.repo_id, rel))
        conn.execute('DELETE FROM "references" WHERE repo_id = ? AND file_path = ?', (self.repo_id, rel))
        conn.execute("DELETE FROM call_edges WHERE repo_id = ? AND caller_file_path = ?", (self.repo_id, rel))
        conn.execute("DELETE FROM files WHERE repo_id = ? AND file_path = ?", (self.repo_id, rel))

    def tool_index(
        self,
        *,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        force: bool = False,  # incremental by default; pass force=True to full-rebuild
        budget_tokens: int = 4000,
    ) -> dict[str, Any]:
        effective_budget_tokens = self._effective_budget_tokens("index", budget_tokens)
        self._sync_symbol_intel()
        stats = self.index_repo(include_globs=include_globs, exclude_globs=exclude_globs, force=force)
        stats_payload = stats.model_dump(mode="json")
        snapshot = self._index_snapshot()
        return self._pack_single_payload(
            {
                "repo_id": stats_payload["repo_id"],
                "index_version": stats_payload["index_version"],
                "files_indexed": snapshot["files_indexed"],
                "symbols_indexed": snapshot["symbols_indexed"],
                "imports_indexed": snapshot["imports_indexed"],
                "provenance": _LOCAL_PROVENANCE,
            },
            budget_tokens=effective_budget_tokens,
            essential_keys=_INDEX_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=[],
        )

    def tool_search(
        self,
        query: str,
        *,
        limit: int = 20,
        mode: SearchMode = "auto",
        intent: Literal["auto", "symbol", "text", "semantic"] = "auto",
        kind: str | None = None,
        language: str | None = None,
        seed_files: list[str] | None = None,
        snippet: Literal["none", "head", "full"] = "none",
        snippet_lines: int = 8,
        file_glob: str | None = None,
        scope: Literal["repo", "external", "deleted"] = "repo",
        since: str | None = None,
        touched_by: str | None = None,
        budget_tokens: int = 4000,
        auto_index: bool = True,
        provenance_filter: str | None = None,
    ) -> dict[str, Any]:
        force_compact_snippet = self._should_force_search_compaction(scope=scope, snippet=snippet, limit=limit)
        effective_snippet: Literal["none", "head", "full"] = "none" if force_compact_snippet else snippet
        effective_snippet_lines = 0 if effective_snippet == "none" else max(1, int(snippet_lines))
        apply_search_cap = scope == "repo" and snippet == "none"
        effective_budget_tokens = (
            self._effective_budget_tokens("search", budget_tokens) if apply_search_cap else max(1, int(budget_tokens))
        )
        if auto_index and scope != "deleted":
            self._ensure_indexed()
        self._sync_symbol_intel()
        resolved_mode = "semantic" if intent == "semantic" else resolve_search_mode(query, mode)
        if resolved_mode in {"semantic", "hybrid"} and not self._semantic_ranker.available:
            # Semantic search requires a configured embedding backend. By default none
            # is set (no external LLM is contacted). If the caller explicitly asked for
            # semantic/hybrid, say so; for an auto-resolved query fall back to lexical.
            if intent == "semantic" or mode in {"semantic", "hybrid"}:
                return {
                    "items": [],
                    "mode": resolved_mode,
                    "semantic_available": False,
                    "provenance": _LOCAL_PROVENANCE,
                    "cache_hit": False,
                    "message": (
                        "Semantic search is not configured. Set ATELIER_CODE_EMBEDDER "
                        "(local|openai|letta|ollama) and optionally ATELIER_CODE_EMBED_MODEL to enable it."
                    ),
                }
            resolved_mode = "lexical"
        use_text_substring = intent == "text" or (
            intent == "auto"
            and self._should_use_text_substring_search(
                query,
                mode=resolved_mode,
                scope=scope,
                kind=kind,
                language=language,
                file_glob=file_glob,
                provenance_filter=provenance_filter,
            )
        )
        temporal_scope = scope in {"repo", "deleted"}
        parsed_since = _parse_since_filter(since) if temporal_scope else None
        normalized_touched_by = _normalize_touched_by(touched_by) if temporal_scope else None
        normalized_seed_files = [self._normalize_file_arg(seed) for seed in seed_files or []]
        rerank_limit = self._search_reranker.pre_rerank_limit(limit, mode=resolved_mode, scope=scope)
        cache_args = {
            "query": query,
            "limit": limit,
            "mode": mode,
            "intent": intent,
            "resolved_mode": resolved_mode,
            "kind": kind,
            "language": language,
            "seed_files": normalized_seed_files,
            "snippet": snippet,
            "effective_snippet": effective_snippet,
            "snippet_lines": effective_snippet_lines,
            "file_glob": file_glob,
            "scope": scope,
            "since_ts": parsed_since,
            "touched_by": normalized_touched_by,
            "budget_tokens": effective_budget_tokens,
            "semantic_candidate_limit": semantic_candidate_limit(rerank_limit),
            "rerank_limit": rerank_limit,
            "rerank": self._search_reranker.cache_fingerprint(mode=resolved_mode, scope=scope),
            "provenance_filter": provenance_filter,
            "use_text_substring": use_text_substring,
        }
        hit, cached = self._cache_get("code.search", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)

        if use_text_substring:
            text_payload = self._tool_text_substring_search(
                query,
                limit=limit,
                file_glob=file_glob,
                budget_tokens=effective_budget_tokens,
                since_ts=parsed_since,
                touched_by=normalized_touched_by,
            )
            self._cache_set("code.search", cache_args, text_payload)
            return text_payload

        if scope == "deleted":
            raw_deleted_items = self.search_symbols(
                query,
                limit=limit,
                mode=resolved_mode,
                kind=kind,
                language=language,
                snippet=effective_snippet,
                snippet_lines=effective_snippet_lines,
                file_glob=file_glob,
                scope="deleted",
                since=since,
                touched_by=touched_by,
                auto_index=False,
            )
            items = [dict(item) for item in raw_deleted_items]
        else:
            raw_items = self.search_symbols(
                query,
                limit=limit,
                mode=resolved_mode,
                kind=kind,
                language=language,
                snippet=effective_snippet,
                snippet_lines=effective_snippet_lines,
                file_glob=file_glob,
                scope=scope,
                since=since,
                touched_by=touched_by,
                auto_index=False,
                provenance_filter=provenance_filter,
            )
            items = [item.model_dump(mode="json", exclude_none=True) for item in raw_items]
        if scope == "repo" and (parsed_since is not None or normalized_touched_by is not None):
            changed_files = self._deleted_history_adapter().changed_files(
                since_ts=parsed_since,
                touched_by=normalized_touched_by,
            )
            items = [item for item in items if str(item.get("file_path") or "") in changed_files]
        items = self._dedupe_search_items(items)
        items = self._prioritize_grounded_search_items(items, seed_files=normalized_seed_files)
        # Capture aggregate provenance before compaction strips per-item provenance
        # (repo-scope compaction drops "provenance"/"symbol_id" as redundant with the
        # top-level fields), so the routed-provider provenance survives in the payload.
        aggregate_provenance = self._items_provenance(items)
        if effective_snippet == "none":
            items = self._compact_search_items(items, scope=scope)
        essential_keys = _DELETED_SEARCH_ESSENTIAL_KEYS if scope == "deleted" else _SEARCH_ESSENTIAL_KEYS
        optional_keys = _DELETED_SEARCH_OPTIONAL_KEYS if scope == "deleted" else _SEARCH_OPTIONAL_KEYS
        payload = self._pack_items_payload(
            items,
            budget_tokens=effective_budget_tokens,
            essential_keys=essential_keys,
            optional_keys_in_drop_order=optional_keys,
            extra_payload={
                "mode": resolved_mode,
                "snippet": effective_snippet,
                "provenance": aggregate_provenance,
            },
        )
        self._cache_set("code.search", cache_args, payload)
        return payload

    def search_channel_health(self, query: str, mode: str = "auto") -> ChannelHealth:
        """Liveness of optional retrieval channels for a query (verdict stamping).

        Lets the MCP boundary distinguish a *trustworthy* empty (every channel the
        query wanted actually ran) from a *dark* one (a wanted channel was off):

        - ``semantic``: applicable only when the resolved mode wants it
          (semantic/hybrid); ``True`` if an embedder is configured, ``False``
          (dark) if not, ``None`` if the query never wanted it (lexical lookup).
        - ``zoekt``: applicable for repo-scope lexical/hybrid; ``False`` (dark)
          only when it is meant to route but the backend is unhealthy. A
          config-disabled zoekt is ``None`` (not dark) -- FTS, always live,
          covers the lexical channel.
        """
        from atelier.core.capabilities.code_context.search_verdict import ChannelHealth

        requested = cast("SearchMode", mode if mode in ("auto", "lexical", "semantic", "hybrid") else "auto")
        resolved = resolve_search_mode(query, requested)
        semantic: bool | None = None
        if resolved in {"semantic", "hybrid"}:
            semantic = bool(self._semantic_ranker.available)
        zoekt: bool | None = None
        if resolved != "semantic":
            with contextlib.suppress(Exception):
                from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

                supervisor = get_zoekt_supervisor(self.repo_root)
                if supervisor.should_route(self.repo_root):
                    zoekt = bool(supervisor.health().ok)
        return ChannelHealth(semantic=semantic, zoekt=zoekt)

    def tool_blame(
        self,
        *,
        query: str | None = None,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        symbol_name: str | None = None,
        file_path: str | None = None,
        include_churn: bool = True,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        target = self._resolve_symbol_target(
            operation_name="blame",
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=file_path,
            kind=None,
            language=None,
            file_glob=None,
        )
        if target.get("error"):
            return self._pack_single_payload(
                target,
                budget_tokens=budget_tokens,
                essential_keys=["error", "message", "matches", "cache_hit", "provenance"],
                optional_keys_in_drop_order=["provenance_breakdown"],
            )
        head_sha = self._current_head_sha()
        index_sha = str(target.get("index_sha") or head_sha)
        normalized_file_path = str(target["file_path"])
        cache_args = {
            "query": query,
            "symbol_id": symbol_id or target.get("symbol_id"),
            "qualified_name": qualified_name or target.get("qualified_name"),
            "symbol_name": symbol_name or target.get("symbol_name"),
            "file_path": normalized_file_path,
            "include_churn": include_churn,
            "index_sha": index_sha,
            "head_sha": head_sha,
            "budget_tokens": budget_tokens,
        }
        hit, cached = self._cache_get("code.blame", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)
        if index_sha != head_sha:
            payload = self._pack_single_payload(
                {
                    "error": "index_stale",
                    "hint": 'run code op="index" first',
                    "symbol_name": str(target["symbol_name"]),
                    "qualified_name": str(target["qualified_name"]),
                    "file_path": normalized_file_path,
                    "freshness": "stale",
                    "index_sha": index_sha,
                    "head_sha": head_sha,
                    "provenance": "blame",
                },
                budget_tokens=budget_tokens,
                essential_keys=[
                    "error",
                    "hint",
                    "symbol_name",
                    "qualified_name",
                    "file_path",
                    "freshness",
                    "provenance",
                ],
                optional_keys_in_drop_order=["index_sha", "head_sha"],
            )
            self._cache_set("code.blame", cache_args, payload)
            return payload
        from atelier.infra.code_intel.git_history.blame import BlameAnnotator
        from atelier.infra.code_intel.git_history.models import BlameRequest

        try:
            annotation = BlameAnnotator(self.repo_root).annotate(
                BlameRequest(
                    file_path=normalized_file_path,
                    line_start=int(target["start_line"]),
                    line_end=int(target["end_line"]),
                    index_sha=index_sha,
                    head_sha=head_sha,
                    include_churn=include_churn,
                )
            )
        except ValueError:
            # The symbol's recorded line span does not map onto a committed HEAD
            # blob (uncommitted/working-tree region or a dirty re-index). Return a
            # structured payload instead of crashing the MCP handler with -32603.
            payload = self._pack_single_payload(
                {
                    "error": "blame_unavailable",
                    "hint": "symbol range is not yet committed; commit then re-index",
                    "symbol_name": str(target["symbol_name"]),
                    "qualified_name": str(target["qualified_name"]),
                    "file_path": normalized_file_path,
                    "line_start": int(target["start_line"]),
                    "line_end": int(target["end_line"]),
                    "provenance": "blame",
                },
                budget_tokens=budget_tokens,
                essential_keys=[
                    "error",
                    "hint",
                    "symbol_name",
                    "qualified_name",
                    "file_path",
                    "provenance",
                ],
                optional_keys_in_drop_order=["line_start", "line_end"],
            )
            self._cache_set("code.blame", cache_args, payload)
            return payload
        latest_commit_ts = max(hunk.commit_time for hunk in annotation.hunks)
        payload_data: dict[str, Any] = {
            "symbol_name": str(target["symbol_name"]),
            "qualified_name": str(target["qualified_name"]),
            "file_path": normalized_file_path,
            "line_start": int(target["start_line"]),
            "line_end": int(target["end_line"]),
            "index_sha": index_sha,
            "head_sha": head_sha,
            "freshness": annotation.freshness,
            "last_modified": datetime.fromtimestamp(latest_commit_ts, tz=UTC).isoformat().replace("+00:00", "Z"),
            "last_author": annotation.last_author,
            "last_commit_sha": annotation.last_commit_sha,
            "last_commit_summary": annotation.last_commit_summary,
            "age_days": annotation.age_days,
            "local_edits": annotation.local_edits,
            "distinct_authors": len({hunk.author_email for hunk in annotation.hunks if hunk.author_email}),
            "hunks": [asdict(hunk) for hunk in annotation.hunks],
            "provenance": "blame",
        }
        if annotation.churn is not None:
            payload_data["churn"] = asdict(annotation.churn)
        payload = self._pack_single_payload(
            payload_data,
            budget_tokens=budget_tokens,
            essential_keys=_BLAME_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=_BLAME_OPTIONAL_KEYS,
        )
        self._cache_set("code.blame", cache_args, payload)
        return payload

    def _symbol_at_line(self, file_path: str, line: int) -> dict[str, Any]:
        """Resolve the innermost symbol whose span contains `line` in `file_path`."""
        normalized = self._normalize_file_arg(file_path)
        with self._connect() as conn:
            self._init_schema(conn)
            row = conn.execute(
                """
                SELECT *, NULL AS score FROM symbols
                WHERE repo_id = ? AND file_path = ? AND start_line <= ? AND end_line >= ?
                ORDER BY start_line DESC
                LIMIT 1
                """,
                (self.repo_id, normalized, line, line),
            ).fetchone()
        if row is None:
            raise LookupError("no symbol at that position")
        symbol_rec = _row_to_symbol(row)
        path = self.repo_root / symbol_rec.file_path
        source = path.read_bytes()[symbol_rec.start_byte : symbol_rec.end_byte].decode("utf-8", errors="replace")
        return {**symbol_rec.model_dump(mode="json"), "source": source}

    def tool_symbol(
        self,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        file_path: str | None = None,
        symbol_name: str | None = None,
        line: int | None = None,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        effective_budget_tokens = self._effective_budget_tokens("symbol", budget_tokens)
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        normalized_file_path = self._normalize_file_arg(file_path) if file_path else None
        positional_lookup = (
            file_path is not None and line is not None and not symbol_id and not qualified_name and not symbol_name
        )
        cache_args = {
            "symbol_id": symbol_id,
            "qualified_name": qualified_name,
            "symbol_name": symbol_name,
            "file_path": normalized_file_path,
            "line": line if positional_lookup else None,
            "budget_tokens": effective_budget_tokens,
        }
        hit, cached = self._cache_get("code.symbol", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)

        raw_symbol = (
            self._symbol_at_line(file_path, line)  # type: ignore[arg-type]
            if positional_lookup
            else self.get_symbol(
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                symbol_name=symbol_name,
                file_path=normalized_file_path,
                auto_index=False,
            )
        )
        payload = self._pack_single_payload(
            self._hydrate_symbol_cross_lang(raw_symbol),
            budget_tokens=effective_budget_tokens,
            essential_keys=_SYMBOL_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=_SYMBOL_OPTIONAL_KEYS,
        )
        self._cache_set("code.symbol", cache_args, payload)
        return payload

    def _hydrate_symbol_cross_lang(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol_id = str(payload.get("symbol_id") or "")
        symbol_name = str(payload.get("symbol_name") or "")
        if not symbol_id:
            return payload
        refs: list[CrossLangReference] = []
        for edge in self._cross_lang_store().query_by_source_symbol(symbol_id):
            refs.append(self._symbol_cross_lang_ref(edge, direction="outgoing"))
        for edge in self._cross_lang_store().query_by_target_symbol(
            tgt_symbol_id=symbol_id, tgt_symbol_name=symbol_name
        ):
            refs.append(self._symbol_cross_lang_ref(edge, direction="incoming"))
        if not refs:
            return payload
        deduped = list(
            {
                (
                    ref.direction,
                    ref.symbol_id,
                    ref.symbol_name,
                    ref.file_path,
                    ref.line,
                    ref.edge_kind,
                ): ref
                for ref in refs
            }.values()
        )
        deduped.sort(
            key=lambda ref: (
                ref.direction,
                ref.file_path,
                int(ref.line or 0),
                ref.symbol_name,
                ref.symbol_id,
                ref.edge_kind,
            )
        )
        allowed = {key: value for key, value in payload.items() if key in SymbolRecord.model_fields}
        validated = SymbolRecord.model_validate(
            {
                **allowed,
                "cross_lang_refs": [ref.model_dump(mode="json", exclude_none=True) for ref in deduped],
            }
        ).model_dump(mode="json", exclude_none=True)
        if "source" in payload:
            validated["source"] = payload["source"]
        return validated

    def _symbol_cross_lang_ref(
        self,
        edge: CrossLangEdge,
        *,
        direction: Literal["incoming", "outgoing"],
    ) -> CrossLangReference:
        if direction == "incoming":
            return CrossLangReference(
                symbol_id=edge.src_symbol_id,
                symbol_name=edge.src_symbol_name,
                qualified_name=edge.src_qualified_name,
                language=edge.src_language,
                file_path=edge.src_file_path,
                line=edge.src_line,
                direction=direction,
                edge_kind=edge.edge_kind,
                confidence=edge.confidence,
            )
        return CrossLangReference(
            symbol_id=edge.tgt_symbol_id,
            symbol_name=edge.tgt_symbol_name,
            qualified_name=None,
            language=edge.tgt_language,
            file_path=edge.tgt_file_path,
            line=edge.src_line,
            direction=direction,
            edge_kind=edge.edge_kind,
            confidence=edge.confidence,
        )

    def _cross_lang_store(self) -> CrossLangEdgeStore:
        return CrossLangEdgeStore(self.connection)

    def tool_files(
        self,
        *,
        path: str | None = None,
        pattern: str | None = None,
        format: Literal["tree", "flat", "grouped"] = "tree",
        include_metadata: bool = True,
        max_depth: int | None = None,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        if max_depth is not None and max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        normalized_path = self._normalize_files_path(path)
        normalized_pattern = (pattern or "").strip() or None
        cache_args = {
            "path": normalized_path,
            "pattern": normalized_pattern,
            "format": format,
            "include_metadata": include_metadata,
            "max_depth": max_depth,
            "budget_tokens": budget_tokens,
        }
        hit, cached = self._cache_get("code.files", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)

        items = self._indexed_file_records(path=normalized_path, pattern=normalized_pattern, max_depth=max_depth)
        essential_keys = list(_FILES_ESSENTIAL_KEYS)
        if format == "grouped":
            essential_keys.append("language")
        optional_keys = _FILES_OPTIONAL_KEYS if include_metadata else []
        full_payload = self._build_files_payload(
            items,
            path=normalized_path,
            pattern=normalized_pattern,
            format=format,
            include_metadata=include_metadata,
            truncated=False,
        )
        full_total_tokens = self._compute_total_tokens({**full_payload, "tokens_saved": 0})

        def build_payload(packed_items: list[dict[str, Any]]) -> dict[str, Any]:
            return self._finalize_packed_payload(
                self._build_files_payload(
                    packed_items,
                    path=normalized_path,
                    pattern=normalized_pattern,
                    format=format,
                    include_metadata=include_metadata,
                    truncated=len(packed_items) < len(items),
                ),
                full_total_tokens=full_total_tokens,
            )

        packed = self._fit_items_to_budget(
            items,
            budget_tokens=budget_tokens,
            essential_keys=essential_keys,
            optional_keys_in_drop_order=optional_keys,
            build_payload=build_payload,
        )
        payload = self._maybe_attach_overflow_metadata(
            packed_payload=packed,
            full_payload=full_payload,
            full_total_tokens=full_total_tokens,
            budget_tokens=budget_tokens,
        )
        self._cache_set("code.files", cache_args, payload)
        return payload

    def tool_explore(
        self,
        query: str,
        *,
        seed_files: list[str] | None = None,
        max_files: int = 6,
        max_symbols: int = 20,
        include_source: bool = True,
        include_relationships: bool = True,
        line_numbers: bool = True,
        skeletonize: bool = True,
        complete_families: bool | None = None,
        depth: int = 1,
        budget_tokens: int = 9000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        effective_skeletonize = skeletonize and _explore_skeleton_enabled()
        effective_complete = (
            bool(complete_families if complete_families is not None else skeletonize) and _explore_skeleton_enabled()
        )

        bounded_max_symbols = max(1, min(max_symbols, 30))
        bounded_max_files = max(1, min(max_files, 8))
        bounded_depth = max(1, depth)
        normalized_seeds = [self._normalize_file_arg(seed) for seed in seed_files or []]
        seed_set = set(normalized_seeds)
        cache_args = {
            "query": query,
            "seed_files": normalized_seeds,
            "max_files": bounded_max_files,
            "max_symbols": bounded_max_symbols,
            "include_source": include_source,
            "include_relationships": include_relationships,
            "line_numbers": line_numbers,
            "skeletonize": effective_skeletonize,
            "complete_families": effective_complete,
            "depth": bounded_depth,
            "budget_tokens": budget_tokens,
        }
        hit, cached = self._cache_get("code.explore", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)

        raw_symbols = self.search_symbols(
            query,
            limit=bounded_max_symbols,
            snippet="none",
            auto_index=False,
        )
        # Winner-pipeline fusion: pull in zoekt trigram anchors. The symbol FTS
        # ranks named symbols well but misses concept/regex queries where the
        # right file has no lexically-matching symbol name; zoekt's trigram search
        # surfaces those files, and seeding a couple of their definitions makes the
        # file survive ranking. Additive and graceful (empty set when zoekt is off)
        # -- the exact/score/seed ranking below still governs final order.
        seeded_files = {symbol.file_path for symbol in raw_symbols}
        anchor_files = [
            anchor
            for anchor in sorted(self._zoekt_candidate_files(query, max_files=max(bounded_max_files * 2, 12)))
            if anchor not in seeded_files
        ]
        if anchor_files:
            anchor_symbols = self._cap_symbols_per_file(
                [
                    symbol
                    for symbol in self._symbols_for_files(anchor_files[:bounded_max_files], limit=400)
                    if (symbol.kind or "").lower() in _DEFINITION_KINDS
                ],
                max_per_file=2,
            )
            raw_symbols = self._dedupe_symbols(raw_symbols + anchor_symbols)
        # Exact-name guard: when the query is itself an indexed symbol name,
        # semantic ranking can bury the exact definition behind lexical cousins
        # (e.g. "_pack_single_payload" surfacing "_payload_looks_empty"), or the
        # max_symbols cap can drop it outright. Pin any exact match to the front,
        # fetching it via a lexical lookup if the ranked search missed it. Only
        # symbol-like (single-token) queries pay that extra lookup.
        exact_hits = _exact_symbol_hits(raw_symbols, query)
        if not exact_hits and _SYMBOL_QUERY_RE.match(query.strip()):
            lexical_hits = self.search_symbols(
                query,
                limit=max(bounded_max_symbols, 10),
                mode="lexical",
                snippet="none",
                auto_index=False,
            )
            exact_hits = _exact_symbol_hits(lexical_hits, query)
        exact_ids = {record.symbol_id for record in exact_hits}
        if exact_hits:
            raw_symbols = exact_hits + [record for record in raw_symbols if record.symbol_id not in exact_ids]
        ranked_symbols = sorted(
            raw_symbols,
            key=lambda record: (
                0 if record.file_path in seed_set else 1,
                0 if record.symbol_id in exact_ids else 1,
                -(record.score or 0.0),
                record.file_path,
                record.start_line,
            ),
        )
        # File diversity: cap symbols-per-file before the symbol budget so one
        # over-populated file (e.g. 8 `as_sqlite` overloads in functions.py)
        # cannot starve the other files the query also matches (the ambiguous-name
        # collapse). Exact/seed hits already sort first, so they survive the cap.
        diverse_ranked = self._cap_symbols_per_file(ranked_symbols, max_per_file=3)
        selected_symbols = diverse_ranked[:bounded_max_symbols]
        family_member_ids: set[str] = set()
        if effective_complete:
            additions = self._complete_sibling_families(selected_symbols, query=query, seed_set=seed_set)
            if additions:
                have = {symbol.symbol_id for symbol in selected_symbols}
                fresh = [symbol for symbol in additions if symbol.symbol_id not in have]
                selected_symbols = selected_symbols + fresh
                family_member_ids = {symbol.symbol_id for symbol in fresh}

        # Rank so the highest-signal symbols claim the files that survive the file
        # and budget caps: seed files, then the query's completed family, then
        # definitions by score, then trivial variables/constants last.
        def _explore_priority(symbol: SymbolRecord) -> int:
            if symbol.symbol_id in exact_ids:
                return -1
            if symbol.file_path in seed_set:
                return 0
            # Direct definition hits must claim files BEFORE sibling-family
            # completions -- otherwise a loose affix (e.g. "select" pulling the
            # whole Select* widget family) hijacks the file slots above the
            # actually-relevant definitions.
            if (symbol.kind or "").lower() in _DEFINITION_KINDS:
                return 1
            if symbol.symbol_id in family_member_ids:
                return 2
            return 3

        selected_symbols = [
            symbol
            for _, symbol in sorted(enumerate(selected_symbols), key=lambda pair: (_explore_priority(pair[1]), pair[0]))
        ]
        selected_files: list[str] = []
        by_file: dict[str, list[SymbolRecord]] = {}
        for symbol in selected_symbols:
            by_file.setdefault(symbol.file_path, []).append(symbol)
            if symbol.file_path not in selected_files:
                selected_files.append(symbol.file_path)
        # Family-completion can add files past the normal cap; allow them since the
        # extra siblings render signatures-only (cheap), but stay bounded.
        file_cap = bounded_max_files
        if family_member_ids:
            file_cap = min(_EXPLORE_FAMILY_FILE_CAP, max(bounded_max_files, len(selected_files)))
        selected_files = selected_files[:file_cap]
        trimmed_symbols = [symbol for symbol in selected_symbols if symbol.file_path in set(selected_files)]
        trimmed_by_file: dict[str, list[SymbolRecord]] = {}
        for symbol in trimmed_symbols:
            trimmed_by_file.setdefault(symbol.file_path, []).append(symbol)

        skeleton_ids: set[str] = set()
        skeleton_families: dict[str, str] = {}
        if effective_skeletonize:
            skeleton_ids, skeleton_families = self._select_skeleton_symbols(trimmed_symbols, seed_set=seed_set)
            # An exact name match is the whole point of the query -- never reduce
            # it to a signature-only skeleton; always show its full body.
            skeleton_ids -= exact_ids
        # Completed family members are supplementary "here's the rest of the family"
        # context, not direct hits -- always render them signatures-only so surfacing
        # a whole family stays cheap and never forces the budget to drop relevant
        # files. The actual search hits still render per the skeletonize flag.
        if family_member_ids:
            for symbol in trimmed_symbols:
                if symbol.symbol_id in family_member_ids and symbol.file_path not in seed_set:
                    skeleton_ids.add(symbol.symbol_id)
                    skeleton_families.setdefault(symbol.symbol_id, "completion")

        entry_points = [
            {
                "symbol_id": symbol.symbol_id,
                "symbol_name": symbol.symbol_name,
                "qualified_name": symbol.qualified_name,
                "file_path": symbol.file_path,
                "kind": symbol.kind,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "score": symbol.score,
                "provenance": symbol.provenance,
            }
            for symbol in trimmed_symbols
        ]

        files_payload: list[dict[str, Any]] = []
        for file_path in selected_files:
            symbols = trimmed_by_file.get(file_path, [])
            file_entry: dict[str, Any] = {
                "file_path": file_path,
                "language": symbols[0].language if symbols else "unknown",
                "symbols": [
                    {
                        "symbol_id": symbol.symbol_id,
                        "symbol_name": symbol.symbol_name,
                        "qualified_name": symbol.qualified_name,
                        "kind": symbol.kind,
                        "start_line": symbol.start_line,
                        "end_line": symbol.end_line,
                        "provenance": symbol.provenance,
                    }
                    for symbol in symbols
                ],
            }
            if include_source:
                sections = [
                    self._source_section_for_symbol(
                        symbol,
                        line_numbers=line_numbers,
                        skeleton=symbol.symbol_id in skeleton_ids,
                    )
                    for symbol in symbols
                ]
                merged_sections = self._merge_nearby_source_sections(sections)
                file_entry["source_sections"] = merged_sections
            files_payload.append(file_entry)

        relationships: dict[str, list[dict[str, Any]]] = {
            "callers": [],
            "callees": [],
            "usages": [],
        }
        if include_relationships:
            for symbol in trimmed_symbols[:3]:
                callers = self._neighborhood(
                    "callers",
                    symbol_id=symbol.symbol_id,
                    depth=bounded_depth,
                    limit=20,
                    budget_tokens=max(600, budget_tokens // 6),
                    auto_index=False,
                )
                if "error" not in callers:
                    relationships["callers"].append(
                        {
                            "symbol_id": symbol.symbol_id,
                            "symbol_name": symbol.symbol_name,
                            "related": callers.get("related", []),
                            "edges": callers.get("edges", []),
                        }
                    )
                callees = self._neighborhood(
                    "callees",
                    symbol_id=symbol.symbol_id,
                    depth=bounded_depth,
                    limit=20,
                    budget_tokens=max(600, budget_tokens // 6),
                    auto_index=False,
                )
                if "error" not in callees:
                    relationships["callees"].append(
                        {
                            "symbol_id": symbol.symbol_id,
                            "symbol_name": symbol.symbol_name,
                            "related": callees.get("related", []),
                            "edges": callees.get("edges", []),
                        }
                    )
                references = self._neighborhood(
                    "refs",
                    symbol_id=symbol.symbol_id,
                    group_by="none",
                    snippet_lines=0,
                    limit=20,
                    auto_index=False,
                    budget_tokens=max(600, budget_tokens // 6),
                )
                if "error" not in references:
                    refs_payload = references.get("references", [])
                    if isinstance(refs_payload, list):
                        relationships["usages"].append(
                            {
                                "symbol_id": symbol.symbol_id,
                                "symbol_name": symbol.symbol_name,
                                "references": refs_payload,
                            }
                        )

        additional_relevant_files = [
            symbol.file_path for symbol in ranked_symbols if symbol.file_path not in set(selected_files)
        ][:20]
        full_payload = {
            "query": query,
            "repo_id": self.repo_id,
            "entry_points": entry_points,
            "files": files_payload,
            "relationships": relationships,
            "additional_relevant_files": additional_relevant_files,
            "truncated": len(selected_symbols) > len(trimmed_symbols),
            "cache_hit": False,
            "provenance": _LOCAL_PROVENANCE,
        }
        # Budget-aware file trim: drop the lowest-priority files until the payload
        # fits, so explore degrades to fewer (most-relevant) files instead of
        # collapsing to "no results" when a completed family + relationships overflow.
        if include_source:
            while len(files_payload) > 1 and self._compute_total_tokens(full_payload) > budget_tokens:
                files_payload.pop()
                full_payload["files"] = files_payload
                full_payload["truncated"] = True
        skeletonized_meta: list[dict[str, Any]] = []
        tokens_saved_total = 0
        for file_entry in files_payload:
            for section in file_entry.get("source_sections", []):
                if not section.get("skeleton"):
                    continue
                section_id = str(section.get("symbol_id") or "")
                skeletonized_meta.append(
                    {
                        "symbol_id": section_id,
                        "qualified_name": section.get("qualified_name"),
                        "file_path": section.get("file_path"),
                        "family": skeleton_families.get(section_id, ""),
                    }
                )
                tokens_saved_total += int(section.get("tokens_saved") or 0)
        if skeletonized_meta:
            full_payload["skeletonized"] = skeletonized_meta
            full_payload["skeleton_tokens_saved"] = tokens_saved_total
        packed = self._pack_single_payload(
            full_payload,
            budget_tokens=budget_tokens,
            essential_keys=_EXPLORE_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=_EXPLORE_OPTIONAL_KEYS,
        )
        self._cache_set("code.explore", cache_args, packed)
        return packed

    def tool_routes(
        self,
        *,
        file_glob: str | None = None,
        language: str | None = None,
        limit: int = 200,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        normalized_language = language.lower().strip() if isinstance(language, str) and language.strip() else None
        cache_args = {
            "file_glob": file_glob,
            "language": normalized_language,
            "limit": limit,
            "budget_tokens": budget_tokens,
        }
        hit, cached = self._cache_get("code.routes", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)

        routes, source_truncated = self._indexed_route_records(
            file_glob=file_glob,
            language=normalized_language,
            limit=max(1, limit),
        )
        full_payload = self._build_routes_payload(
            routes,
            file_glob=file_glob,
            language=normalized_language,
            truncated=source_truncated,
        )
        full_total_tokens = self._compute_total_tokens({**full_payload, "tokens_saved": 0})

        def build_payload(packed_items: list[dict[str, Any]]) -> dict[str, Any]:
            return self._finalize_packed_payload(
                self._build_routes_payload(
                    packed_items,
                    file_glob=file_glob,
                    language=normalized_language,
                    truncated=source_truncated or len(packed_items) < len(routes),
                ),
                full_total_tokens=full_total_tokens,
            )

        packed = self._fit_items_to_budget(
            routes,
            budget_tokens=budget_tokens,
            essential_keys=_ROUTES_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=_ROUTES_OPTIONAL_KEYS,
            build_payload=build_payload,
        )
        payload = self._maybe_attach_overflow_metadata(
            packed_payload=packed,
            full_payload=full_payload,
            full_total_tokens=full_total_tokens,
            budget_tokens=budget_tokens,
        )
        self._cache_set("code.routes", cache_args, payload)
        return payload

    def tool_context(
        self,
        *,
        task: str,
        seed_files: list[str] | None = None,
        budget_tokens: int = 4000,
        max_symbols: int = 4,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        effective_budget_tokens = self._effective_budget_tokens("context", budget_tokens)
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        normalized_seeds = [self._normalize_file_arg(seed) for seed in seed_files or []]
        cache_args = {
            "task": task,
            "seed_files": normalized_seeds,
            "budget_tokens": effective_budget_tokens,
            "max_symbols": max_symbols,
        }
        hit, cached = self._cache_get("code.context", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)

        raw = self.context_pack(
            task=task,
            seed_files=normalized_seeds,
            budget_tokens=effective_budget_tokens,
            max_symbols=max_symbols,
            auto_index=False,
        )
        payload = self._pack_single_payload(
            raw.model_dump(mode="json"),
            budget_tokens=effective_budget_tokens,
            essential_keys=_CONTEXT_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=[
                "provenance",
                "budget_tokens",
                "token_count",
                "tokens_saved_vs_full_files",
                "content",
                "telemetry",
                "code_blocks",
                "repo_map",
                "import_neighbors",
                "related_symbols",
                "entry_points",
            ],
            base_tokens_saved=raw.tokens_saved_vs_full_files,
        )
        self._cache_set("code.context", cache_args, payload)
        return payload

    def tool_usages(
        self,
        query: str | None = None,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        symbol_name: str | None = None,
        file_path: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        file_glob: str | None = None,
        group_by: Literal["file", "caller", "none"] = "file",
        snippet_lines: int = 3,
        limit: int = 20,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        effective_budget_tokens = self._effective_budget_tokens("usages", budget_tokens)
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        normalized_file_path = self._normalize_file_arg(file_path) if file_path else None
        cache_args = {
            "query": query,
            "symbol_id": symbol_id,
            "qualified_name": qualified_name,
            "symbol_name": symbol_name,
            "file_path": normalized_file_path,
            "kind": kind,
            "language": language,
            "file_glob": file_glob,
            "group_by": group_by,
            "snippet_lines": snippet_lines,
            "limit": limit,
            "budget_tokens": effective_budget_tokens,
        }
        hit, cached = self._cache_get("code.usages", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)
        payload = self._neighborhood(
            "refs",
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=normalized_file_path,
            kind=kind,
            language=language,
            file_glob=file_glob,
            group_by=group_by,
            snippet_lines=snippet_lines,
            limit=limit,
            auto_index=False,
            budget_tokens=effective_budget_tokens,
        )
        if "error" not in payload:
            self._cache_set("code.usages", cache_args, payload)
        return payload

    def tool_callers(
        self,
        query: str | None = None,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        symbol_name: str | None = None,
        file_path: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        depth: int = 1,
        limit: int = 20,
        snapshot: bool = False,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        return self._neighborhood(
            "callers",
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=file_path,
            kind=kind,
            language=language,
            depth=depth,
            limit=limit,
            snapshot=snapshot,
            budget_tokens=budget_tokens,
            auto_index=auto_index,
        )

    def tool_callees(
        self,
        query: str | None = None,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        symbol_name: str | None = None,
        file_path: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        depth: int = 1,
        limit: int = 20,
        snapshot: bool = False,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        return self._neighborhood(
            "callees",
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=file_path,
            kind=kind,
            language=language,
            depth=depth,
            limit=limit,
            snapshot=snapshot,
            budget_tokens=budget_tokens,
            auto_index=auto_index,
        )

    def tool_pattern(
        self,
        *,
        pattern: str,
        rewrite: str | None = None,
        language: str | None = None,
        file_glob: str | None = None,
        dry_run: bool = True,
        limit: int = 20,
        budget_tokens: int = 4000,
    ) -> dict[str, Any]:
        self._ensure_indexed()
        effective_budget_tokens = self._effective_budget_tokens("pattern", budget_tokens)
        adapter = AstGrepAdapter(self.repo_root)
        if rewrite is None:
            cache_args = {
                "pattern": pattern,
                "language": language,
                "file_glob": file_glob,
                "limit": limit,
                "budget_tokens": effective_budget_tokens,
            }
            native_cache_args = {**cache_args, "native": True}
            hit, cached = self._cache_get("code.pattern", native_cache_args)
            if hit and cached is not None:
                return self._mark_cache_hit(cached)
            native = self._native_python_pattern_search(
                pattern=pattern,
                language=language,
                file_glob=file_glob,
                limit=limit,
            )
            if native is not None:
                payload = self._pack_pattern_matches(native, budget_tokens=effective_budget_tokens)
                self._cache_set(
                    "code.pattern",
                    native_cache_args,
                    payload,
                )
                return payload
            hit, cached = self._cache_get("code.pattern", cache_args)
            if hit and cached is not None:
                return self._mark_cache_hit(cached)
            try:
                result = adapter.search(pattern=pattern, language=language, file_glob=file_glob, limit=limit)
            except AstGrepToolUnavailable as exc:
                native_unavailable = self._native_python_pattern_search(
                    pattern=pattern,
                    language=language,
                    file_glob=file_glob,
                    limit=limit,
                )
                if native_unavailable is not None:
                    payload = self._pack_pattern_matches(native_unavailable, budget_tokens=effective_budget_tokens)
                    return payload
                return exc.payload
            if len(result.matches) > limit:
                result = PatternSearchResult(
                    matches=result.matches[:limit],
                    truncated=True,
                    total_matches=result.total_matches if result.total_matches is not None else len(result.matches),
                )
            payload = self._pack_pattern_matches(
                result,
                budget_tokens=effective_budget_tokens,
            )
            self._cache_set("code.pattern", cache_args, payload)
            return payload

        try:
            rewrite_result = adapter.rewrite(
                pattern=pattern,
                rewrite=rewrite,
                language=language,
                file_glob=file_glob,
                dry_run=dry_run,
            )
        except AstGrepToolUnavailable as exc:
            return exc.payload
        if not dry_run and rewrite_result.files_changed:
            self._reindex_files(rewrite_result.files_changed)
        return self._pack_pattern_rewrite(rewrite_result, budget_tokens=effective_budget_tokens)

    def _native_python_pattern_search(
        self,
        *,
        pattern: str,
        language: str | None,
        file_glob: str | None,
        limit: int,
    ) -> PatternSearchResult | None:
        """Native Python structural search for common benchmark-critical patterns.

        ast-grep remains the advanced backend, but decorators/calls should not
        fail just because an external binary is unavailable.
        """
        normalized = pattern.strip()
        if language not in {None, "python", "py"}:
            return None
        mode: Literal["decorator", "call", "call_any", "def", "class"] | None = None
        target_name: str | None = None
        if normalized.startswith("@"):
            mode = "decorator"
            target_name = normalized[1:].split("(", 1)[0].strip()
        elif normalized in {"$F($$$ARGS)", "$F($$$)", "$F()"}:
            mode = "call_any"
        elif match := re.fullmatch(r"([A-Za-z_][A-Za-z0-9_\.]*)\(\s*(?:\$\$\$|\.{3}|)\s*\)", normalized):
            mode = "call"
            target_name = match.group(1)
        elif match := re.fullmatch(
            r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*(?:\$\$\$|\.{3}|[^)]*)\)\s*:?",
            normalized,
        ):
            mode = "def"
            target_name = match.group(1)
        elif match := re.fullmatch(
            r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\s*(?:\$\$\$|\.{3}|[^)]*)\s*\))?\s*:?",
            normalized,
        ):
            mode = "class"
            target_name = match.group(1)
        if mode is None or (mode != "call_any" and not target_name):
            return None

        matches: list[PatternMatch] = []
        candidates = sorted(path for path in self._indexed_files() if path.endswith(".py"))
        if file_glob:
            candidates = [path for path in candidates if _matches_file_glob(path, file_glob)]

        def names_match(observed: str | None) -> bool:
            if observed is None or target_name is None:
                return False
            return observed == target_name or ("." not in target_name and observed.endswith(f".{target_name}"))

        def build_match(
            rel: str,
            lines: list[str],
            node: ast.AST,
            *,
            captures: dict[str, str],
        ) -> PatternMatch:
            line = int(getattr(node, "lineno", 1) or 1)
            column = int(getattr(node, "col_offset", 0) or 0) + 1
            end_line = int(getattr(node, "end_lineno", line) or line)
            end_column = int(getattr(node, "end_col_offset", 0) or 0) + 1
            snippet = lines[line - 1].strip() if 1 <= line <= len(lines) else ""
            return PatternMatch(
                file_path=rel,
                line=line,
                column=column,
                end_line=max(line, end_line),
                end_column=max(column, end_column),
                snippet=snippet,
                captures=captures,
            )

        max_matches = max(0, limit)
        truncated = False

        def append_match(match: PatternMatch) -> None:
            nonlocal truncated
            if len(matches) < max_matches:
                matches.append(match)
                return
            truncated = True

        if mode == "decorator" and target_name:
            raw_matches = self.search_text(f"@{target_name}", path=".", limit=max_matches + 1)
            decorator_re = re.compile(r"^\s*@\s*([A-Za-z_][A-Za-z0-9_\.]*)")
            for raw_match in raw_matches:
                if not raw_match.file_path.endswith(".py"):
                    continue
                if file_glob and not _matches_file_glob(raw_match.file_path, file_glob):
                    continue
                match = decorator_re.match(raw_match.text)
                if match is None or not names_match(match.group(1)):
                    continue
                append_match(
                    PatternMatch(
                        file_path=raw_match.file_path,
                        line=raw_match.line,
                        column=raw_match.column,
                        end_line=raw_match.line,
                        end_column=raw_match.column + len(raw_match.text),
                        snippet=raw_match.text.strip(),
                        captures={"decorator": match.group(1)},
                    )
                )
                if truncated:
                    break
            matches.sort(key=lambda item: (item.file_path, item.line, item.column, item.snippet))
            return PatternSearchResult(
                matches=matches, truncated=truncated, total_matches=None if truncated else len(matches)
            )

        if mode in {"def", "class"} and target_name:
            wanted_kinds = ("class",) if mode == "class" else ("function", "method")
            placeholders = ",".join("?" for _ in wanted_kinds)
            with self._connect() as conn:
                self._init_schema(conn)
                rows = conn.execute(
                    f"""
                    SELECT *, NULL AS score FROM symbols
                    WHERE repo_id = ? AND symbol_name = ? AND kind IN ({placeholders})
                    ORDER BY file_path, start_line, end_line, qualified_name, symbol_id
                    LIMIT ?
                    """,
                    (self.repo_id, target_name, *wanted_kinds, max_matches + 1),
                ).fetchall()
            for row in rows:
                symbol = _row_to_symbol(row)
                if file_glob and not _matches_file_glob(symbol.file_path, file_glob):
                    continue
                append_match(
                    PatternMatch(
                        file_path=symbol.file_path,
                        line=symbol.start_line,
                        column=1,
                        end_line=symbol.end_line,
                        end_column=1,
                        snippet=symbol.signature,
                        captures={"name": symbol.symbol_name},
                    )
                )
                if truncated:
                    break
            return PatternSearchResult(
                matches=matches, truncated=truncated, total_matches=None if truncated else len(matches)
            )

        for rel in candidates:
            if truncated:
                break
            source = self._read_file(rel)
            lines = source.splitlines()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            if mode == "decorator":
                for node in ast.walk(tree):
                    if truncated:
                        break
                    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                        continue
                    for decorator in node.decorator_list:
                        name = self._python_call_name(decorator)
                        if name is None and isinstance(decorator, ast.Name):
                            name = decorator.id
                        if not names_match(name):
                            continue
                        append_match(
                            build_match(
                                rel,
                                lines,
                                decorator,
                                captures={"decorator": name or target_name or ""},
                            )
                        )
                        if truncated:
                            break
            elif mode in {"call", "call_any"}:
                for node in ast.walk(tree):
                    if truncated:
                        break
                    if not isinstance(node, ast.Call):
                        continue
                    name = self._python_call_name(node.func)
                    if not name or (mode == "call" and not names_match(name)):
                        continue
                    append_match(build_match(rel, lines, node, captures={"F": name}))
            elif mode == "def":
                for node in ast.walk(tree):
                    if truncated:
                        break
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == target_name:
                        append_match(build_match(rel, lines, node, captures={"name": node.name}))
            elif mode == "class":
                for node in ast.walk(tree):
                    if truncated:
                        break
                    if isinstance(node, ast.ClassDef) and node.name == target_name:
                        append_match(build_match(rel, lines, node, captures={"name": node.name}))
        matches.sort(key=lambda item: (item.file_path, item.line, item.column, item.snippet))
        total_matches = None if truncated else len(matches)
        return PatternSearchResult(matches=matches, truncated=truncated, total_matches=total_matches)

    def tool_status(
        self,
        *,
        budget_tokens: int = 2000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        cache_args = {
            "budget_tokens": budget_tokens,
            "index_version": self._current_index_version(),
            "autosync_enabled": self._autosync_enabled,
            "autosync_debounce_ms": self._autosync_debounce_ms,
            "head_sha": self._safe_current_head_sha(),
        }
        hit, cached = self._cache_get("code.status", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)
        index_stats = self._index_snapshot()
        cache_stats = self._cache.stats(
            repo_id=self.repo_id,
            index_version=self._current_index_version(),
            tool_name=None,
        )
        stale_after_seconds = 86_400
        files_indexed = int(index_stats.get("files_indexed", 0) or 0)
        index_age_seconds = index_stats.get("index_age_seconds")
        if files_indexed <= 0:
            freshness_status = "empty"
            freshness_reason = "no indexed files"
        elif isinstance(index_age_seconds, int) and index_age_seconds > stale_after_seconds:
            freshness_status = "stale"
            freshness_reason = "index older than stale threshold"
        else:
            freshness_status = "fresh"
            freshness_reason = "index within freshness threshold"

        provider_thresholds = {
            "required_health_status": "ok",
            "require_index_head_match_for_scip": True,
        }
        head_sha = self._safe_current_head_sha()
        warnings: list[dict[str, Any]] = []
        provider_counts = {"ok": 0, "degraded": 0, "unhealthy": 0}
        providers: list[dict[str, Any]] = []
        for provider in self.intel_store.providers:
            provider_name = str(getattr(provider, "name", provider.__class__.__name__.lower()))
            entry: dict[str, Any] = {"name": provider_name}
            try:
                health = provider.health()
            except Exception as exc:
                logging.exception("Recovered from broad exception handler")
                health = ProviderHealth(status="unhealthy", reason=str(exc))
            if isinstance(health, ProviderHealth):
                entry["status"] = health.status
                entry["ok"] = health.ok
                if health.reason:
                    entry["reason"] = str(health.reason)
            else:
                ok = bool(health)
                entry["status"] = "ok" if ok else "unhealthy"
                entry["ok"] = ok
            provider_status = str(entry.get("status") or "unhealthy")
            if provider_status in provider_counts:
                provider_counts[provider_status] += 1
            if provider_status != "ok":
                warnings.append(
                    {
                        "code": "provider_health_not_ok",
                        "level": "warning",
                        "provider": provider_name,
                        "message": f"provider '{provider_name}' health is {provider_status}",
                    }
                )
            index_sha_fn = getattr(provider, "index_sha", None)
            if callable(index_sha_fn):
                with contextlib.suppress(Exception):
                    index_sha = index_sha_fn()
                    if index_sha:
                        entry["index_sha"] = str(index_sha)
            if provider_name == "scip":
                if head_sha is not None:
                    entry["head_sha"] = head_sha
                index_sha = entry.get("index_sha")
                if isinstance(index_sha, str) and head_sha:
                    if index_sha == head_sha:
                        entry["freshness"] = "fresh"
                    else:
                        entry["freshness"] = "stale"
                        warnings.append(
                            {
                                "code": "provider_index_stale",
                                "level": "warning",
                                "provider": provider_name,
                                "message": "SCIP index SHA does not match HEAD; reindex recommended.",
                            }
                        )
                else:
                    entry["freshness"] = "unknown"
            else:
                entry["freshness"] = "unknown"
            providers.append(entry)

        payload = {
            "repo_id": self.repo_id,
            "repo_root": str(self.repo_root),
            "db_path": str(self.db_path),
            "index_version": self._current_index_version(),
            "index": index_stats,
            "cache": cache_stats,
            "providers": providers,
            "provider_freshness": {
                "thresholds": provider_thresholds,
                "summary": {
                    **provider_counts,
                    "total": sum(provider_counts.values()),
                },
            },
            "warnings": warnings,
            "freshness": {
                "status": freshness_status,
                "reason": freshness_reason,
                "indexed": files_indexed > 0,
                "last_indexed_at": index_stats.get("last_indexed_at"),
                "index_age_seconds": index_age_seconds,
                "stale_after_seconds": stale_after_seconds,
            },
            "autosync": self._autosync_status(),
            "provenance": _LOCAL_PROVENANCE,
        }
        payload = cast(dict[str, Any], self._json_safe(payload))
        packed = self._pack_single_payload(
            payload,
            budget_tokens=budget_tokens,
            essential_keys=_STATUS_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=[],
        )
        self._cache_set("code.status", cache_args, packed)
        return packed

    def tool_cache_status(
        self,
        *,
        cache_tool: str | None = None,
        budget_tokens: int = 4000,
    ) -> dict[str, Any]:
        effective_budget_tokens = self._effective_budget_tokens("cache_status", budget_tokens)
        tool_name = self._normalize_cache_tool(cache_tool)
        cache_stats = self._cache.stats(
            repo_id=self.repo_id,
            index_version=self._current_index_version(),
            tool_name=tool_name,
        )
        payload = {
            "repo_id": self.repo_id,
            "index_version": self._current_index_version(),
            "entry_count": int(cache_stats.get("entry_count", 0)),
            "entries_by_tool": cache_stats.get("entries_by_tool", {}),
            "total_bytes": int(cache_stats.get("total_bytes", 0)),
            "max_bytes": int(cache_stats.get("max_bytes", 0)),
            "scope": {
                "cache_tool": cache_tool or "all",
                "tool_name": tool_name,
            },
            "last_hit_at": cache_stats.get("last_hit_at", ""),
            "provenance": _LOCAL_PROVENANCE,
        }
        return self._pack_single_payload(
            payload,
            budget_tokens=effective_budget_tokens,
            essential_keys=_CACHE_STATUS_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=["repo_id", "index_version", "last_hit_at", "scope"],
        )

    def tool_cache_invalidate(
        self,
        *,
        cache_tool: str | None = None,
        budget_tokens: int = 4000,
    ) -> dict[str, Any]:
        tool_name = self._normalize_cache_tool(cache_tool)
        index_version = self._current_index_version()
        invalidated = self._cache.invalidate(repo_id=self.repo_id, index_version=index_version, tool_name=tool_name)
        return self._pack_single_payload(
            {
                "repo_id": self.repo_id,
                "index_version": index_version,
                **invalidated,
                "scope": {"cache_tool": cache_tool or "all", "tool_name": tool_name},
                "provenance": _LOCAL_PROVENANCE,
            },
            budget_tokens=budget_tokens,
            essential_keys=_CACHE_INVALIDATE_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=[],
        )

    @overload
    def search_symbols(
        self,
        query: str,
        *,
        limit: int = 20,
        mode: SearchMode = "auto",
        kind: str | None = None,
        language: str | None = None,
        snippet: Literal["none", "head", "full"] = "none",
        snippet_lines: int = 8,
        file_glob: str | None = None,
        scope: Literal["repo", "external"] = "repo",
        since: str | None = None,
        touched_by: str | None = None,
        auto_index: bool = True,
        provenance_filter: str | None = None,
    ) -> list[SymbolRecord]: ...

    @overload
    def search_symbols(
        self,
        query: str,
        *,
        scope: Literal["deleted"],
        limit: int = 20,
        mode: SearchMode = "auto",
        kind: str | None = None,
        language: str | None = None,
        snippet: Literal["none", "head", "full"] = "none",
        snippet_lines: int = 8,
        file_glob: str | None = None,
        since: str | None = None,
        touched_by: str | None = None,
        auto_index: bool = True,
        provenance_filter: str | None = None,
    ) -> list[DeletedHistoryItem]: ...

    def search_symbols(
        self,
        query: str,
        *,
        limit: int = 20,
        mode: SearchMode = "auto",
        kind: str | None = None,
        language: str | None = None,
        snippet: Literal["none", "head", "full"] = "none",
        snippet_lines: int = 8,
        file_glob: str | None = None,
        scope: Literal["repo", "external", "deleted"] = "repo",
        since: str | None = None,
        touched_by: str | None = None,
        auto_index: bool = True,
        provenance_filter: str | None = None,
    ) -> list[SymbolRecord] | list[DeletedHistoryItem]:
        """Deterministic multi-channel symbol search with routed-provider fallback."""
        if auto_index and scope != "deleted":
            self._ensure_indexed()
        if scope == "deleted":
            return self._deleted_history_adapter().search(
                query,
                limit=limit,
                since_ts=_parse_since_filter(since),
                touched_by=_normalize_touched_by(touched_by),
                language=language,
            )
        resolved_mode = resolve_search_mode(query, mode)
        candidate_files: set[str] | None = None
        rerank_limit = self._search_reranker.pre_rerank_limit(limit, mode=resolved_mode, scope=scope)
        if scope == "repo" and provenance_filter == "commit":
            hits = self._search_commit_chunks(query, limit=rerank_limit)
            if file_glob:
                hits = [hit for hit in hits if _matches_file_glob(hit.file_path, file_glob)]
            hits = [hit for hit in hits if not should_skip_relative_path(hit.file_path)]
            if _is_precise_symbol_query(query):
                exact_hits = _exact_symbol_hits(hits, query)
                if exact_hits:
                    hits = exact_hits
            hits = self._search_reranker.rerank(
                query,
                hits,
                mode=resolved_mode,
                scope=scope,
                source_loader=self._load_symbol_source_for_rerank,
            )
            return [
                self._attach_snippet(symbol, snippet=snippet, snippet_lines=snippet_lines) for symbol in hits[:limit]
            ]
        if scope == "repo" and resolved_mode != "semantic":
            candidate_files = self._zoekt_candidate_files(query, max_files=max(limit * 4, 40))
        if resolved_mode == "lexical":
            hits = self.intel_store.search_symbols(query, limit=limit, kind=kind, language=language, scope=scope)
            if scope == "repo" and candidate_files:
                hits = [hit for hit in hits if hit.file_path in candidate_files]
            if scope == "repo" and not hits:
                hits = self._search_symbols_local(
                    query,
                    limit=limit,
                    kind=kind,
                    language=language,
                    candidate_files=candidate_files,
                )
        else:
            candidate_limit = semantic_candidate_limit(rerank_limit)
            if scope == "external":
                hits = self.intel_store.search_symbols(
                    query,
                    limit=candidate_limit,
                    kind=kind,
                    language=language,
                    scope="external",
                )
            else:
                lexical_hits = self.intel_store.search_symbols(
                    query,
                    limit=candidate_limit,
                    kind=kind,
                    language=language,
                    scope="repo",
                )
                if candidate_files:
                    lexical_hits = [hit for hit in lexical_hits if hit.file_path in candidate_files]
                if not lexical_hits:
                    lexical_hits = self._search_symbols_local(
                        query,
                        limit=candidate_limit,
                        kind=kind,
                        language=language,
                        candidate_files=candidate_files,
                    )
                try:
                    semantic_hits = self._search_symbols_semantic_local(
                        query,
                        limit=candidate_limit,
                        kind=kind,
                        language=language,
                    )
                except OllamaUnavailable:
                    semantic_hits = []
                # Merge commit chunks as a third candidate source (LINEAGE-03)
                commit_hits: list[SymbolRecord] = []
                with contextlib.suppress(Exception):
                    commit_hits = self._search_commit_chunks(query, limit=candidate_limit)
                if resolved_mode == "semantic":
                    hits = (semantic_hits + commit_hits)[:rerank_limit]
                else:
                    hits = self._semantic_ranker.reciprocal_rank_fuse(
                        lexical_hits, semantic_hits + commit_hits, limit=rerank_limit
                    )
        if file_glob:
            hits = [hit for hit in hits if _matches_file_glob(hit.file_path, file_glob)]
        hits = [hit for hit in hits if not should_skip_relative_path(hit.file_path)]
        if provenance_filter is not None:
            hits = [h for h in hits if h.provenance == provenance_filter]
        if _is_precise_symbol_query(query):
            exact_hits = _exact_symbol_hits(hits, query)
            if exact_hits:
                hits = exact_hits
        hits = self._search_reranker.rerank(
            query,
            hits,
            mode=resolved_mode,
            scope=scope,
            source_loader=self._load_symbol_source_for_rerank,
        )
        return [self._attach_snippet(symbol, snippet=snippet, snippet_lines=snippet_lines) for symbol in hits[:limit]]

    def _search_symbols_local(
        self,
        query: str,
        *,
        limit: int = 20,
        kind: str | None = None,
        language: str | None = None,
        candidate_files: set[str] | None = None,
    ) -> list[SymbolRecord]:
        normalized_query = query.strip()
        if not normalized_query:
            return []
        normalized_query_lower = normalized_query.lower()
        fts_query = _safe_fts_query(normalized_query)
        fts_prefix_query = _fts_prefix_query(normalized_query)
        terms = _identifier_terms(normalized_query)
        first_term = terms[0] if terms else normalized_query_lower[:4]
        strong_fetch_limit = max(limit * 8, 80)
        query_mentions_tests = _query_implies_test_scope(normalized_query)
        kind_boosts = {
            "class": 18.0,
            "interface": 18.0,
            "type": 15.0,
            "struct": 15.0,
            "enum": 14.0,
            "method": 11.0,
            "function": 10.0,
        }
        if normalized_query and normalized_query[0].isupper():
            kind_boosts["class"] = kind_boosts.get("class", 0.0) + 8.0
            kind_boosts["type"] = kind_boosts.get("type", 0.0) + 8.0

        filters = ["repo_id = ?"]
        params: list[Any] = [self.repo_id]
        if kind:
            filters.append("kind = ?")
            params.append(kind)
        if language:
            filters.append("language = ?")
            params.append(language)
        if candidate_files:
            normalized_candidates = sorted({self._normalize_file_arg(path) for path in candidate_files if path})
            if normalized_candidates:
                filters.append(f"file_path IN ({','.join('?' for _ in normalized_candidates)})")
                params.extend(normalized_candidates)
        where_sql = " AND ".join(filters)

        term_set = {term for term in terms if term}
        centrality_map = self._symbol_centrality_map()
        scored: dict[str, tuple[float, int, SymbolRecord]] = {}

        def adjustment(symbol: SymbolRecord) -> float:
            score = kind_boosts.get(symbol.kind, 0.0)
            symbol_name_lower = symbol.symbol_name.lower()
            qualified_name_lower = symbol.qualified_name.lower()
            lexical_text = f"{symbol.symbol_name} {symbol.qualified_name} {symbol.signature}".lower()
            file_path_lower = symbol.file_path.lower()
            file_name_stem = Path(symbol.file_path).stem.lower()
            coverage = sum(1 for term in terms[:8] if term and term in lexical_text)
            score += float(coverage) * 5.0
            if symbol_name_lower.startswith(normalized_query_lower):
                score += 24.0
            if qualified_name_lower.startswith(normalized_query_lower):
                score += 20.0
            if normalized_query_lower in file_name_stem:
                score += 22.0
            elif file_name_stem.startswith(normalized_query_lower[: max(1, min(len(normalized_query_lower), 8))]):
                score += 10.0
            for term in terms[:6]:
                if term and term in file_path_lower:
                    score += 6.0
            # Per-token name match (the missing name-match bonus): reward a query
            # TOKEN that matches the symbol's OWN name tokens, so multi-term/regex
            # queries (e.g. "select_format|CAST") still surface the exactly-named
            # symbol instead of losing to body-coverage / kind-boost noise.
            name_tokens = _identifier_terms(symbol.symbol_name)
            if name_tokens:
                matched = sum(1 for token in name_tokens if token in term_set)
                if matched == len(name_tokens):
                    score += 28.0 + 6.0 * len(name_tokens)
                elif matched:
                    score += 9.0 * matched
            # Structural importance (call-graph eigenvector centrality / PageRank):
            # the signal Atelier computes but never fed into ranking. Central core
            # symbols outrank peripheral textual matches. Normalized 0..1.
            cscore = centrality_map.get(symbol_name_lower)
            if cscore is None:
                cscore = centrality_map.get(qualified_name_lower, 0.0)
            score += cscore * 30.0
            if _is_test_file_path(symbol.file_path) and not query_mentions_tests:
                score -= 90.0
            return score

        def consider_rows(
            rows: list[sqlite3.Row], *, channel_rank: int, base: float, use_row_score: bool = False
        ) -> None:
            for row in rows:
                symbol = _row_to_symbol(row)
                channel_score = float(row["score"]) * 100.0 if use_row_score and row["score"] is not None else 0.0
                score = base + channel_score + adjustment(symbol)
                existing = scored.get(symbol.symbol_id)
                next_value = (score, channel_rank, symbol.model_copy(update={"score": score}))
                if existing is None:
                    scored[symbol.symbol_id] = next_value
                    continue
                if next_value[0] > existing[0] or (next_value[0] == existing[0] and next_value[1] < existing[1]):
                    scored[symbol.symbol_id] = next_value

        with self._connect() as conn:
            self._init_schema(conn)
            exact_rows = conn.execute(
                f"""
                SELECT *, NULL AS score
                FROM symbols
                WHERE {where_sql} AND (symbol_name = ? OR qualified_name = ?)
                ORDER BY file_path, start_line
                LIMIT ?
                """,
                tuple([*params, normalized_query, normalized_query, strong_fetch_limit]),
            ).fetchall()
            consider_rows(exact_rows, channel_rank=0, base=1300.0)

            ci_exact_rows = conn.execute(
                f"""
                SELECT *, NULL AS score
                FROM symbols
                WHERE {where_sql} AND (lower(symbol_name) = ? OR lower(qualified_name) = ?)
                ORDER BY file_path, start_line
                LIMIT ?
                """,
                tuple([*params, normalized_query_lower, normalized_query_lower, strong_fetch_limit]),
            ).fetchall()
            consider_rows(ci_exact_rows, channel_rank=1, base=1180.0)

            if fts_query:
                fts_rows = conn.execute(
                    f"""
                    SELECT s.*, 1.0 / (1.0 + abs(bm25(symbol_fts))) AS score
                    FROM symbol_fts
                    JOIN symbols s ON s.symbol_id = symbol_fts.symbol_id
                    WHERE symbol_fts MATCH ? AND s.repo_id = ?{" AND s.kind = ?" if kind else ""}{" AND s.language = ?" if language else ""}
                    ORDER BY bm25(symbol_fts), s.file_path, s.start_line
                    LIMIT ?
                    """,
                    tuple(
                        [
                            fts_query,
                            self.repo_id,
                            *([kind] if kind else []),
                            *([language] if language else []),
                            strong_fetch_limit,
                        ]
                    ),
                ).fetchall()
                consider_rows(fts_rows, channel_rank=2, base=980.0, use_row_score=True)

            if fts_prefix_query and fts_prefix_query != fts_query:
                fts_prefix_rows = conn.execute(
                    f"""
                    SELECT s.*, 1.0 / (1.0 + abs(bm25(symbol_fts))) AS score
                    FROM symbol_fts
                    JOIN symbols s ON s.symbol_id = symbol_fts.symbol_id
                    WHERE symbol_fts MATCH ? AND s.repo_id = ?{" AND s.kind = ?" if kind else ""}{" AND s.language = ?" if language else ""}
                    ORDER BY bm25(symbol_fts), s.file_path, s.start_line
                    LIMIT ?
                    """,
                    tuple(
                        [
                            fts_prefix_query,
                            self.repo_id,
                            *([kind] if kind else []),
                            *([language] if language else []),
                            strong_fetch_limit,
                        ]
                    ),
                ).fetchall()
                consider_rows(fts_prefix_rows, channel_rank=3, base=940.0, use_row_score=True)

            like_pattern = f"%{normalized_query_lower}%"
            substring_rows = conn.execute(
                f"""
                SELECT *, NULL AS score
                FROM symbols
                WHERE {where_sql} AND (
                    lower(symbol_name) LIKE ?
                    OR lower(qualified_name) LIKE ?
                    OR lower(signature) LIKE ?
                )
                ORDER BY file_path, start_line
                LIMIT ?
                """,
                tuple([*params, like_pattern, like_pattern, like_pattern, strong_fetch_limit]),
            ).fetchall()
            consider_rows(substring_rows, channel_rank=4, base=860.0)

            path_rows = conn.execute(
                f"""
                SELECT *, NULL AS score
                FROM symbols
                WHERE {where_sql} AND (
                    lower(file_path) LIKE ?
                    OR lower(file_path) LIKE ?
                )
                ORDER BY file_path, start_line
                LIMIT ?
                """,
                tuple([*params, like_pattern, f"%{first_term}%", strong_fetch_limit]),
            ).fetchall()
            consider_rows(path_rows, channel_rank=5, base=820.0)

            camel_seed_rows = conn.execute(
                f"""
                SELECT *, NULL AS score
                FROM symbols
                WHERE {where_sql}
                ORDER BY file_path, start_line
                LIMIT ?
                """,
                tuple([*params, strong_fetch_limit]),
            ).fetchall()
            camel_rows = [
                row
                for row in camel_seed_rows
                if _camel_case_match(
                    normalized_query,
                    str(row["symbol_name"]),
                    str(row["qualified_name"]),
                )
            ]
            consider_rows(camel_rows, channel_rank=6, base=790.0)

            # Fuzzy recovery (RapidFuzz / Damerau-Levenshtein). Fires whenever the
            # strong channels found no EXACT name match -- not only on a total miss --
            # so a stray partial-token hit no longer suppresses the real target.
            # Damerau-Levenshtein scores transpositions (``make_ram_env`` ->
            # ``make_arm_env``) and insert/delete/substitute typos in one pass; the
            # scan covers EVERY in-scope symbol so recall is independent of fetch
            # order, and matches merge below exact/strong hits, ranked by similarity.
            has_exact_name_match = any(
                record.symbol_name.lower() == normalized_query_lower
                or record.qualified_name.lower() == normalized_query_lower
                for _, _, record in scored.values()
            )
            if not has_exact_name_match and _should_run_full_fuzzy_symbol_scan(normalized_query):
                fuzzy_name_rows = conn.execute(
                    f"SELECT symbol_id, symbol_name FROM symbols WHERE {where_sql}",
                    tuple(params),
                ).fetchall()
                if fuzzy_name_rows:
                    candidate_names = [str(row["symbol_name"]).lower() for row in fuzzy_name_rows]
                    matched_ids: list[str] = []
                    similarity_by_id: dict[str, float] = {}
                    for _matched, similarity, index in rapidfuzz_process.extract(
                        normalized_query_lower,
                        candidate_names,
                        scorer=DamerauLevenshtein.normalized_similarity,
                        score_cutoff=_FUZZY_SIMILARITY_CUTOFF,
                        limit=strong_fetch_limit,
                    ):
                        if candidate_names[index] == normalized_query_lower:
                            continue
                        symbol_id = str(fuzzy_name_rows[index]["symbol_id"])
                        matched_ids.append(symbol_id)
                        similarity_by_id[symbol_id] = float(similarity)
                    if matched_ids:
                        placeholders = ",".join("?" for _ in matched_ids)
                        matched_rows = conn.execute(
                            f"""
                            SELECT *, NULL AS score FROM symbols
                            WHERE repo_id = ? AND symbol_id IN ({placeholders})
                            """,
                            tuple([self.repo_id, *matched_ids]),
                        ).fetchall()
                        for row in matched_rows:
                            symbol_id = str(row["symbol_id"])
                            consider_rows(
                                [row],
                                channel_rank=7,
                                base=600.0 + similarity_by_id.get(symbol_id, 0.0) * 60.0,
                            )

        ranked = sorted(
            scored.values(),
            key=lambda item: (
                -item[0],
                item[1],
                item[2].file_path,
                item[2].start_line,
                item[2].end_line,
                item[2].qualified_name,
                item[2].symbol_id,
            ),
        )
        emit_product_local(
            "code_context_retrieved",
            repo_id=self.repo_id,
            operation="search",
            result_count=len(ranked),
        )
        return [symbol for _, _, symbol in ranked[:limit]]

    def _search_symbols_semantic_local(
        self,
        query: str,
        *,
        limit: int = 20,
        kind: str | None = None,
        language: str | None = None,
    ) -> list[SymbolRecord]:
        # Default path (ANN opt-in off): byte-identical to before -- positional
        # candidate scan + brute-force cosine in SemanticSearchRanker.
        if not ann_retrieval_enabled():
            candidates = self._semantic_symbol_candidates(limit=limit, kind=kind, language=language)
            return self._semantic_ranker.semantic_search(
                query,
                candidates=candidates,
                limit=limit,
                source_loader=lambda symbol: self._read_file_slice(
                    symbol.file_path, symbol.start_byte, symbol.end_byte
                ),
            )
        return self._search_symbols_semantic_ann(query, limit=limit, kind=kind, language=language)

    def _search_symbols_semantic_ann(
        self,
        query: str,
        *,
        limit: int,
        kind: str | None = None,
        language: str | None = None,
    ) -> list[SymbolRecord]:
        """Opt-in ANN semantic search over the persistent per-symbol vector store.

        Replaces the positional LIMIT scan: candidates are recovered by cosine
        proximity (HNSW, or exact brute-force as the mandatory fallback) over
        provenance-stamped vectors. N5 (model-id/dim drift) and N16 (index_version
        staleness) are enforced via :class:`SymbolAnnIndex`.
        """
        embedder = self._semantic_ranker.embedder
        embedding_dim = embedder.dim
        if embedding_dim <= 0:
            return []
        query_vector = self._semantic_ranker.embed_query(query)
        if not query_vector:
            return []
        index_version = self._current_index_version()
        # Full filtered candidate set (capped) -- the store, not a positional
        # slice, decides relevance. Embedding is cached, so warm runs are cheap.
        candidates = self._semantic_symbol_candidates(limit=_ANN_SYMBOL_CANDIDATE_CAP, kind=kind, language=language)
        if not candidates:
            return []
        candidate_by_id = {symbol.symbol_id: symbol for symbol in candidates}
        with self._connect() as conn:
            self._init_schema(conn)
            # N5: only ids already stored under the *current* model/dim/version
            # are fresh; everything else is (re-)embedded so a model swap never
            # leaves stale vectors in play.
            fresh_ids = self._ann_symbol_index.existing_stamped_ids(
                conn,
                embedder_name=embedder.name,
                embedding_dim=embedding_dim,
                index_version=index_version,
            )
            pending = {symbol_id: symbol for symbol_id, symbol in candidate_by_id.items() if symbol_id not in fresh_ids}
            new_vectors: dict[str, tuple[str, list[float]]] = {}
            for symbol_id, symbol in pending.items():
                source_text = self._read_file_slice(symbol.file_path, symbol.start_byte, symbol.end_byte)
                vector = self._semantic_ranker.embed_symbol(symbol, source_text=source_text)
                if vector and len(vector) == embedding_dim:
                    new_vectors[symbol_id] = (symbol.content_hash, vector)
            self._ann_symbol_index.upsert_vectors(
                conn,
                embedder_name=embedder.name,
                embedding_dim=embedding_dim,
                index_version=index_version,
                vectors=new_vectors,
            )
            stored = self._ann_symbol_index.load_current_vectors(
                conn,
                embedder_name=embedder.name,
                embedding_dim=embedding_dim,
            )
        # Restrict ranking to the in-scope candidate set so kind/language filters
        # and the positional cap are honoured even though the store may hold more.
        stored = [sv for sv in stored if sv.symbol_id in candidate_by_id]
        ranked_ids = self._ann_symbol_index.query(
            query_vector,
            stored,
            limit=limit,
            index_version=index_version,
            embedder_name=embedder.name,
            embedding_dim=embedding_dim,
        )
        from atelier.infra.storage.vector import cosine_similarity

        results: list[SymbolRecord] = []
        score_by_id = {sv.symbol_id: cosine_similarity(query_vector, sv.vector) for sv in stored}
        for symbol_id in ranked_ids:
            hit = candidate_by_id.get(symbol_id)
            if hit is None:
                continue
            results.append(hit.model_copy(update={"score": score_by_id.get(symbol_id, 0.0)}))
        return results

    def _semantic_symbol_candidates(
        self,
        *,
        limit: int,
        kind: str | None = None,
        language: str | None = None,
    ) -> list[SymbolRecord]:
        filters = ["repo_id = ?"]
        params: list[Any] = [self.repo_id]
        if kind:
            filters.append("kind = ?")
            params.append(kind)
        if language:
            filters.append("language = ?")
            params.append(language)
        params.append(limit)
        where_sql = " AND ".join(filters)
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                f"""
                SELECT *, NULL AS score
                FROM symbols
                WHERE {where_sql}
                ORDER BY file_path, start_line
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [_row_to_symbol(row) for row in rows]

    def get_symbol(
        self,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        file_path: str | None = None,
        symbol_name: str | None = None,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        """Retrieve exact symbol metadata and source by byte offsets."""
        if auto_index:
            self._ensure_indexed()
        return self.intel_store.get_symbol(
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            file_path=file_path,
            symbol_name=symbol_name,
        )

    def _get_symbol_local(
        self,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        file_path: str | None = None,
        symbol_name: str | None = None,
    ) -> dict[str, Any]:
        clauses = ["repo_id = ?"]
        params: list[Any] = [self.repo_id]
        if symbol_id:
            clauses.append("symbol_id = ?")
            params.append(symbol_id)
        if qualified_name:
            clauses.append("qualified_name = ?")
            params.append(qualified_name)
        if symbol_name:
            clauses.append("symbol_name = ?")
            params.append(symbol_name)
        if file_path:
            clauses.append("file_path = ?")
            params.append(self._normalize_file_arg(file_path))
        if len(clauses) == 1:
            raise ValueError("symbol_id, qualified_name, symbol_name, or file_path is required")
        with self._connect() as conn:
            self._init_schema(conn)
            row = conn.execute(
                f"SELECT *, NULL AS score FROM symbols WHERE {' AND '.join(clauses)} ORDER BY file_path, start_line LIMIT 1",
                tuple(params),
            ).fetchone()
        if row is None:
            raise LookupError("symbol not found")
        symbol = _row_to_symbol(row)
        path = self.repo_root / symbol.file_path
        try:
            source = path.read_bytes()[symbol.start_byte : symbol.end_byte].decode("utf-8", errors="replace")
        except OSError:
            # The index can reference a file absent from disk (deleted, moved, or
            # snapshot-excluded since indexing). Return the symbol metadata with an
            # empty body so callers (explore relationship resolution, node, ...)
            # degrade instead of crashing on one stale entry.
            source = ""
        emit_product_local("code_symbol_retrieved", repo_id=self.repo_id, kind=symbol.kind)
        return {**symbol.model_dump(mode="json"), "source": source}

    def file_outline(
        self,
        *,
        file_path: str | None = None,
        limit: int = 200,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        """Return compact file or repository symbol outlines."""
        if auto_index:
            self._ensure_indexed()
        params: list[Any] = [self.repo_id]
        where = "repo_id = ?"
        if file_path:
            where += " AND file_path = ?"
            params.append(self._normalize_file_arg(file_path))
        params.append(limit)
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                f"""
                SELECT *, NULL AS score FROM symbols
                WHERE {where}
                ORDER BY file_path, start_line
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            record = _row_to_symbol(row)
            entry: dict[str, Any] = {
                "name": record.symbol_name,
                "kind": record.kind,
                "signature": record.signature,
                "line_start": record.start_line,
                "line_end": record.end_line,
            }
            # Drop qualified_name when it duplicates name (the common case for
            # module-level symbols) — redundant bytes the agent never needs.
            if record.qualified_name and record.qualified_name != record.symbol_name:
                entry["qualified_name"] = record.qualified_name
            grouped.setdefault(record.file_path, []).append(entry)
        return {"repo_id": self.repo_id, "files": grouped, "symbol_count": len(rows)}

    def repo_map(self, *, seed_files: list[str] | None = None, budget_tokens: int = 2000) -> dict[str, Any]:
        """Build an Aider-style PageRank repo map with a token budget."""
        normalized = [self._normalize_file_arg(seed) for seed in seed_files or []]
        result = build_repo_map(self.repo_root, seed_files=normalized, budget_tokens=budget_tokens)
        return result.model_dump(mode="json") | {"mode": "map"}

    def _render_context_code_block(self, symbol: SymbolRecord, source_block: str) -> str:
        block_header = f"### {symbol.qualified_name} ({symbol.file_path}:{symbol.start_line}-{symbol.end_line})"
        return f"{block_header}\n```{symbol.language}\n{source_block}\n```"

    def _context_content_with_candidate(self, lines: list[str], *, block: str | None = None) -> str:
        candidate_lines = list(lines)
        if block is not None:
            candidate_lines.extend([block, ""])
        return "\n".join(candidate_lines).strip()

    def _fit_context_code_block_source(
        self,
        *,
        lines: list[str],
        symbol: SymbolRecord,
        source: str,
        budget_tokens: int,
        max_source_chars: int,
        allow_over_budget: bool,
    ) -> str | None:
        capped_source = hard_cap_chars(source, max_source_chars)
        full_block = self._render_context_code_block(symbol, capped_source)
        if count_tokens(self._context_content_with_candidate(lines, block=full_block)) <= budget_tokens:
            return capped_source

        search_high = min(max_source_chars, max(1, len(source)))
        best_source: str | None = None
        low = 1
        high = max(1, search_high)
        while low <= high:
            mid = (low + high) // 2
            candidate_source = hard_cap_chars(source, mid)
            candidate_block = self._render_context_code_block(symbol, candidate_source)
            if count_tokens(self._context_content_with_candidate(lines, block=candidate_block)) <= budget_tokens:
                best_source = candidate_source
                low = mid + 1
            else:
                high = mid - 1

        if best_source is not None:
            return best_source
        return capped_source if allow_over_budget else None

    def context_pack(
        self,
        *,
        task: str,
        seed_files: list[str] | None = None,
        budget_tokens: int = 4000,
        max_symbols: int = 8,
        auto_index: bool = True,
    ) -> ContextPack:
        """Build a compact, deterministic context bundle with capped entry points and code blocks."""
        if auto_index:
            self._ensure_indexed()
        context_policy = resolve_output_policy("context")
        normalized_seeds = [self._normalize_file_arg(seed) for seed in seed_files or []]
        search_query = task
        lexical_anchor_files = sorted(self._zoekt_candidate_files(search_query, max_files=max(max_symbols * 4, 24)))
        context_seed_files = list(dict.fromkeys([*normalized_seeds, *lexical_anchor_files]))
        repo_map_payload = self.repo_map(seed_files=context_seed_files, budget_tokens=max(200, budget_tokens // 4))
        bounded_max_symbols = max(1, min(max_symbols, context_policy.max_related_symbols))
        symbol_hits = self.search_symbols(
            search_query,
            limit=self._context_pack_search_limit(
                max_symbols=bounded_max_symbols,
                max_symbols_per_file=context_policy.max_symbols_per_file,
            ),
            auto_index=False,
        )
        seed_symbols = self._symbols_for_files(
            context_seed_files,
            limit=max(
                bounded_max_symbols * max(1, context_policy.max_symbols_per_file),
                bounded_max_symbols,
            ),
        )
        selected = self._dedupe_symbols([*seed_symbols, *symbol_hits])
        selected = [symbol for symbol in selected if self._is_context_pack_symbol(symbol)]
        selected = self._prioritize_context_symbols(search_query, selected)
        selected = self._prune_overlapping_context_symbols(selected)
        selected = self._cap_symbols_per_file(selected, max_per_file=max(1, context_policy.max_symbols_per_file))
        selected = selected[:bounded_max_symbols]

        neighbors = self._import_neighbors(context_seed_files)
        # N9: generated/scaffolding files are dropped from "Related Symbols"
        # entirely -- they are noise once the hand-written entry points are
        # surfaced. The cap on related count is applied afterwards.
        neighbor_files = [path for path in self._context_neighbor_files(neighbors) if not is_generated_path(path)][
            : context_policy.max_related_symbols
        ]
        graph_related = self._context_graph_related_symbols(
            selected,
            query=search_query,
            limit=context_policy.max_related_symbols,
            max_symbols_per_file=max(1, context_policy.max_symbols_per_file),
        )
        selected_ids = {item.symbol_id for item in selected}
        related_symbols = [item for item in graph_related if not is_generated_path(item.file_path)]
        related_ids = {item.symbol_id for item in related_symbols} | selected_ids
        if len(related_symbols) < context_policy.max_related_symbols and neighbor_files:
            neighbor_symbol_limit = max(
                1,
                context_policy.max_related_symbols * max(1, context_policy.max_symbols_per_file),
            )
            neighbor_symbols = self._search_symbols_local(
                search_query,
                limit=neighbor_symbol_limit,
                candidate_files=set(neighbor_files),
            )
            if not neighbor_symbols:
                neighbor_symbols = self._symbols_for_files(neighbor_files, limit=neighbor_symbol_limit)
            related_seed = [
                symbol
                for symbol in neighbor_symbols
                if self._is_context_pack_symbol(symbol)
                and symbol.symbol_id not in related_ids
                and not is_generated_path(symbol.file_path)
            ]
            neighbor_related = self._prioritize_context_symbols(search_query, related_seed)
            related_symbols.extend(neighbor_related)
            related_symbols = self._prune_overlapping_context_symbols(related_symbols)
            related_symbols = self._cap_symbols_per_file(
                related_symbols, max_per_file=max(1, context_policy.max_symbols_per_file)
            )
            related_symbols = related_symbols[: context_policy.max_related_symbols]
        entry_points = [self._context_symbol_summary(symbol) for symbol in selected]
        related_summaries = [self._context_symbol_summary(symbol) for symbol in related_symbols]

        lines = ["# Atelier code context", f"task: {task}", ""]
        if repo_map_payload.get("outline"):
            lines.extend(["## repo_map", str(repo_map_payload["outline"]), ""])
        lines.append("## entry_points")
        if entry_points:
            lines.extend(
                [
                    f"- {item['file_path']}:{item['start_line']} — {item['qualified_name']} [{item['kind']}]"
                    for item in entry_points
                ]
            )
        else:
            lines.append("- none")
        lines.append("")
        lines.append("## related_symbols")
        if related_summaries:
            lines.extend(
                [
                    f"- {item['file_path']}:{item['start_line']} — {item['qualified_name']} [{item['kind']}]"
                    for item in related_summaries
                ]
            )
        elif context_policy.include_edges and neighbor_files:
            lines.extend([f"- {item}" for item in neighbor_files])
        else:
            lines.append("- none")
        lines.append("")
        lines.append("## code_blocks")

        packed_symbols: list[SymbolRecord] = []
        code_blocks: list[dict[str, Any]] = []
        naive_tokens = 0
        max_code_blocks = max(1, context_policy.max_code_blocks)
        code_block_candidates = self._dedupe_symbols([*selected, *graph_related])
        naive_file_tokens: dict[str, int] = {}
        for symbol in code_block_candidates:
            if len(packed_symbols) >= max_code_blocks:
                break
            file_tokens = naive_file_tokens.get(symbol.file_path)
            if file_tokens is None:
                # A concurrent autosync reindex may delete the file out from under
                # us; skip its naive-baseline contribution instead of aborting the
                # whole pack. Cache per file so multiple symbols sharing a file do
                # not re-read it.
                with contextlib.suppress(OSError):
                    file_tokens = count_tokens(self._read_file(symbol.file_path))
                naive_file_tokens[symbol.file_path] = file_tokens or 0
            naive_tokens += naive_file_tokens[symbol.file_path]
            symbol_payload = self.get_symbol(symbol_id=symbol.symbol_id, auto_index=False)
            source_block = self._fit_context_code_block_source(
                lines=lines,
                symbol=symbol,
                source=str(symbol_payload.get("source") or ""),
                budget_tokens=budget_tokens,
                max_source_chars=context_policy.max_code_block_chars,
                allow_over_budget=not packed_symbols,
            )
            if source_block is None:
                continue
            block = self._render_context_code_block(symbol, source_block)
            lines.append(block)
            lines.append("")
            packed_symbols.append(symbol)
            code_blocks.append(
                {
                    "symbol_id": symbol.symbol_id,
                    "qualified_name": symbol.qualified_name,
                    "file_path": symbol.file_path,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "language": symbol.language,
                    "source": source_block,
                }
            )
        if not packed_symbols:
            lines.append("- none")
            lines.append("")

        content = "\n".join(lines).strip()
        token_count = count_tokens(content)
        tokens_saved = max(0, naive_tokens - token_count)
        emit_product_local(
            "code_context_retrieved",
            repo_id=self.repo_id,
            operation="context_pack",
            result_count=len(packed_symbols),
        )
        return ContextPack(
            task=task,
            budget_tokens=budget_tokens,
            token_count=token_count,
            tokens_saved_vs_full_files=tokens_saved,
            symbols=packed_symbols,
            entry_points=entry_points,
            related_symbols=related_summaries,
            code_blocks=code_blocks,
            repo_map=str(repo_map_payload.get("outline", "")),
            import_neighbors=neighbor_files,
            content=content,
            telemetry={
                "repo_id": self.repo_id,
                "selected_symbols": len(packed_symbols),
                "entry_points": len(entry_points),
                "related_symbols": len(related_summaries),
                "call_graph_related_symbols": len(graph_related),
                "token_budget_fit": token_count <= budget_tokens,
            },
        )

    def search_text(
        self,
        query: str,
        *,
        path: str = ".",
        limit: int = 50,
        ignore_case: bool = False,
    ) -> list[TextMatch]:
        """Literal text search over the warmed line index, with rg as legacy fallback."""
        search_path = self._resolve_inside_repo(path)
        indexed = self._search_text_index(query, search_path=search_path, limit=limit, ignore_case=ignore_case)
        if indexed:
            return indexed
        if shutil.which("rg") is not None:
            args = [
                "rg",
                "--fixed-strings",
                "--line-number",
                "--column",
                "--no-heading",
                "--color",
                "never",
                "--max-count",
                str(limit),
            ]
            if ignore_case:
                args.append("--ignore-case")
            args.extend([query, str(search_path)])
            proc = subprocess.run(args, check=False, capture_output=True, text=True)
            if proc.returncode not in {0, 1}:
                raise RuntimeError(proc.stderr.strip() or "ripgrep failed")
            return self._parse_rg_output(proc.stdout, limit=limit)
        return self._python_text_search(query, search_path, limit=limit, ignore_case=ignore_case)

    def _search_text_index(
        self,
        query: str,
        *,
        search_path: Path,
        limit: int,
        ignore_case: bool,
    ) -> list[TextMatch]:
        normalized = query.strip()
        if not normalized:
            return []
        fts_query = _safe_fts_query(normalized)
        rel = _safe_relpath(self.repo_root, search_path)
        path_clause = ""
        path_params: list[Any] = []
        if search_path != self.repo_root:
            if search_path.is_file():
                path_clause = " AND file_path = ?"
                path_params.append(rel)
            else:
                path_clause = " AND (file_path = ? OR file_path LIKE ?)"
                path_params.extend([rel, f"{rel.rstrip('/')}/%"])
        query_lower = normalized.lower()
        rows: list[sqlite3.Row] = []
        with self._connect() as conn:
            self._init_schema(conn)
            if fts_query:
                rows = conn.execute(
                    f"""
                    SELECT file_path, line, text
                    FROM file_line_fts
                    WHERE file_line_fts MATCH ? AND repo_id = ?{path_clause}
                    ORDER BY file_path, line
                    LIMIT ?
                    """,
                    tuple([fts_query, self.repo_id, *path_params, max(limit * 8, 80)]),
                ).fetchall()
            if not rows:
                like = f"%{query_lower if ignore_case else normalized}%"
                text_expr = "lower(text)" if ignore_case else "text"
                rows = conn.execute(
                    f"""
                    SELECT file_path, line, text
                    FROM file_line_fts
                    WHERE repo_id = ?{path_clause} AND {text_expr} LIKE ?
                    ORDER BY file_path, line
                    LIMIT ?
                    """,
                    tuple([self.repo_id, *path_params, like, max(limit * 8, 80)]),
                ).fetchall()
        matches: list[TextMatch] = []
        for row in rows:
            text = str(row["text"])
            haystack = text.lower() if ignore_case else text
            needle = query_lower if ignore_case else normalized
            index = haystack.find(needle)
            if index < 0:
                continue
            matches.append(
                TextMatch(
                    file_path=str(row["file_path"]),
                    line=int(row["line"]),
                    column=index + 1,
                    text=text,
                )
            )
            if len(matches) >= limit:
                break
        return matches

    def _should_use_text_substring_search(
        self,
        query: str,
        *,
        mode: SearchMode,
        scope: Literal["repo", "external", "deleted"],
        kind: str | None,
        language: str | None,
        file_glob: str | None,
        provenance_filter: str | None,
    ) -> bool:
        normalized = query.strip()
        if scope != "repo" or mode != "lexical" or kind is not None or provenance_filter is not None:
            return False
        if not (4 <= len(normalized) <= 40):
            return False
        if any(char.isspace() for char in normalized):
            return False
        if "_" in normalized or "." in normalized:
            return False
        if normalized != normalized.lower():
            return False
        return not self._has_exact_repo_symbol(normalized, kind=kind, language=language, file_glob=file_glob)

    def _has_exact_repo_symbol(
        self,
        query: str,
        *,
        kind: str | None,
        language: str | None,
        file_glob: str | None,
    ) -> bool:
        clauses = [
            "repo_id = ?",
            "(symbol_name = ? OR qualified_name = ? OR lower(symbol_name) = ? OR lower(qualified_name) = ?)",
        ]
        params: list[Any] = [self.repo_id, query, query, query.lower(), query.lower()]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if language:
            clauses.append("language = ?")
            params.append(language)
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                f"""
                SELECT file_path
                FROM symbols
                WHERE {" AND ".join(clauses)}
                LIMIT 20
                """,
                tuple(params),
            ).fetchall()
        if file_glob:
            return any(_matches_file_glob(str(row["file_path"]), file_glob) for row in rows)
        return bool(rows)

    def _substring_symbol_hits(
        self,
        query_lower: str,
        *,
        limit: int,
        file_glob: str | None,
    ) -> list[SymbolRecord]:
        like_pattern = f"%{query_lower}%"
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                """
                SELECT *, NULL AS score
                FROM symbols
                WHERE repo_id = ? AND (
                    lower(symbol_name) LIKE ?
                    OR lower(qualified_name) LIKE ?
                    OR lower(signature) LIKE ?
                )
                ORDER BY
                    CASE WHEN kind IN ('class', 'method', 'function') THEN 0 ELSE 1 END,
                    CASE WHEN lower(symbol_name) LIKE ? OR lower(qualified_name) LIKE ? THEN 0 ELSE 1 END,
                    length(symbol_name),
                    file_path,
                    start_line
                LIMIT ?
                """,
                (
                    self.repo_id,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    f"{query_lower}%",
                    f"{query_lower}%",
                    max(limit * 12, 120),
                ),
            ).fetchall()
        hits = [_row_to_symbol(row) for row in rows]
        if file_glob:
            hits = [hit for hit in hits if _matches_file_glob(hit.file_path, file_glob)]
        return hits[:limit]

    def _tool_text_substring_search(
        self,
        query: str,
        *,
        limit: int,
        file_glob: str | None,
        budget_tokens: int,
        since_ts: int | None = None,
        touched_by: str | None = None,
    ) -> dict[str, Any]:
        search_path = "src/atelier" if (self.repo_root / "src" / "atelier").is_dir() else "."
        query_lower = query.lower()
        symbol_hits = self._substring_symbol_hits(query_lower, limit=max(limit * 40, 200), file_glob=file_glob)
        ranked_symbol_hits = sorted(
            (
                item
                for item in symbol_hits
                if query_lower in item.symbol_name.lower() or query_lower in item.qualified_name.lower()
            ),
            key=lambda item: self._text_substring_symbol_score(query_lower, item),
            reverse=True,
        )
        symbol_items = [item.model_dump(mode="json", exclude_none=True) for item in ranked_symbol_hits[:limit]]
        raw_limit = max(limit * 50, 500)
        matches = self.search_text(query, path=search_path, limit=raw_limit, ignore_case=True)
        if file_glob:
            matches = [match for match in matches if _matches_file_glob(match.file_path, file_glob)]
        ranked = sorted(
            matches,
            key=lambda match: self._text_substring_score(query, match),
            reverse=True,
        )
        symbol_paths = {str(item.get("file_path") or "") for item in symbol_items}
        text_items = [
            item
            for item in (self._text_match_search_item(query, match) for match in ranked[:limit])
            if str(item.get("file_path") or "") not in symbol_paths
        ]
        items = self._dedupe_search_items(symbol_items + text_items)
        if since_ts is not None or touched_by is not None:
            changed_files = self._deleted_history_adapter().changed_files(
                since_ts=since_ts,
                touched_by=touched_by,
            )
            items = [item for item in items if str(item.get("file_path") or "") in changed_files]
        payload = self._pack_items_payload(
            items,
            budget_tokens=budget_tokens,
            essential_keys=_SEARCH_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=["snippet", "score", "repo_id"],
            extra_payload={
                "mode": "lexical",
                "snippet": "none",
                "provenance": _LOCAL_PROVENANCE,
                "text_search": True,
            },
        )
        return payload

    def _text_substring_score(self, query: str, match: TextMatch) -> tuple[int, int, int, int]:
        lowered_text = match.text.lower()
        lowered_path = match.file_path.lower()
        query_lower = query.lower()
        definition = int(
            bool(re.search(rf"\b(def|class)\s+[A-Za-z_][A-Za-z0-9_]*{re.escape(query_lower)}", lowered_text))
        )
        symbolish = int(bool(re.search(rf"[A-Za-z_][A-Za-z0-9_]*{re.escape(query_lower)}", lowered_text)))
        path_hit = int(query_lower in lowered_path)
        return (definition, symbolish, path_hit, -len(match.file_path))

    def _text_substring_symbol_score(self, query_lower: str, symbol: SymbolRecord) -> tuple[int, int, int, int, int]:
        symbol_name_lower = symbol.symbol_name.lower()
        qualified_name_lower = symbol.qualified_name.lower()
        preferred_kind = int(symbol.kind in {"class", "method", "function"})
        startswith = int(symbol_name_lower.startswith(query_lower) or qualified_name_lower.startswith(query_lower))
        bare_startswith = int(symbol_name_lower.lstrip("_").startswith(query_lower))
        path_hit = int(query_lower in symbol.file_path.lower())
        return (preferred_kind, startswith, bare_startswith, path_hit, -len(symbol.symbol_name))

    def _text_match_search_item(self, query: str, match: TextMatch) -> dict[str, Any]:
        name = self._text_match_name(query, match.text)
        return {
            "symbol_id": f"text:{match.file_path}:{match.line}:{match.column}",
            "symbol_name": name,
            "qualified_name": name,
            "file_path": match.file_path,
            "kind": "text_match",
            "start_line": match.line,
            "signature": match.text.strip()[:240],
            "provenance": _LOCAL_PROVENANCE,
            "score": 1.0,
        }

    def _text_match_name(self, query: str, text: str) -> str:
        match = re.search(r"\b(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        if match:
            return match.group(1)
        token = re.search(rf"([A-Za-z_][A-Za-z0-9_]*{re.escape(query)}[A-Za-z0-9_]*)", text)
        if token:
            return token.group(1)
        return query

    def _zoekt_candidate_files(
        self,
        query: str,
        *,
        path: str = ".",
        max_files: int = 40,
    ) -> set[str]:
        normalized_query = query.strip()
        if not normalized_query:
            return set()
        try:
            from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return set()
        with contextlib.suppress(Exception):
            search_path = self._resolve_inside_repo(path)
            supervisor = get_zoekt_supervisor(self.repo_root)
            if not supervisor.should_route(search_path):
                return set()
            if not supervisor.health().ok:
                return set()
            result = supervisor.search(
                query=normalized_query,
                search_path=search_path,
                max_files=max(1, min(max_files, 200)),
                max_chars_per_file=800,
                include_outline=False,
            )
            files: set[str] = set()
            for match in result.matches:
                raw_path = Path(match.path)
                resolved = raw_path if raw_path.is_absolute() else (self.repo_root / raw_path)
                with contextlib.suppress(ValueError):
                    rel = _safe_relpath(self.repo_root, resolved.resolve())
                    files.add(rel)
            return files
        return set()

    def _zoekt_text_matches(
        self,
        query: str,
        *,
        limit: int,
        file_glob: str | None = None,
        path: str = ".",
    ) -> list[TextMatch]:
        candidate_files = self._zoekt_candidate_files(query, path=path, max_files=max(1, min(limit, 200)))
        if not candidate_files:
            return []
        matches: list[TextMatch] = []
        lower_query = query.lower()
        for rel in sorted(candidate_files):
            if file_glob and not _matches_file_glob(rel, file_glob):
                continue
            with contextlib.suppress(OSError):
                lines = (self.repo_root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
                for line_no, text in enumerate(lines, start=1):
                    column = text.lower().find(lower_query)
                    if column < 0:
                        continue
                    matches.append(TextMatch(file_path=rel, line=line_no, column=column + 1, text=text))
                    if len(matches) >= limit:
                        return matches
        return matches

    def find_references(
        self,
        query: str | None = None,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        symbol_name: str | None = None,
        file_path: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        file_glob: str | None = None,
        group_by: Literal["file", "caller", "none"] = "file",
        snippet_lines: int = 3,
        limit: int = 20,
        auto_index: bool = True,
        budget_tokens: int = 4000,
    ) -> dict[str, Any]:
        effective_budget_tokens = self._effective_budget_tokens("relation", budget_tokens)
        if auto_index:
            self._ensure_indexed()
        resolved = self._resolve_symbol_targets(
            operation_name="usages",
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=file_path,
            kind=kind,
            language=language,
            file_glob=file_glob,
        )
        if resolved.get("error"):
            return self._pack_single_payload(
                resolved,
                budget_tokens=effective_budget_tokens,
                essential_keys=["error", "message", "matches", "cache_hit", "provenance"],
                optional_keys_in_drop_order=["provenance_breakdown"],
            )
        targets = cast(list[dict[str, Any]], resolved["targets"])
        primary_target = targets[0]
        relation_policy = resolve_output_policy("relation")
        # Bound the intermediate reference set at the source so a very common
        # identifier cannot inflate the pre-sort collection without limit. The
        # final policy/limit caps below still apply as a backstop; this ceiling
        # keeps headroom for dedup + sort while truncating each provider's
        # contribution as it is collected.
        collection_ceiling = max(
            limit,
            relation_policy.max_related_symbols if relation_policy.max_related_symbols > 0 else 0,
        )
        collection_ceiling = max(collection_ceiling * 4, 100)
        references: list[UsageReference] = []
        ceiling_truncated = False
        for target in targets:
            local_refs = self.intel_store.find_references(
                symbol_id=str(target["symbol_id"]),
                qualified_name=str(target["qualified_name"]),
                file_path=str(target["file_path"]),
                symbol_name=str(target["symbol_name"]),
            )
            cross_lang_refs = self._cross_lang_usage_references(target)
            references.extend(local_refs[: max(collection_ceiling - len(references), 0)])
            references.extend(cross_lang_refs[: max(collection_ceiling - len(references), 0)])
            if len(references) >= collection_ceiling:
                # Source-level ceiling fired: the pre-sort set was capped before
                # the downstream policy cap could weigh in, so the result is
                # genuinely incomplete regardless of relation_policy.
                ceiling_truncated = True
                break
        ordered_references = sorted(
            references,
            key=lambda item: (
                item.file_path,
                item.line,
                item.column,
                item.end_line,
                item.end_column,
                item.provenance,
            ),
        )
        items = self._dedupe_usage_items(
            [self._usage_item(reference, snippet_lines=snippet_lines) for reference in ordered_references]
        )
        if not items:
            fallback_query = symbol_name or query or qualified_name
            if fallback_query:
                fallback_provenance = "zoekt_text"
                text_hits = self._zoekt_text_matches(
                    fallback_query,
                    limit=collection_ceiling,
                    file_glob=file_glob,
                )
                if not text_hits:
                    fallback_provenance = "text"
                    text_hits = self.search_text(fallback_query, path=".", limit=collection_ceiling, ignore_case=False)
                items = [
                    {
                        "file_path": match.file_path,
                        "line": match.line,
                        "column": match.column,
                        "end_line": match.line,
                        "end_column": match.column + len(fallback_query),
                        "snippet": match.text,
                        "caller": None,
                        "edge_kind": "text_match",
                        "confidence": 0.25,
                        "provenance": fallback_provenance,
                    }
                    for match in text_hits
                ]
                items = self._dedupe_usage_items(items)
        if file_glob:
            items = [item for item in items if _matches_file_glob(str(item["file_path"]), file_glob)]
        if not relation_policy.include_snippet:
            for item in items:
                item.pop("snippet", None)
        truncated_by_policy = False
        if relation_policy.max_related_symbols > 0 and len(items) > relation_policy.max_related_symbols:
            items = items[: relation_policy.max_related_symbols]
            truncated_by_policy = True
        full_payload = self._build_usages_payload(
            target=primary_target,
            items=items,
            group_by=group_by,
            truncated=truncated_by_policy or ceiling_truncated,
            ambiguity=cast(dict[str, Any] | None, resolved.get("ambiguity")),
        )
        full_total_tokens = self._compute_total_tokens({**full_payload, "tokens_saved": 0})

        def build_payload(packed_items: list[dict[str, Any]]) -> dict[str, Any]:
            return self._finalize_packed_payload(
                self._build_usages_payload(
                    target=primary_target,
                    items=packed_items,
                    group_by=group_by,
                    truncated=truncated_by_policy or ceiling_truncated or len(packed_items) < len(items),
                    ambiguity=cast(dict[str, Any] | None, resolved.get("ambiguity")),
                ),
                full_total_tokens=full_total_tokens,
            )

        return self._fit_items_to_budget(
            items[:limit],
            budget_tokens=effective_budget_tokens,
            essential_keys=_USAGES_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=_USAGES_OPTIONAL_KEYS,
            build_payload=build_payload,
            enforce_protected_top_rank=False,
        )

    def _cross_lang_usage_references(self, target: dict[str, Any]) -> list[UsageReference]:
        symbol_id = str(target.get("symbol_id") or "")
        symbol_name = str(target.get("symbol_name") or "")
        if not symbol_id:
            return []
        refs: list[UsageReference] = []
        for edge in self._cross_lang_store().query_by_target_symbol(
            tgt_symbol_id=symbol_id, tgt_symbol_name=symbol_name
        ):
            refs.append(
                UsageReference(
                    file_path=edge.src_file_path,
                    line=edge.src_line,
                    column=1,
                    end_line=edge.src_line,
                    end_column=1,
                    caller=edge.src_qualified_name,
                    provenance="cross_lang",
                    edge_kind=edge.edge_kind,
                    confidence=edge.confidence,
                )
            )
        return refs

    def _tool_call_graph(
        self,
        direction: CallGraphDirection,
        *,
        query: str | None = None,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        symbol_name: str | None = None,
        file_path: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        depth: int = 1,
        limit: int = 20,
        snapshot: bool = False,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        effective_budget_tokens = self._effective_budget_tokens(direction, budget_tokens)
        if auto_index:
            self._ensure_indexed()
        self._sync_symbol_intel()
        normalized_file_path = self._normalize_file_arg(file_path) if file_path else None
        bounded_depth = max(1, depth)
        cache_args = {
            "direction": direction,
            "query": query,
            "symbol_id": symbol_id,
            "qualified_name": qualified_name,
            "symbol_name": symbol_name,
            "file_path": normalized_file_path,
            "kind": kind,
            "language": language,
            "depth": bounded_depth,
            "limit": limit,
            "snapshot": snapshot,
            "budget_tokens": effective_budget_tokens,
        }
        hit, cached = self._cache_get(f"code.{direction}", cache_args)
        if hit and cached is not None:
            return self._mark_cache_hit(cached)
        resolved = self._resolve_symbol_targets(
            operation_name=direction,
            query=query,
            symbol_id=symbol_id,
            qualified_name=qualified_name,
            symbol_name=symbol_name,
            file_path=normalized_file_path,
            kind=kind,
            language=language,
            file_glob=None,
        )
        if resolved.get("error"):
            return self._pack_single_payload(
                resolved,
                budget_tokens=effective_budget_tokens,
                essential_keys=["error", "message", "matches", "cache_hit", "provenance"],
                optional_keys_in_drop_order=["provenance_breakdown"],
            )
        targets = cast(list[dict[str, Any]], resolved["targets"])
        primary_target = targets[0]
        lookup = self.intel_store.find_callers if direction == "callers" else self.intel_store.find_callees
        traversals: list[CallGraphTraversalResult] = []
        for target in targets:
            traversal = traverse_call_graph(
                target,
                direction=direction,
                depth=bounded_depth,
                limit=limit,
                snapshot=snapshot,
                lookup_neighbors=lambda current_symbol_id: lookup(symbol_id=current_symbol_id),
            )
            if traversal.data_status == "unavailable" and direction == "callers":
                fallback = self._fallback_callers_from_references(
                    target=target,
                    limit=limit,
                )
                if fallback.data_status == "available":
                    traversal = fallback
            traversals.append(traversal)
        if len(traversals) == 1:
            traversal = traversals[0]
        else:
            nodes_by_identity: dict[tuple[str, str, int, int, str], CallGraphNode] = {}
            edges_by_key: dict[tuple[str, str, int], CallGraphEdge] = {}
            merged_truncated = False
            status_rank = {"unavailable": 0, "empty": 1, "available": 2}
            merged_status = "unavailable"
            for current in traversals:
                merged_truncated = merged_truncated or current.truncated
                if status_rank[current.data_status] > status_rank[merged_status]:
                    merged_status = current.data_status
                for node in current.nodes:
                    node_key = (
                        node.symbol_id,
                        node.file_path,
                        node.start_line,
                        node.end_line,
                        node.qualified_name,
                    )
                    nodes_by_identity[node_key] = node
                for edge in current.edges:
                    key = (edge.caller_symbol_id, edge.callee_symbol_id, edge.depth)
                    edges_by_key[key] = edge
            merged_nodes = sorted(
                nodes_by_identity.values(),
                key=lambda item: (item.file_path, item.start_line, item.symbol_id),
            )
            merged_edges = sorted(
                edges_by_key.values(),
                key=lambda item: (item.depth, item.caller_symbol_id, item.callee_symbol_id),
            )
            if merged_edges:
                merged_status = "available"
            merged_message = (
                "routed call edge data is unavailable"
                if merged_status == "unavailable"
                else "no related call edges were found" if merged_status == "empty" else None
            )
            merged_snapshot = None
            if snapshot:
                merged_snapshot = {
                    "direction": direction,
                    "depth": bounded_depth,
                    "target_symbol_id": str(primary_target["symbol_id"]),
                    "target_count": len(targets),
                    "node_count": len(merged_nodes),
                    "edge_count": len(merged_edges),
                }
            traversal = CallGraphTraversalResult(
                nodes=merged_nodes,
                edges=merged_edges,
                truncated=merged_truncated,
                data_status=cast(Any, merged_status),
                message=merged_message,
                snapshot=merged_snapshot,
            )
        payload = build_call_graph_payload(
            primary_target,
            direction=direction,
            depth=bounded_depth,
            result=traversal,
        )
        ambiguity = cast(dict[str, Any] | None, resolved.get("ambiguity"))
        if ambiguity is not None:
            payload["ambiguity"] = ambiguity
        relation_policy = resolve_output_policy("relation")
        if relation_policy.max_related_symbols > 0:
            # Respect the caller's explicit limit when it exceeds the compact-policy
            # default (12). Without this, passing limit=50 still silently truncates
            # to 12 because the compact policy runs after the traversal.
            max_related = max(limit, relation_policy.max_related_symbols)
            related_before = len(cast(list[dict[str, Any]], payload.get("related", [])))
            edges_before = len(cast(list[dict[str, Any]], payload.get("edges", [])))
            payload["related"] = cast(list[dict[str, Any]], payload.get("related", []))[:max_related]
            payload["edges"] = cast(list[dict[str, Any]], payload.get("edges", []))[:max_related]
            payload["related_count"] = len(cast(list[dict[str, Any]], payload.get("related", [])))
            payload["edge_count"] = len(cast(list[dict[str, Any]], payload.get("edges", [])))
            payload["truncated"] = (
                bool(payload.get("truncated", False)) or related_before > max_related or edges_before > max_related
            )
        if not relation_policy.include_edges:
            payload["edges"] = []
            payload["edge_count"] = 0
        payload["provenance"] = str(primary_target.get("provenance") or _LOCAL_PROVENANCE)
        packed = self._pack_single_payload(
            payload,
            budget_tokens=effective_budget_tokens,
            essential_keys=_CALL_GRAPH_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=_CALL_GRAPH_OPTIONAL_KEYS,
        )
        if "related" not in packed and "related" in payload:
            packed["related"] = payload["related"]
            packed["related_count"] = payload.get("related_count", len(cast(list[Any], payload["related"])))
        if "edges" not in packed and "edges" in payload:
            packed["edges"] = payload["edges"]
            packed["edge_count"] = payload.get("edge_count", len(cast(list[Any], payload["edges"])))
        # Re-apply shortening to restored fields (they bypassed _finalize_packed_payload shortening)
        packed = apply_field_name_shortening(packed)
        if "data_status" not in packed and "data_status" in payload:
            packed["data_status"] = payload["data_status"]
        if "error" not in packed:
            self._cache_set(f"code.{direction}", cache_args, packed)
        return packed

    def _neighborhood(
        self,
        relation: Literal["self", "callers", "callees", "refs"],
        *,
        query: str | None = None,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        symbol_name: str | None = None,
        file_path: str | None = None,
        line: int | None = None,
        kind: str | None = None,
        language: str | None = None,
        file_glob: str | None = None,
        depth: int = 1,
        limit: int = 20,
        group_by: Literal["file", "caller", "none"] = "file",
        snippet_lines: int = 3,
        snapshot: bool = False,
        budget_tokens: int = 4000,
        auto_index: bool = True,
    ) -> dict[str, Any]:
        """Unified symbol-graph access: one resolve+project entry over the shared
        SCIP index. ``relation`` selects the projection:

        * ``self``    -- the symbol's own definition (``depth``/``group_by``/
          ``snippet_lines`` ignored).
        * ``callers`` -- inbound call edges (transitive via ``depth``).
        * ``callees`` -- outbound call edges (transitive via ``depth``).
        * ``refs``    -- all references/usages (flat; ``depth`` ignored).

        ``node``/``callers``/``callees``/``usages`` and ``explore``'s relationship
        pass all funnel through here, so symbol-graph access has a single code
        path. Each branch still delegates to its existing engine method, so
        payloads are unchanged -- this is the seam the projections collapse into.
        """
        if relation == "self":
            return self.tool_symbol(
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                symbol_name=symbol_name,
                file_path=file_path,
                line=line,
                budget_tokens=budget_tokens,
                auto_index=auto_index,
            )
        if relation in ("callers", "callees"):
            return self._tool_call_graph(
                relation,
                query=query,
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                symbol_name=symbol_name,
                file_path=file_path,
                kind=kind,
                language=language,
                depth=depth,
                limit=limit,
                snapshot=snapshot,
                budget_tokens=budget_tokens,
                auto_index=auto_index,
            )
        if relation == "refs":
            return self.find_references(
                query=query,
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                symbol_name=symbol_name,
                file_path=file_path,
                kind=kind,
                language=language,
                file_glob=file_glob,
                group_by=group_by,
                snippet_lines=snippet_lines,
                limit=limit,
                auto_index=auto_index,
                budget_tokens=budget_tokens,
            )
        raise ValueError(f"unknown neighborhood relation: {relation!r}")

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if readonly:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=30.0)
        else:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
        self._apply_pragmas(conn, readonly=readonly)
        conn.row_factory = sqlite3.Row
        return conn

    def _apply_pragmas(self, conn: sqlite3.Connection, *, readonly: bool = False) -> None:
        conn.execute("PRAGMA busy_timeout = 30000")
        if readonly:
            return
        row = conn.execute("PRAGMA journal_mode").fetchone()
        current_mode = str(row[0]).lower() if row else ""
        if current_mode != "wal":
            # WAL gives concurrent readers + a single writer across processes, so
            # reads never get "database is locked". The switch only fails while
            # another connection holds a lock; busy_timeout (set above) lets it
            # wait for a quiet moment, and once flipped WAL persists on the file.
            with contextlib.suppress(sqlite3.OperationalError):
                result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
                if result is not None and str(result[0]).lower() != "wal":
                    logger.debug("code index WAL switch deferred (journal_mode=%s)", result[0])
        conn.execute("PRAGMA synchronous = NORMAL")

    def connection(self) -> sqlite3.Connection:
        conn = self._connect()
        self._init_schema(conn)
        return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        if self._schema_ready:
            return
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS engine_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
                repo_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                language TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL DEFAULT 0,
                indexed_at TEXT NOT NULL,
                PRIMARY KEY (repo_id, file_path)
            );
            CREATE TABLE IF NOT EXISTS symbols (
                symbol_id TEXT PRIMARY KEY,
                repo_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                language TEXT NOT NULL,
                symbol_name TEXT NOT NULL,
                qualified_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                signature TEXT NOT NULL,
                start_byte INTEGER NOT NULL,
                end_byte INTEGER NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                parent_symbol TEXT,
                doc_summary TEXT,
                content_hash TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS symbol_fts USING fts5(
                symbol_id UNINDEXED,
                name,
                qualified_name,
                signature,
                file_path UNINDEXED,
                source
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS file_line_fts USING fts5(
                repo_id UNINDEXED,
                file_path UNINDEXED,
                line UNINDEXED,
                text
            );
            CREATE TABLE IF NOT EXISTS imports (
                repo_id TEXT NOT NULL,
                source_file TEXT NOT NULL,
                raw_import TEXT NOT NULL,
                target_file TEXT,
                UNIQUE(repo_id, source_file, raw_import, target_file)
            );
            CREATE TABLE IF NOT EXISTS "references" (
                repo_id TEXT NOT NULL,
                symbol_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                line INTEGER NOT NULL,
                column INTEGER NOT NULL,
                end_column INTEGER NOT NULL,
                enclosing_symbol_name TEXT,
                enclosing_qualified_name TEXT,
                snippet TEXT NOT NULL,
                UNIQUE(repo_id, symbol_name, file_path, line, column, enclosing_qualified_name)
            );
            CREATE TABLE IF NOT EXISTS call_edges (
                repo_id TEXT NOT NULL,
                caller_symbol_name TEXT NOT NULL,
                caller_qualified_name TEXT NOT NULL,
                caller_file_path TEXT NOT NULL,
                caller_start_line INTEGER NOT NULL,
                caller_end_line INTEGER NOT NULL,
                callee_name TEXT NOT NULL,
                call_line INTEGER NOT NULL,
                call_column INTEGER NOT NULL,
                snippet TEXT NOT NULL,
                UNIQUE(repo_id, caller_qualified_name, caller_file_path, call_line, call_column, callee_name)
            );
            CREATE INDEX IF NOT EXISTS idx_symbols_repo_file ON symbols(repo_id, file_path);
            CREATE INDEX IF NOT EXISTS idx_symbols_repo_name ON symbols(repo_id, symbol_name);
            CREATE INDEX IF NOT EXISTS idx_imports_target ON imports(repo_id, target_file);
            CREATE INDEX IF NOT EXISTS idx_references_name ON "references"(repo_id, symbol_name);
            CREATE INDEX IF NOT EXISTS idx_references_file ON "references"(repo_id, file_path);
            CREATE INDEX IF NOT EXISTS idx_call_edges_callee ON call_edges(repo_id, callee_name);
            CREATE INDEX IF NOT EXISTS idx_call_edges_caller ON call_edges(repo_id, caller_file_path, caller_start_line);
            CREATE TABLE IF NOT EXISTS commit_chunks (
                commit_sha     TEXT PRIMARY KEY,
                author_date    INTEGER NOT NULL,
                files_touched  TEXT NOT NULL,
                symbols_touched TEXT,
                summary        TEXT NOT NULL,
                summary_model  TEXT NOT NULL,
                embedding      BLOB,
                index_version  INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_commit_author_date ON commit_chunks(author_date);
            CREATE INDEX IF NOT EXISTS idx_commit_files ON commit_chunks(files_touched);
            """)
        # Migration: older DBs predate the files.mtime_ns column used to fast-skip
        # unchanged files during incremental reindex. CREATE TABLE IF NOT EXISTS
        # never adds a column to an existing table, so add it here when absent.
        file_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(files)")}
        if "mtime_ns" not in file_columns:
            conn.execute("ALTER TABLE files ADD COLUMN mtime_ns INTEGER NOT NULL DEFAULT 0")
        conn.execute("INSERT OR IGNORE INTO engine_state(key, value) VALUES ('index_version', '0')")
        self._schema_ready = True

    def index_ready(self) -> bool:
        """True once the symbol index has at least one indexed file for this repo."""
        if self._index_ready_cached:
            return True
        try:
            with self._connect() as conn:
                self._init_schema(conn)
                row = conn.execute("SELECT 1 FROM files WHERE repo_id = ? LIMIT 1", (self.repo_id,)).fetchone()
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return False
        if row is not None:
            self._index_ready_cached = True
            return True
        return False

    def _ensure_autosync_worker_alive(self) -> None:
        if not self._autosync_enabled or self._autosync_stop.is_set():
            return
        t = self._autosync_thread
        if t is not None and t.is_alive():
            return
        self._autosync_thread = None
        self._start_autosync_worker()

    def _ensure_indexed(self) -> None:
        if self.index_ready():
            # Change detection + reindex is the background autosync worker's job
            # (it polls every _autosync_poll_ms). Running it inline here would
            # stat every source file in the repo on every read tool call -- the
            # per-call tax that made grep/read/explore slow on large repos. Keep
            # the worker alive and let it own resync; files just edited are
            # already current via the targeted _reindex_files after each edit.
            if self._autosync_enabled:
                self._ensure_autosync_worker_alive()
            self._ensure_lineage_ready()
            return
        if self._autosync_enabled:
            self._ensure_autosync_worker_alive()
            return
        # autosync always on in practice; index will be built by the worker

    def _excluded(self, path: Path, patterns: list[str]) -> bool:
        rel = _safe_relpath(self.repo_root, path)
        return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)

    def _normalize_file_arg(self, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            return _safe_relpath(self.repo_root, path)
        return str(path)

    def _resolve_inside_repo(self, value: str) -> Path:
        path = Path(value)
        resolved = path.resolve() if path.is_absolute() else (self.repo_root / path).resolve()
        try:
            resolved.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError(f"path escape denied: {value}") from exc
        return resolved

    def _extract_python_symbols(self, source: str) -> list[_ExtractedSymbol]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        offsets = _line_offsets(source)
        lines = source.splitlines()
        symbols: list[_ExtractedSymbol] = []

        def line_text(line_no: int) -> str:
            if 1 <= line_no <= len(lines):
                return lines[line_no - 1].strip()
            return ""

        def add_node(node: ast.AST, name: str, kind: str, parent: str | None) -> None:
            start_line = int(getattr(node, "lineno", 1))
            end_line = int(getattr(node, "end_lineno", start_line))
            col = int(getattr(node, "col_offset", 0))
            end_col = int(getattr(node, "end_col_offset", 0))
            start_byte = offsets[max(0, start_line - 1)] + col
            end_byte = offsets[max(0, end_line - 1)] + end_col if end_col else offsets[min(end_line, len(offsets) - 1)]
            qualified = f"{parent}.{name}" if parent else name
            doc = (
                ast.get_docstring(node)
                if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                else None
            )
            symbols.append(
                _ExtractedSymbol(
                    name=name,
                    qualified_name=qualified,
                    kind=kind,
                    signature=line_text(start_line),
                    start_byte=start_byte,
                    end_byte=max(start_byte, end_byte),
                    start_line=start_line,
                    end_line=end_line,
                    parent_symbol=parent,
                    doc_summary=(stripped.splitlines()[0][:200] if doc and (stripped := doc.strip()) else None),
                )
            )

        def walk_body(body: list[ast.stmt], parent: str | None = None) -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    add_node(node, node.name, "class", parent)
                    walk_body(node.body, node.name if parent is None else f"{parent}.{node.name}")
                elif isinstance(node, ast.AsyncFunctionDef):
                    add_node(node, node.name, "method" if parent else "async_function", parent)
                elif isinstance(node, ast.FunctionDef):
                    add_node(node, node.name, "method" if parent else "function", parent)
                elif parent is None and isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            add_node(node, target.id, "variable", None)
                elif parent is None and isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    add_node(node, node.target.id, "variable", None)

        walk_body(tree.body)
        return sorted(symbols, key=lambda item: (item.start_line, item.qualified_name))

    @staticmethod
    def _python_call_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = CodeContextEngine._python_call_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return CodeContextEngine._python_call_name(node.func)
        return None

    def _extract_tag_symbols(self, path: Path, source: str, language: str) -> list[_ExtractedSymbol]:
        del language
        try:
            tags = [tag for tag in extract_tags(path) if tag.kind == "definition"]
        except (OSError, SyntaxError):
            return []
        offsets = _line_offsets(source)
        lines = source.splitlines()
        sorted_tags = sorted(tags, key=lambda tag: (tag.line, tag.name))
        symbols: list[_ExtractedSymbol] = []
        for index, tag in enumerate(sorted_tags):
            start_line = max(1, tag.line)
            next_line = sorted_tags[index + 1].line - 1 if index + 1 < len(sorted_tags) else start_line
            end_line = max(start_line, min(next_line, len(lines)))
            start_byte = offsets[start_line - 1] if start_line - 1 < len(offsets) else tag.byte_range[0]
            end_byte = offsets[end_line] if end_line < len(offsets) else tag.byte_range[1]
            signature = lines[start_line - 1].strip() if start_line <= len(lines) else tag.name
            symbols.append(
                _ExtractedSymbol(
                    name=tag.name,
                    qualified_name=tag.name,
                    kind=self._kind_from_signature(signature),
                    signature=signature,
                    start_byte=start_byte,
                    end_byte=max(start_byte, end_byte),
                    start_line=start_line,
                    end_line=end_line,
                )
            )
        return symbols

    def _python_imports(self, path: Path, source: str) -> list[tuple[str, str | None]]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        imports: list[tuple[str, str | None]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append((alias.name, self._resolve_python_module(path.parent, alias.name)))
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((node.module, self._resolve_python_module(path.parent, node.module)))
        return imports

    def _javascript_imports(self, path: Path, source: str) -> list[tuple[str, str | None]]:
        imports: list[tuple[str, str | None]] = []
        for match in _JS_IMPORT_RE.finditer(source):
            raw = next(group for group in match.groups() if group)
            target = None
            if raw.startswith("."):
                target = self._resolve_relative_module(path.parent, raw, [".ts", ".tsx", ".js", ".jsx"])
            imports.append((raw, target))
        return imports

    def _resolve_python_module(self, base: Path, module: str) -> str | None:
        parts = module.split(".")
        search_bases: list[Path] = []
        for candidate in [base, *base.parents, self.repo_root, self.repo_root / "src"]:
            resolved = candidate.resolve()
            if resolved not in search_bases:
                search_bases.append(resolved)
        for search_base in search_bases:
            candidate = search_base / Path(*parts).with_suffix(".py")
            if candidate.is_file():
                return _safe_relpath(self.repo_root, candidate)
            package = search_base / Path(*parts) / "__init__.py"
            if package.is_file():
                return _safe_relpath(self.repo_root, package)
            # src-layout imports often omit the top-level src directory while
            # file-local parent probing starts below it. Also handle package-root
            # candidates such as atelier.core.foo -> src/atelier/core/foo.py.
            src_candidate = self.repo_root / "src" / Path(*parts).with_suffix(".py")
            if src_candidate.is_file():
                return _safe_relpath(self.repo_root, src_candidate)
            src_package = self.repo_root / "src" / Path(*parts) / "__init__.py"
            if src_package.is_file():
                return _safe_relpath(self.repo_root, src_package)
        return None

    def _resolve_relative_module(self, base: Path, raw: str, suffixes: list[str]) -> str | None:
        candidate_base = (base / raw).resolve()
        candidates: list[Path] = []
        if candidate_base.suffix:
            candidates.append(candidate_base)
        else:
            candidates.extend(candidate_base.with_suffix(suffix) for suffix in suffixes)
            candidates.extend(candidate_base / f"index{suffix}" for suffix in suffixes)
            candidates.extend(candidate_base / f"mod{suffix}" for suffix in suffixes)
        for candidate in candidates:
            if candidate.is_file():
                return _safe_relpath(self.repo_root, candidate)
        return None

    def _kind_from_signature(self, signature: str) -> str:
        stripped = signature.lstrip()
        if stripped.startswith("class "):
            return "class"
        if stripped.startswith(("interface ", "type ")):
            return "type"
        if stripped.startswith(("function ", "func ", "fn ")):
            return "function"
        if stripped.startswith(("struct ", "enum ", "trait ")):
            return "class"
        return "variable"

    def _symbols_for_files(self, file_paths: list[str], *, limit: int) -> list[SymbolRecord]:
        if not file_paths:
            return []
        placeholders = ",".join("?" for _ in file_paths)
        params: list[Any] = [self.repo_id, *file_paths, limit]
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                f"""
                SELECT *, NULL AS score FROM symbols
                WHERE repo_id = ? AND file_path IN ({placeholders})
                ORDER BY file_path, start_line
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [_row_to_symbol(row) for row in rows]

    def _dedupe_symbols(self, symbols: list[SymbolRecord]) -> list[SymbolRecord]:
        seen: set[str] = set()
        output: list[SymbolRecord] = []
        for symbol in symbols:
            if symbol.symbol_id in seen:
                continue
            seen.add(symbol.symbol_id)
            output.append(symbol)
        return output

    def _cap_symbols_per_file(self, symbols: list[SymbolRecord], *, max_per_file: int) -> list[SymbolRecord]:
        if max_per_file <= 0:
            return symbols
        counts: dict[str, int] = {}
        output: list[SymbolRecord] = []
        for symbol in symbols:
            seen = counts.get(symbol.file_path, 0)
            if seen >= max_per_file:
                continue
            counts[symbol.file_path] = seen + 1
            output.append(symbol)
        return output

    def _context_pack_search_limit(self, *, max_symbols: int, max_symbols_per_file: int) -> int:
        return max(
            max_symbols,
            max_symbols * max(2, max_symbols_per_file),
        )

    def _is_noise_symbol_kind(self, kind: str) -> bool:
        return kind.strip().lower() in {"import", "export"}

    def _is_context_pack_symbol(self, symbol: SymbolRecord) -> bool:
        if self._is_noise_symbol_kind(symbol.kind):
            return False
        if symbol.provenance == "commit" or symbol.kind == "commit":
            return False
        rel = str(symbol.file_path or "").strip()
        if not rel:
            return False
        with contextlib.suppress(ValueError):
            if self._resolve_inside_repo(rel).is_file():
                return True
        return False

    def _symbol_matches_compound_query(self, query_terms: list[str], symbol: SymbolRecord) -> bool:
        if len(query_terms) < 2:
            return False
        lexical = f"{symbol.symbol_name} {symbol.qualified_name} {symbol.signature}".lower()
        matched = sum(1 for term in query_terms if term and term in lexical)
        return matched >= min(len(query_terms), 3)

    def _symbol_popularity_scores(self, symbols: list[SymbolRecord]) -> dict[str, float]:
        """Batch-compute a usage-frequency popularity score per candidate symbol.

        Popularity blends indexed reference counts (the ``references`` table,
        keyed by ``symbol_name``) with caller counts (``call_edges``, keyed by
        ``callee_name``). Both lookups hit existing indexes, so this is cheap and
        always available -- it never requires git. The raw counts are squashed
        into [0, 1) so a wildly-popular symbol cannot dominate; popularity is
        only ever consumed as a low-priority ranking tiebreaker.
        """
        names = sorted({symbol.symbol_name for symbol in symbols if symbol.symbol_name})
        if not names:
            return {}
        placeholders = ",".join("?" for _ in names)
        ref_counts: dict[str, int] = {}
        caller_counts: dict[str, int] = {}
        try:
            with self._connect() as conn:
                self._init_schema(conn)
                for row in conn.execute(
                    f'SELECT symbol_name, COUNT(*) AS n FROM "references" '
                    f"WHERE repo_id = ? AND symbol_name IN ({placeholders}) GROUP BY symbol_name",
                    (self.repo_id, *names),
                ).fetchall():
                    ref_counts[str(row["symbol_name"])] = int(row["n"])
                for row in conn.execute(
                    f"SELECT callee_name, COUNT(*) AS n FROM call_edges "
                    f"WHERE repo_id = ? AND callee_name IN ({placeholders}) GROUP BY callee_name",
                    (self.repo_id, *names),
                ).fetchall():
                    caller_counts[str(row["callee_name"])] = int(row["n"])
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return {}
        scores: dict[str, float] = {}
        for symbol in symbols:
            raw = ref_counts.get(symbol.symbol_name, 0) + caller_counts.get(symbol.symbol_name, 0)
            # Diminishing-returns squash into [0, 1): popular-but-correct symbols
            # rise as a tiebreaker without ever outweighing match quality.
            scores[symbol.symbol_id] = raw / (raw + 5.0) if raw > 0 else 0.0
        return scores

    def _symbol_churn_scores(self, symbols: list[SymbolRecord]) -> dict[str, float]:
        """Per-symbol churn score in [0, 1] from the optional churn provider.

        Returns an empty mapping (no churn signal) unless a provider is injected,
        keeping ranking free of git/blame cost by default. Churn, like
        popularity, is consumed only as a low-priority ranking tiebreaker.
        """
        provider = self._churn_score_provider
        if provider is None or not symbols:
            return {}
        try:
            raw = provider(symbols)
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return {}
        return {symbol_id: max(0.0, min(1.0, float(value))) for symbol_id, value in raw.items()}

    def _context_symbol_signals(self, symbols: list[SymbolRecord]) -> dict[str, float]:
        """Combine usage-frequency and churn into a single tiebreaker per symbol."""
        if not symbols:
            return {}
        popularity = self._symbol_popularity_scores(symbols)
        churn = self._symbol_churn_scores(symbols)
        if not popularity and not churn:
            return {}
        combined: dict[str, float] = {}
        for symbol in symbols:
            combined[symbol.symbol_id] = popularity.get(symbol.symbol_id, 0.0) + churn.get(symbol.symbol_id, 0.0)
        return combined

    def _context_symbol_rank(
        self,
        query: str,
        symbol: SymbolRecord,
        *,
        popularity: float = 0.0,
    ) -> tuple[int, int, int, int, int, int, float, float, str, int, str]:
        normalized_query = query.strip().lower()
        symbol_name = symbol.symbol_name.lower()
        qualified_name = symbol.qualified_name.lower()
        query_terms = _identifier_terms(normalized_query)
        exact = int(normalized_query in {symbol_name, qualified_name})
        prefix = int(
            bool(normalized_query)
            and (symbol_name.startswith(normalized_query) or qualified_name.startswith(normalized_query))
        )
        compound = int(self._symbol_matches_compound_query(query_terms[:8], symbol))
        term_prefix_hits = sum(
            1 for term in query_terms[:8] if term and (symbol_name.startswith(term) or qualified_name.startswith(term))
        )
        tool_query = any(term in {"mcp", "tool"} for term in query_terms)
        tool_boost = 0
        if tool_query:
            if "mcp_server" in symbol.file_path.lower():
                tool_boost += 3
            if symbol_name.startswith("tool_"):
                tool_boost += 2
            if "mcp" in qualified_name:
                tool_boost += 1
        # N9: generated/scaffolding files rank last. This demotion sits AFTER the
        # authoritative exact-hit signal, so an exact symbol that legitimately
        # lives in a generated file is still surfaced; it only sinks generated
        # candidates beneath equally- or weaker-matched hand-written code.
        not_generated = 0 if is_generated_path(symbol.file_path) else 1
        # G7: popularity/churn is positioned AFTER every match-quality signal
        # (exact/prefix/compound/term/tool) and after the lexical/semantic score,
        # so it can only ever break ties among otherwise-equal candidates. An
        # exact-symbol hit (exact=1) is always ranked above any non-exact symbol
        # regardless of how popular the non-exact one is.
        return (
            exact,
            not_generated,
            prefix,
            compound,
            term_prefix_hits,
            tool_boost,
            float(symbol.score or 0.0),
            float(popularity),
            symbol.file_path,
            symbol.start_line,
            symbol.qualified_name,
        )

    def _prioritize_context_symbols(self, query: str, symbols: list[SymbolRecord]) -> list[SymbolRecord]:
        signals = self._context_symbol_signals(symbols)
        ranks = {
            symbol.symbol_id: self._context_symbol_rank(query, symbol, popularity=signals.get(symbol.symbol_id, 0.0))
            for symbol in symbols
        }
        return sorted(
            symbols,
            key=lambda symbol: (
                -ranks[symbol.symbol_id][0],
                -ranks[symbol.symbol_id][1],
                -ranks[symbol.symbol_id][2],
                -ranks[symbol.symbol_id][3],
                -ranks[symbol.symbol_id][4],
                -ranks[symbol.symbol_id][5],
                -ranks[symbol.symbol_id][6],
                -ranks[symbol.symbol_id][7],
                ranks[symbol.symbol_id][8],
                ranks[symbol.symbol_id][9],
                ranks[symbol.symbol_id][10],
                symbol.symbol_id,
            ),
        )

    def _prune_overlapping_context_symbols(self, symbols: list[SymbolRecord]) -> list[SymbolRecord]:
        kept: list[SymbolRecord] = []
        for symbol in symbols:
            if any(self._context_symbols_are_redundant(existing, symbol) for existing in kept):
                continue
            kept.append(symbol)
        return kept

    def _context_symbols_are_redundant(self, kept: SymbolRecord, candidate: SymbolRecord) -> bool:
        if self._normalize_file_arg(kept.file_path) != self._normalize_file_arg(candidate.file_path):
            return False
        kept_contains_candidate = self._context_symbol_contains(kept, candidate)
        candidate_contains_kept = self._context_symbol_contains(candidate, kept)
        return kept_contains_candidate or candidate_contains_kept

    def _context_symbol_contains(self, outer: SymbolRecord, inner: SymbolRecord) -> bool:
        outer_start = int(outer.start_line)
        outer_end = max(outer_start, int(outer.end_line))
        inner_start = int(inner.start_line)
        inner_end = max(inner_start, int(inner.end_line))
        return outer_start <= inner_start and outer_end >= inner_end

    def _context_neighbor_files(self, neighbors: list[str]) -> list[str]:
        files: list[str] = []
        for neighbor in neighbors:
            candidate = str(neighbor or "").strip()
            if not candidate:
                continue
            path = self.repo_root / candidate
            if path.is_file():
                files.append(candidate)
        return sorted(set(files))

    def _context_symbol_from_call_graph_node(self, node: CallGraphNode) -> SymbolRecord | None:
        node_file = str(node.file_path or "").strip()
        if not node_file:
            return None
        normalized_file = self._normalize_file_arg(node_file)
        with self._connect() as conn:
            self._init_schema(conn)
            node_symbol_id = str(node.symbol_id or "").strip()
            if node_symbol_id and not node_symbol_id.startswith(("local-call::", "local-callee::", "ref::")):
                row = conn.execute(
                    """
                    SELECT *, NULL AS score FROM symbols
                    WHERE repo_id = ? AND symbol_id = ?
                    LIMIT 1
                    """,
                    (self.repo_id, node_symbol_id),
                ).fetchone()
                if row is not None:
                    return _row_to_symbol(row)
            row = conn.execute(
                """
                SELECT *, NULL AS score FROM symbols
                WHERE repo_id = ? AND file_path = ? AND start_line = ?
                  AND (qualified_name = ? OR symbol_name = ?)
                ORDER BY
                  CASE
                    WHEN qualified_name = ? THEN 0
                    WHEN symbol_name = ? THEN 1
                    ELSE 2
                  END,
                  (end_line - start_line) ASC,
                  end_line ASC,
                  symbol_id ASC
                LIMIT 1
                """,
                (
                    self.repo_id,
                    normalized_file,
                    int(node.start_line),
                    str(node.qualified_name),
                    str(node.symbol_name),
                    str(node.qualified_name),
                    str(node.symbol_name),
                ),
            ).fetchone()
        if row is None:
            return None
        return _row_to_symbol(row)

    def _context_graph_related_symbols(
        self,
        selected: list[SymbolRecord],
        *,
        query: str,
        limit: int,
        max_symbols_per_file: int,
    ) -> list[SymbolRecord]:
        if limit <= 0 or not selected:
            return []
        relation_priority: dict[str, int] = {}
        candidates_by_id: dict[str, SymbolRecord] = {}
        selected_ids = {symbol.symbol_id for symbol in selected}
        for symbol in selected:
            for priority, lookup in enumerate((self.intel_store.find_callees, self.intel_store.find_callers)):
                nodes = lookup(
                    symbol_id=symbol.symbol_id,
                    qualified_name=symbol.qualified_name,
                    file_path=symbol.file_path,
                    symbol_name=symbol.symbol_name,
                )
                if not nodes:
                    continue
                for node in nodes:
                    candidate = self._context_symbol_from_call_graph_node(node)
                    if candidate is None or candidate.symbol_id in selected_ids:
                        continue
                    if not self._is_context_pack_symbol(candidate):
                        continue
                    candidates_by_id[candidate.symbol_id] = candidate
                    existing = relation_priority.get(candidate.symbol_id)
                    if existing is None or priority < existing:
                        relation_priority[candidate.symbol_id] = priority
        if not candidates_by_id:
            return []
        signals = self._context_symbol_signals(list(candidates_by_id.values()))
        ranks = {
            symbol_id: self._context_symbol_rank(query, symbol, popularity=signals.get(symbol_id, 0.0))
            for symbol_id, symbol in candidates_by_id.items()
        }
        ordered = sorted(
            candidates_by_id.values(),
            key=lambda symbol: (
                relation_priority.get(symbol.symbol_id, 99),
                -ranks[symbol.symbol_id][0],
                -ranks[symbol.symbol_id][1],
                -ranks[symbol.symbol_id][2],
                -ranks[symbol.symbol_id][3],
                -ranks[symbol.symbol_id][4],
                -ranks[symbol.symbol_id][5],
                -ranks[symbol.symbol_id][6],
                -ranks[symbol.symbol_id][7],
                ranks[symbol.symbol_id][8],
                ranks[symbol.symbol_id][9],
                ranks[symbol.symbol_id][10],
                symbol.symbol_id,
            ),
        )
        ordered = self._prune_overlapping_context_symbols(ordered)
        ordered = self._cap_symbols_per_file(ordered, max_per_file=max(1, max_symbols_per_file))
        return ordered[:limit]

    def _context_symbol_summary(self, symbol: SymbolRecord) -> dict[str, Any]:
        return {
            "symbol_id": symbol.symbol_id,
            "symbol_name": symbol.symbol_name,
            "qualified_name": symbol.qualified_name,
            "kind": symbol.kind,
            "file_path": symbol.file_path,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
            "score": symbol.score,
            "provenance": symbol.provenance,
        }

    def _import_neighbors(self, seed_files: list[str]) -> list[str]:
        if not seed_files:
            return []
        placeholders = ",".join("?" for _ in seed_files)
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                f"""
                SELECT DISTINCT COALESCE(target_file, raw_import) AS neighbor
                FROM imports
                WHERE repo_id = ? AND source_file IN ({placeholders})
                UNION
                SELECT DISTINCT source_file AS neighbor
                FROM imports
                WHERE repo_id = ? AND target_file IN ({placeholders})
                ORDER BY neighbor
                """,
                tuple([self.repo_id, *seed_files, self.repo_id, *seed_files]),
            ).fetchall()
        return [str(row["neighbor"]) for row in rows if row["neighbor"]]

    def _indexed_files(self) -> list[str]:
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                "SELECT file_path FROM files WHERE repo_id = ? ORDER BY file_path",
                (self.repo_id,),
            ).fetchall()
        return [str(row["file_path"]) for row in rows]

    def _read_file(self, rel: str) -> str:
        # The index can reference files absent from disk (deleted, moved, or excluded
        # from a snapshot since indexing). Degrade to empty content so every caller
        # (explore source + relationships, repo map, rerank, ...) survives instead of
        # crashing the whole tool call on one stale entry.
        try:
            return (self.repo_root / rel).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return ""

    def _read_file_slice(self, rel: str, start_byte: int, end_byte: int) -> str:
        try:
            data = (self.repo_root / rel).read_bytes()
        except (OSError, ValueError):
            return ""
        return data[start_byte:end_byte].decode("utf-8", errors="replace")

    def _load_symbol_source_for_rerank(self, symbol: SymbolRecord) -> str:
        if symbol.provenance == "commit" or symbol.kind == "commit":
            return ""
        if not symbol.file_path or symbol.end_byte <= symbol.start_byte:
            return ""
        with contextlib.suppress(OSError, ValueError):
            return self._read_file_slice(symbol.file_path, symbol.start_byte, symbol.end_byte)
        return ""

    def _source_section_for_symbol(
        self,
        symbol: SymbolRecord | dict[str, Any],
        *,
        line_numbers: bool = True,
        skeleton: bool = False,
    ) -> dict[str, Any]:
        payload = symbol.model_dump(mode="json") if isinstance(symbol, SymbolRecord) else symbol
        file_path = str(payload["file_path"])
        start_line = int(payload["start_line"])
        end_line = int(payload["end_line"])
        source = self._read_file_slice(file_path, int(payload["start_byte"]), int(payload["end_byte"]))
        lines = source.splitlines()
        if line_numbers:
            full_content = "\n".join(f"{start_line + idx}\t{line}" for idx, line in enumerate(lines))
        else:
            full_content = source
        section: dict[str, Any] = {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "symbol_id": payload["symbol_id"],
            "symbol_name": payload["symbol_name"],
            "qualified_name": payload["qualified_name"],
            "line_numbers": line_numbers,
        }
        if skeleton:
            skel = self._skeletonize_source(
                source,
                file_path=file_path,
                start_line=start_line,
                language=payload.get("language"),
                line_numbers=line_numbers,
            )
            if skel is not None:
                from atelier.core.capabilities.repo_map.budget import estimate_tokens

                # Gate + metadata only (use the skeleton iff it is actually
                # shorter); a char-based estimate gives the same decision at a
                # fraction of the cost of BPE-encoding every symbol body twice.
                saved = estimate_tokens(full_content) - estimate_tokens(skel)
                if saved > 0:
                    section["content"] = hard_cap_chars(skel, _EXPLORE_SOURCE_SECTION_MAX_CHARS)
                    section["skeleton"] = True
                    section["tokens_saved"] = saved
                    return section
        section["content"] = hard_cap_chars(full_content, _EXPLORE_SOURCE_SECTION_MAX_CHARS)
        return section

    def _merge_nearby_source_sections(
        self,
        sections: list[dict[str, Any]],
        *,
        gap_lines: int = 4,
    ) -> list[dict[str, Any]]:
        if not sections:
            return []
        ordered = sorted(
            sections,
            key=lambda item: (
                str(item["file_path"]),
                int(item["start_line"]),
                int(item["end_line"]),
            ),
        )
        merged: list[dict[str, Any]] = [dict(ordered[0])]
        for section in ordered[1:]:
            current = merged[-1]
            same_file = str(current["file_path"]) == str(section["file_path"])
            near_or_overlap = int(section["start_line"]) <= int(current["end_line"]) + max(0, gap_lines)
            if same_file and near_or_overlap and not current.get("skeleton") and not section.get("skeleton"):
                line_numbers = bool(current.get("line_numbers", True))
                current["start_line"] = min(int(current["start_line"]), int(section["start_line"]))
                current["end_line"] = max(int(current["end_line"]), int(section["end_line"]))
                current["content"] = self._render_source_section(
                    str(current["file_path"]),
                    start_line=int(current["start_line"]),
                    end_line=int(current["end_line"]),
                    line_numbers=line_numbers,
                )
                continue
            merged.append(dict(section))
        for section in merged:
            section.pop("line_numbers", None)
        return merged

    def _render_source_section(
        self,
        file_path: str,
        *,
        start_line: int,
        end_line: int,
        line_numbers: bool,
    ) -> str:
        lines = self._read_file(file_path).splitlines()
        if not lines:
            return ""
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), max(start_idx, end_line))
        segment = lines[start_idx:end_idx]
        if line_numbers:
            return hard_cap_chars(
                "\n".join(f"{start_line + idx}\t{line}" for idx, line in enumerate(segment)),
                _EXPLORE_SOURCE_SECTION_MAX_CHARS,
            )
        return hard_cap_chars("\n".join(segment), _EXPLORE_SOURCE_SECTION_MAX_CHARS)

    def _complete_sibling_families(
        self, symbols: list[SymbolRecord], *, query: str, seed_set: set[str]
    ) -> list[SymbolRecord]:
        """Surface sibling families that name-ranked search misses.

        FTS tokenization splits camelCase, so a bare affix query ('embedder')
        returns the base symbol but not 'OpenAIEmbedder'. For each strong suffix
        affix -- both the query's own tokens and those of the top selected
        symbols -- look up same-kind symbols whose name CONTAINS that affix
        (substring match); when >=3 exist, return the members not already selected
        so explore presents the whole family. Query-driven probes surface the
        family even when search ranked unrelated symbols (e.g. trivial variables)
        above it. Index lookups only, bounded by caps.
        """
        if not symbols:
            return []
        have_ids = {symbol.symbol_id for symbol in symbols}
        probes: list[tuple[str, str]] = []
        seen_probe: set[tuple[str, str]] = set()
        # Query-driven probes first -- the family the caller actually named, across
        # the definition kinds, regardless of how search ranked the raw hits.
        for affix in self._skeleton_affixes(query):
            for kind in _QUERY_PROBE_KINDS:
                key = (kind, affix)
                if key not in seen_probe:
                    seen_probe.add(key)
                    probes.append(key)
        for symbol in symbols[:_EXPLORE_FAMILY_PROBE_SYMBOLS]:
            kind = (symbol.kind or "").lower()
            if kind not in _SKELETON_KINDS:
                continue
            affixes = self._skeleton_affixes(symbol.symbol_name or symbol.qualified_name)
            if not affixes:
                continue
            key = (kind, affixes[0])  # suffix token -- the dominant family signal
            if key not in seen_probe:
                seen_probe.add(key)
                probes.append(key)
        if not probes:
            return []
        additions: list[SymbolRecord] = []
        seen_ids: set[str] = set()
        try:
            with self._connect() as conn:
                self._init_schema(conn)
                for kind, affix in probes:
                    if len(additions) >= _EXPLORE_FAMILY_TOTAL_CAP:
                        break
                    rows = conn.execute(
                        """
                        SELECT *, NULL AS score FROM symbols
                        WHERE repo_id = ? AND lower(kind) = ? AND instr(lower(symbol_name), ?) > 0
                        ORDER BY file_path, start_line
                        LIMIT ?
                        """,
                        (self.repo_id, kind, affix, _EXPLORE_FAMILY_PER_FAMILY_CAP * 3),
                    ).fetchall()
                    members = [_row_to_symbol(row) for row in rows]
                    if len({member.symbol_id for member in members}) < _SKELETON_MIN_FAMILY:
                        continue
                    added = 0
                    for member in members:
                        if added >= _EXPLORE_FAMILY_PER_FAMILY_CAP or len(additions) >= _EXPLORE_FAMILY_TOTAL_CAP:
                            break
                        if member.symbol_id in have_ids or member.symbol_id in seen_ids:
                            continue
                        if member.file_path in seed_set:
                            continue
                        if int(member.end_line) - int(member.start_line) < _SKELETON_MIN_BODY_LINES:
                            continue
                        seen_ids.add(member.symbol_id)
                        additions.append(member)
                        added += 1
        except (sqlite3.Error, OSError, ValueError):
            logging.exception("Recovered from broad exception handler")
            return []
        return additions

    def _select_skeleton_symbols(
        self,
        symbols: list[SymbolRecord],
        *,
        seed_set: set[str],
    ) -> tuple[set[str], dict[str, str]]:
        """Pick redundant sibling symbols to render signatures-only.

        Index-free: groups already-selected, non-seed symbols of the same kind
        by a shared name affix (>=4 chars, non-generic). A family needs >=3
        members; the highest-scored member stays full (the exemplar), the rest
        are skeletoned. Returns (skeleton_symbol_ids, symbol_id -> "affix:kind").
        """
        from collections import defaultdict

        candidates: list[SymbolRecord] = []
        for symbol in symbols:
            if symbol.file_path in seed_set:
                continue
            if (symbol.kind or "").lower() not in _SKELETON_KINDS:
                continue
            if int(symbol.end_line) - int(symbol.start_line) < _SKELETON_MIN_BODY_LINES:
                continue
            candidates.append(symbol)

        groups: dict[tuple[str, str], list[SymbolRecord]] = defaultdict(list)
        for symbol in candidates:
            kind = (symbol.kind or "").lower()
            for affix in self._skeleton_affixes(symbol.symbol_name or symbol.qualified_name):
                groups[(kind, affix)].append(symbol)

        assigned: set[str] = set()
        skeleton_ids: set[str] = set()
        families: dict[str, str] = {}
        for (kind, affix), members in sorted(groups.items()):
            fresh = {member.symbol_id: member for member in members if member.symbol_id not in assigned}
            if len(fresh) < _SKELETON_MIN_FAMILY:
                continue
            ordered = sorted(
                fresh.values(),
                key=lambda member: (-(member.score or 0.0), member.qualified_name or member.symbol_name or ""),
            )
            assigned.add(ordered[0].symbol_id)
            for member in ordered[1:]:
                assigned.add(member.symbol_id)
                skeleton_ids.add(member.symbol_id)
                families[member.symbol_id] = f"{affix}:{kind}"
        return skeleton_ids, families

    def _skeleton_affixes(self, name: str | None) -> list[str]:
        base = (name or "").split(".")[-1]
        raw: list[str] = []
        for snake in base.split("_"):
            if snake:
                raw.extend(_CAMEL_BOUNDARY_RE.split(snake))
        tokens = [token.lower() for token in raw if token]
        tokens = [token for token in tokens if len(token) >= 4 and token not in _SKELETON_STOPWORDS]
        if not tokens:
            return []
        affixes: list[str] = []
        if tokens[-1] not in affixes:
            affixes.append(tokens[-1])
        if tokens[0] not in affixes:
            affixes.append(tokens[0])
        return affixes

    @staticmethod
    def _signature_header_end(lines: list[str]) -> int:
        """Index of the line that ends a callable's signature header (``def ...:`` / ``{``)."""
        for index, line in enumerate(lines[:8]):
            stripped = line.rstrip()
            if stripped.endswith((":", "{", "=>")):
                return index
        return 0

    def _skeletonize_source(
        self,
        source: str,
        *,
        file_path: str,
        start_line: int,
        language: str | None,
        line_numbers: bool,
    ) -> str | None:
        """Render a symbol body as signature lines only (definitions kept, bodies dropped).

        Reuses tree-sitter definition tags so nested member signatures survive.
        Returns None when there is nothing meaningful to collapse.
        """
        lines = source.splitlines()
        if len(lines) < 2:
            return None
        from atelier.infra.tree_sitter.tags import extract_tags_from_text

        try:
            tags = extract_tags_from_text(source, file_path, language or None)
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return None
        keep = {0}
        for tag in tags:
            if tag.kind == "definition" and 1 <= tag.line <= len(lines):
                keep.add(tag.line - 1)
        kept = sorted(index for index in keep if 0 <= index < len(lines))
        if len(kept) <= 1:
            # Flat callable (function/method with no nested defs): keep only the
            # signature header and elide the body. Containers already keep their
            # member definition lines above, so this only fires for callables.
            header_end = self._signature_header_end(lines)
            if header_end + 1 >= len(lines):
                return None
            kept = list(range(header_end + 1))
        rendered: list[str] = []
        previous: int | None = None
        for index in kept:
            if previous is not None and index > previous + 1:
                rendered.append("\t…")
            if line_numbers:
                rendered.append(f"{start_line + index}\t{lines[index]}")
            else:
                rendered.append(lines[index])
            previous = index
        return "\n".join(rendered)

    def _usage_item(self, reference: UsageReference, *, snippet_lines: int) -> dict[str, Any]:
        payload = reference.model_dump(mode="json", exclude_none=True)
        if snippet_lines > 0 and "snippet" not in payload:
            payload["snippet"] = self._reference_snippet(reference.file_path, reference.line, snippet_lines)
        return payload

    def _reference_snippet(self, file_path: str, line: int, snippet_lines: int) -> str:
        lines = self._read_file(file_path).splitlines()
        if not lines:
            return ""
        start = max(0, line - 1)
        end = min(len(lines), start + max(1, snippet_lines))
        return "\n".join(lines[start:end])

    def _build_usages_payload(
        self,
        *,
        target: dict[str, Any],
        items: list[dict[str, Any]],
        group_by: Literal["file", "caller", "none"],
        truncated: bool,
        ambiguity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provenance_breakdown = self._provenance_breakdown(items)
        provenance = self._items_provenance(items) if items else str(target.get("provenance") or _LOCAL_PROVENANCE)
        payload: dict[str, Any] = {
            "target": self._usage_target_summary(target),
            "references": self._group_usages(items, group_by=group_by),
            "reference_count": len(items),
            "group_by": group_by,
            "truncated": truncated,
            "cache_hit": False,
            "provenance": provenance,
            "provenance_breakdown": provenance_breakdown,
        }
        if ambiguity is not None:
            payload["ambiguity"] = ambiguity
        return payload

    def _group_usages(
        self,
        items: list[dict[str, Any]],
        *,
        group_by: Literal["file", "caller", "none"],
    ) -> list[dict[str, Any]] | dict[str, list[dict[str, Any]]]:
        if group_by == "none":
            return items
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if group_by == "caller":
                key = str(item.get("caller") or item["file_path"])
            else:
                key = str(item["file_path"])
            grouped.setdefault(key, []).append(item)
        return grouped

    def _usage_target_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        keys = [
            "symbol_id",
            "symbol_name",
            "qualified_name",
            "file_path",
        ]
        return {key: payload[key] for key in keys if key in payload}

    def _usage_item_identity(self, item: dict[str, Any]) -> tuple[Any, ...]:
        confidence = item.get("confidence")
        normalized_confidence = round(float(confidence), 6) if isinstance(confidence, int | float) else None
        return (
            str(item.get("file_path") or ""),
            int(item.get("line") or 0),
            int(item.get("column") or 0),
            int(item.get("end_line") or 0),
            int(item.get("end_column") or 0),
            str(item.get("caller") or ""),
            str(item.get("provenance") or ""),
            str(item.get("edge_kind") or ""),
            normalized_confidence,
        )

    def _dedupe_usage_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for item in items:
            deduped[self._usage_item_identity(item)] = item
        return [deduped[key] for key in sorted(deduped.keys())]

    def _symbol_lookup_matches(
        self,
        *,
        query: str | None,
        symbol_name: str | None,
        qualified_name: str | None,
        file_path: str | None,
        kind: str | None,
        language: str | None,
        file_glob: str | None,
    ) -> list[SymbolRecord]:
        target_query = query or qualified_name or symbol_name
        if not target_query:
            return []
        candidates = self.search_symbols(
            target_query,
            limit=20,
            kind=kind,
            language=language,
            snippet="none",
            file_glob=file_glob,
            auto_index=False,
        )
        exact = [
            candidate
            for candidate in candidates
            if (candidate.qualified_name == target_query or candidate.symbol_name == target_query)
            and (file_path is None or candidate.file_path == file_path)
        ]
        matches = exact or candidates
        deduped = {candidate.symbol_id: candidate for candidate in matches}
        return sorted(
            deduped.values(),
            key=lambda candidate: (
                candidate.file_path,
                candidate.start_line,
                candidate.end_line,
                candidate.qualified_name,
                candidate.symbol_id,
            ),
        )

    def _ambiguity_metadata(self, *, operation_name: str, targets: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(targets) <= 1:
            return None
        return {
            "note": f"merged {len(targets)} matching symbols for {operation_name}",
            "merged_target_count": len(targets),
            "matches": [
                {
                    "symbol_id": str(target["symbol_id"]),
                    "qualified_name": str(target.get("qualified_name") or ""),
                    "symbol_name": str(target.get("symbol_name") or ""),
                    "file_path": str(target.get("file_path") or ""),
                    "start_line": int(target.get("start_line") or 0),
                    "provenance": str(target.get("provenance") or _LOCAL_PROVENANCE),
                }
                for target in targets[:10]
            ],
        }

    def _resolve_symbol_targets(
        self,
        *,
        operation_name: str,
        query: str | None,
        symbol_id: str | None,
        qualified_name: str | None,
        symbol_name: str | None,
        file_path: str | None,
        kind: str | None,
        language: str | None,
        file_glob: str | None,
    ) -> dict[str, Any]:
        if symbol_id or qualified_name or (symbol_name and file_path):
            try:
                target = self.get_symbol(
                    symbol_id=symbol_id,
                    qualified_name=qualified_name,
                    symbol_name=symbol_name,
                    file_path=file_path,
                    auto_index=False,
                )
            except LookupError:
                return {
                    "error": "symbol_not_found",
                    "message": "no matching symbol was found",
                    "cache_hit": False,
                    "provenance": _LOCAL_PROVENANCE,
                }
            return {"targets": [target], "ambiguity": None}
        target_query = query or qualified_name or symbol_name
        if not target_query:
            raise ValueError(f"query, symbol_id, qualified_name, or symbol_name is required for code {operation_name}")
        matches = self._symbol_lookup_matches(
            query=query,
            symbol_name=symbol_name,
            qualified_name=qualified_name,
            file_path=file_path,
            kind=kind,
            language=language,
            file_glob=file_glob,
        )
        if not matches:
            return {
                "error": "symbol_not_found",
                "message": "no matching symbol was found",
                "cache_hit": False,
                "provenance": _LOCAL_PROVENANCE,
            }
        targets: list[dict[str, Any]] = []
        for candidate in matches:
            with contextlib.suppress(LookupError):
                targets.append(self.get_symbol(symbol_id=candidate.symbol_id, auto_index=False))
        if not targets:
            return {
                "error": "symbol_not_found",
                "message": "no matching symbol was found",
                "cache_hit": False,
                "provenance": _LOCAL_PROVENANCE,
            }
        return {
            "targets": targets,
            "ambiguity": self._ambiguity_metadata(operation_name=operation_name, targets=targets),
        }

    def _resolve_symbol_target(
        self,
        *,
        operation_name: str,
        query: str | None,
        symbol_id: str | None,
        qualified_name: str | None,
        symbol_name: str | None,
        file_path: str | None,
        kind: str | None,
        language: str | None,
        file_glob: str | None,
    ) -> dict[str, Any]:
        if symbol_id or qualified_name or (symbol_name and file_path):
            try:
                return self.get_symbol(
                    symbol_id=symbol_id,
                    qualified_name=qualified_name,
                    symbol_name=symbol_name,
                    file_path=file_path,
                    auto_index=False,
                )
            except LookupError:
                return {
                    "error": "symbol_not_found",
                    "message": "no matching symbol was found",
                    "cache_hit": False,
                    "provenance": _LOCAL_PROVENANCE,
                }
        target_query = query or qualified_name or symbol_name
        if not target_query:
            raise ValueError(f"query, symbol_id, qualified_name, or symbol_name is required for code {operation_name}")
        deduped = self._symbol_lookup_matches(
            query=query,
            symbol_name=symbol_name,
            qualified_name=qualified_name,
            file_path=file_path,
            kind=kind,
            language=language,
            file_glob=file_glob,
        )
        if not deduped:
            return {
                "error": "symbol_not_found",
                "message": "no matching symbol was found",
                "cache_hit": False,
                "provenance": _LOCAL_PROVENANCE,
            }
        if len(deduped) > 1:
            return {
                "error": "disambiguation_required",
                "message": f"multiple symbols match the {operation_name} query",
                "matches": [
                    {
                        "symbol_id": candidate.symbol_id,
                        "qualified_name": candidate.qualified_name,
                        "symbol_name": candidate.symbol_name,
                        "file_path": candidate.file_path,
                        "start_line": candidate.start_line,
                        "provenance": candidate.provenance,
                    }
                    for candidate in deduped[:10]
                ],
                "cache_hit": False,
                "provenance": _LOCAL_PROVENANCE,
            }
        return self.get_symbol(symbol_id=deduped[0].symbol_id, auto_index=False)

    def _find_references_local(
        self,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        file_path: str | None = None,
        symbol_name: str | None = None,
    ) -> list[UsageReference]:
        try:
            target = self._get_symbol_local(
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                file_path=file_path,
                symbol_name=symbol_name,
            )
        except LookupError:
            target = self._get_symbol_local(
                qualified_name=qualified_name,
                file_path=file_path,
                symbol_name=symbol_name,
            )
        target_name = str(target["symbol_name"])
        target_file = str(target["file_path"])
        target_start = int(target["start_line"])
        target_end = int(target["end_line"])
        indexed = self._indexed_references_for_symbol(
            target_name=target_name,
            target_file=target_file,
            target_start=target_start,
            target_end=target_end,
        )
        if indexed:
            return indexed
        # References are indexed for every tree-sitter language at index time, so a miss
        # here means the symbol has no recorded references. Do NOT re-parse the whole repo
        # with tree-sitter at query time -- that is O(repo) and can segfault on huge or
        # generated files. Return empty; find_references() falls back to a cheap text scan.
        return []

    def _indexed_references_for_symbol(
        self,
        *,
        target_name: str,
        target_file: str,
        target_start: int,
        target_end: int,
    ) -> list[UsageReference]:
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                """
                SELECT file_path, line, column, end_column, enclosing_qualified_name, snippet
                FROM "references"
                WHERE repo_id = ? AND symbol_name = ?
                ORDER BY file_path, line, column
                """,
                (self.repo_id, target_name),
            ).fetchall()
        results: list[UsageReference] = []
        seen: set[tuple[str, int, int]] = set()
        for row in rows:
            file_path = str(row["file_path"])
            line = int(row["line"])
            column = int(row["column"])
            if file_path == target_file and target_start <= line <= target_end:
                continue
            key = (file_path, line, column)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                UsageReference(
                    file_path=file_path,
                    line=line,
                    column=column,
                    end_line=line,
                    end_column=int(row["end_column"]),
                    caller=cast(str | None, row["enclosing_qualified_name"]),
                    snippet=str(row["snippet"]),
                    provenance="local_index",
                )
            )
        return results

    def _find_callers_local(
        self,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        file_path: str | None = None,
        symbol_name: str | None = None,
    ) -> list[CallGraphNode] | None:
        try:
            target = self._get_symbol_local(
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                file_path=file_path,
                symbol_name=symbol_name,
            )
        except LookupError:
            return None
        target_name = str(target["symbol_name"])
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                """
                SELECT DISTINCT caller_symbol_name, caller_qualified_name, caller_file_path,
                       caller_start_line, caller_end_line
                FROM call_edges
                WHERE repo_id = ? AND (callee_name = ? OR callee_name LIKE ?)
                ORDER BY caller_file_path, caller_start_line
                """,
                (self.repo_id, target_name, f"%.{target_name}"),
            ).fetchall()
        return [
            self._call_graph_node_from_indexed_row(
                file_path=str(row["caller_file_path"]),
                start_line=int(row["caller_start_line"]),
                end_line=int(row["caller_end_line"]),
                symbol_name=str(row["caller_symbol_name"]),
                qualified_name=str(row["caller_qualified_name"]),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # G6 -- symbol-level call-graph centrality (with N16 cache guard)
    # ------------------------------------------------------------------

    def _symbol_centrality_map(self) -> dict[str, float]:
        """Symbol name -> normalized eigenvector centrality (0..1), cached by index
        version. Feeds the call-graph importance signal into search ranking so
        central core symbols outrank peripheral textual matches."""
        version = self._current_index_version()
        cached = getattr(self, "_centrality_name_map", None)
        if cached is not None and cached[0] == version:
            return cached[1]
        mapping: dict[str, float] = {}
        try:
            ranking = self.call_graph_centrality(limit=1_000_000).get("ranking", [])
            max_ev = max((float(item.get("eigenvector") or 0.0) for item in ranking), default=0.0) or 1.0
            for item in ranking:
                name = str(item.get("symbol") or "")
                if not name:
                    continue
                norm_ev = float(item.get("eigenvector") or 0.0) / max_ev
                for key in (name.lower(), name.split(".")[-1].split("::")[-1].lower()):
                    if norm_ev > mapping.get(key, 0.0):
                        mapping[key] = norm_ev
        except Exception:
            logging.exception("Recovered from broad exception handler")
        self._centrality_name_map = (version, mapping)
        return mapping

    def call_graph_centrality(self, *, limit: int = 50, use_cache: bool = True) -> dict[str, Any]:
        """Rank the most important symbols by call-graph centrality.

        Reads the persisted ``call_edges`` graph for this repo and returns degree
        and (power-iteration) eigenvector centrality per symbol, most central
        first. ``index_version`` is included so callers can tell which graph
        snapshot produced a ranking.

        N16: results are cached keyed to ``(index_version, limit)``. Every
        reindex bumps ``index_version`` (see ``_bump_index_version``), which
        changes the key, so a graph mutation can never serve a stale ranking.
        """
        version = self._current_index_version()
        cache_key = (version, limit)
        if use_cache:
            with self._centrality_cache_lock:
                cached = self._centrality_cache.get(cache_key)
            if cached is not None:
                return dict(cached)
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                """
                SELECT caller_qualified_name, callee_name
                FROM call_edges
                WHERE repo_id = ?
                """,
                (self.repo_id,),
            ).fetchall()
        edges = [(str(row["caller_qualified_name"]), str(row["callee_name"])) for row in rows]
        result = compute_call_graph_centrality(edges, limit=limit)
        result["index_version"] = version
        if use_cache:
            with self._centrality_cache_lock:
                self._centrality_cache[cache_key] = dict(result)
        return result

    def _fallback_callers_from_references(
        self,
        *,
        target: dict[str, Any],
        limit: int,
    ) -> CallGraphTraversalResult:
        target_symbol_id = str(target["symbol_id"])
        target_file = str(target["file_path"])
        target_start = int(target["start_line"])
        target_end = int(target["end_line"])
        references = self.intel_store.find_references(
            symbol_id=target_symbol_id,
            qualified_name=str(target["qualified_name"]),
            file_path=target_file,
            symbol_name=str(target["symbol_name"]),
        )
        references = sorted(
            [*references, *self._cross_lang_usage_references(target)],
            key=lambda item: (item.file_path, item.line, item.column, item.provenance),
        )
        nodes_by_id: dict[str, CallGraphNode] = {}
        edges: list[CallGraphEdge] = []
        seen_edges: set[tuple[str, str, int]] = set()
        truncated = False
        for reference in references:
            if reference.file_path == target_file and target_start <= reference.line <= target_end:
                continue
            node = self._caller_node_from_reference(reference, target_symbol_id=target_symbol_id)
            if node is None:
                continue
            if node.symbol_id not in nodes_by_id:
                if len(nodes_by_id) >= limit:
                    truncated = True
                    continue
                nodes_by_id[node.symbol_id] = node
            edge_key = (node.symbol_id, target_symbol_id, 1)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append(
                    CallGraphEdge(
                        caller_symbol_id=node.symbol_id,
                        callee_symbol_id=target_symbol_id,
                        depth=1,
                    )
                )
        ordered_nodes = sorted(nodes_by_id.values(), key=lambda item: (item.file_path, item.start_line, item.symbol_id))
        ordered_edges = sorted(edges, key=lambda item: (item.depth, item.caller_symbol_id, item.callee_symbol_id))
        if not ordered_edges:
            return CallGraphTraversalResult(
                nodes=[],
                edges=[],
                truncated=False,
                data_status="unavailable",
                message="routed call edge data is unavailable",
                snapshot=None,
            )
        return CallGraphTraversalResult(
            nodes=ordered_nodes,
            edges=ordered_edges,
            truncated=truncated,
            data_status="available",
            message="fallback caller graph derived from symbol references",
            snapshot=None,
        )

    def _caller_node_from_reference(
        self,
        reference: UsageReference,
        *,
        target_symbol_id: str,
    ) -> CallGraphNode | None:
        normalized_file = self._normalize_file_arg(reference.file_path)
        with self._connect() as conn:
            self._init_schema(conn)
            row = conn.execute(
                """
                SELECT *, NULL AS score FROM symbols
                WHERE repo_id = ? AND file_path = ? AND start_line <= ? AND end_line >= ?
                ORDER BY (end_line - start_line) ASC, start_line DESC
                LIMIT 1
                """,
                (self.repo_id, normalized_file, reference.line, reference.line),
            ).fetchone()
        if row is not None:
            symbol = _row_to_symbol(row)
            if symbol.symbol_id == target_symbol_id:
                return None
            return CallGraphNode(
                symbol_id=symbol.symbol_id,
                symbol_name=symbol.symbol_name,
                qualified_name=symbol.qualified_name,
                file_path=symbol.file_path,
                kind=symbol.kind,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                provenance=reference.provenance or symbol.provenance,
            )
        synthetic_seed = f"{normalized_file}:{reference.line}:{reference.column}:{reference.caller or ''}"
        synthetic_id = f"ref::{hashlib.sha1(synthetic_seed.encode('utf-8')).hexdigest()[:16]}"
        fallback_name = reference.caller or f"{Path(normalized_file).name}:{reference.line}"
        return CallGraphNode(
            symbol_id=synthetic_id,
            symbol_name=fallback_name,
            qualified_name=fallback_name,
            file_path=normalized_file,
            kind="reference",
            start_line=reference.line,
            end_line=reference.end_line,
            provenance=reference.provenance or "treesitter",
        )

    def _find_callees_local(
        self,
        *,
        symbol_id: str | None = None,
        qualified_name: str | None = None,
        file_path: str | None = None,
        symbol_name: str | None = None,
    ) -> list[CallGraphNode] | None:
        try:
            target = self._get_symbol_local(
                symbol_id=symbol_id,
                qualified_name=qualified_name,
                file_path=file_path,
                symbol_name=symbol_name,
            )
        except LookupError:
            return None
        target_file = str(target["file_path"])
        target_start = int(target["start_line"])
        target_end = int(target["end_line"])
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                """
                SELECT DISTINCT callee_name
                FROM call_edges
                WHERE repo_id = ? AND caller_file_path = ?
                  AND caller_start_line = ? AND caller_end_line = ?
                ORDER BY callee_name
                """,
                (self.repo_id, target_file, target_start, target_end),
            ).fetchall()
        target_ext = Path(target_file).suffix
        target_is_python = target_ext == ".py"
        nodes_by_identity: dict[str, CallGraphNode] = {}
        for row in rows:
            callee_name = str(row["callee_name"])
            short_name = callee_name.rsplit(".", 1)[-1]
            matched = self._indexed_symbol_payloads_for_call_name(callee_name)
            # Keep only definitions in the caller's own language. A Python
            # function cannot call a TS/JS symbol that merely shares the short
            # name (e.g. `range`, `min`), so cross-language name collisions are
            # dropped rather than surfaced as bogus callees.
            same_lang = [p for p in matched if Path(str(p.get("file_path") or "")).suffix == target_ext]
            if same_lang:
                for payload in same_lang:
                    node = CallGraphNode(
                        symbol_id=str(payload["symbol_id"]),
                        symbol_name=str(payload["symbol_name"]),
                        qualified_name=str(payload["qualified_name"]),
                        file_path=str(payload["file_path"]),
                        kind=str(payload["kind"]),
                        start_line=int(payload["start_line"]),
                        end_line=int(payload["end_line"]),
                        provenance=str(payload.get("provenance") or "local_index"),
                    )
                    nodes_by_identity[node.symbol_id] = node
                continue
            # No same-language definition: for Python callers, builtins and
            # ubiquitous container methods have no navigable target and are pure
            # noise — skip them instead of emitting a synthetic reference node.
            if target_is_python and short_name in _PY_CALLEE_NOISE:
                continue
            synthetic_id = f"local-callee::{hashlib.sha1(callee_name.encode('utf-8')).hexdigest()[:16]}"
            if synthetic_id not in nodes_by_identity:
                nodes_by_identity[synthetic_id] = CallGraphNode(
                    symbol_id=synthetic_id,
                    symbol_name=short_name,
                    qualified_name=callee_name,
                    file_path=target_file,
                    kind="reference",
                    start_line=target_start,
                    end_line=target_end,
                    provenance="local_index",
                )
        return sorted(
            nodes_by_identity.values(),
            key=lambda item: (item.file_path, item.start_line, item.symbol_id),
        )

    def _indexed_symbol_payloads_for_call_name(self, call_name: str) -> list[dict[str, Any]]:
        short_name = call_name.rsplit(".", 1)[-1]
        with self._connect() as conn:
            self._init_schema(conn)
            rows = conn.execute(
                """
                SELECT *, NULL AS score FROM symbols
                WHERE repo_id = ? AND symbol_name = ?
                ORDER BY file_path, start_line, end_line, qualified_name, symbol_id
                """,
                (self.repo_id, short_name),
            ).fetchall()
        if not rows:
            return []
        symbols = [_row_to_symbol(row) for row in rows]
        short_suffix = f".{short_name}"
        ranked = sorted(
            symbols,
            key=lambda symbol: (
                0 if symbol.qualified_name == call_name else 1 if symbol.qualified_name.endswith(short_suffix) else 2,
                symbol.file_path,
                symbol.start_line,
                symbol.end_line,
                symbol.qualified_name,
                symbol.symbol_id,
            ),
        )
        deduped: dict[str, dict[str, Any]] = {}
        for symbol in ranked:
            deduped[symbol.symbol_id] = symbol.model_dump(mode="json", exclude_none=True)
        return list(deduped.values())

    def _call_graph_node_from_indexed_row(
        self,
        *,
        file_path: str,
        start_line: int,
        end_line: int,
        symbol_name: str,
        qualified_name: str,
    ) -> CallGraphNode:
        with self._connect() as conn:
            self._init_schema(conn)
            row = conn.execute(
                """
                    SELECT *, NULL AS score FROM symbols
                    WHERE repo_id = ? AND file_path = ? AND start_line = ? AND symbol_name = ?
                    LIMIT 1
                    """,
                (self.repo_id, file_path, start_line, symbol_name),
            ).fetchone()
        if row is not None:
            symbol = _row_to_symbol(row)
            return CallGraphNode(
                symbol_id=symbol.symbol_id,
                symbol_name=symbol.symbol_name,
                qualified_name=symbol.qualified_name,
                file_path=symbol.file_path,
                kind=symbol.kind,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                provenance="local_index",
            )
        synthetic_id = (
            f"local-call::{hashlib.sha1(f'{file_path}:{start_line}:{qualified_name}'.encode()).hexdigest()[:16]}"
        )
        return CallGraphNode(
            symbol_id=synthetic_id,
            symbol_name=symbol_name,
            qualified_name=qualified_name,
            file_path=file_path,
            kind="function",
            start_line=start_line,
            end_line=end_line,
            provenance="local_index",
        )

    def _parse_rg_output(self, output: str, *, limit: int) -> list[TextMatch]:
        matches: list[TextMatch] = []
        for line in output.splitlines():
            if len(matches) >= limit:
                break
            path_text, sep, rest = line.partition(":")
            if not sep:
                continue
            line_text, sep, rest = rest.partition(":")
            if not sep:
                continue
            column_text, sep, text = rest.partition(":")
            if not sep:
                continue
            with contextlib.suppress(ValueError):
                matches.append(
                    TextMatch(
                        file_path=self._normalize_file_arg(path_text),
                        line=int(line_text),
                        column=int(column_text),
                        text=text,
                    )
                )
        return matches

    def _cache_get(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
        return self._cache.get(
            tool_name=tool_name,
            args=args,
            index_version=self._current_index_version(),
            repo_id=self.repo_id,
        )

    def _cache_set(self, tool_name: str, args: dict[str, Any], payload: dict[str, Any]) -> None:
        self._cache.set(
            tool_name=tool_name,
            args=args,
            index_version=self._current_index_version(),
            repo_id=self.repo_id,
            payload=payload,
        )

    def _reindex_files(self, file_paths: list[str]) -> None:
        """Incrementally reindex only *file_paths* -- never a whole-repo rebuild.

        Called after an edit (or codemod) touches specific files. Deleting and
        re-extracting just those files keeps post-edit latency O(edited files).
        The previous implementation called ``self.index_repo()`` (force=True),
        which wiped every table and re-parsed the entire repo on every symbol
        edit -- minutes on large repos (sympy/django) for a one-file change.
        """
        rels: list[str] = []
        existing_paths: list[Path] = []
        seen: set[str] = set()
        for raw in file_paths:
            try:
                resolved = self._resolve_inside_repo(raw)
            except ValueError:
                continue
            rel = _safe_relpath(self.repo_root, resolved)
            if rel in seen:
                continue
            seen.add(rel)
            rels.append(rel)
            if resolved.is_file():
                existing_paths.append(resolved)
        if not rels:
            return

        def _reindex_locked() -> None:
            with self._index_write_lock(block=True) as acquired:
                if not acquired:
                    # Another process is rebuilding the index; it will pick up
                    # these files. Don't pile on a concurrent write.
                    return
                with self._connect() as conn:
                    self._init_schema(conn)
                    for rel in rels:
                        self._delete_file_index(conn, rel)
                    results = (
                        self._parallel_extract(existing_paths, total=len(existing_paths)) if existing_paths else []
                    )
                    if results:
                        self._apply_file_data_batch(conn, results)
                    self._bump_index_version(conn)

        if self._autosync_enabled:
            with self._db_lock, self._autosync_lock:
                _reindex_locked()
        else:
            with self._db_lock:
                _reindex_locked()

    def _current_index_version(self) -> int:
        if self._index_version_cached is not None:
            return self._index_version_cached
        with self._connect() as conn:
            self._init_schema(conn)
            row = conn.execute("SELECT value FROM engine_state WHERE key = 'index_version'").fetchone()
        version = int(row["value"]) if row is not None else 0
        self._index_version_cached = version
        return version

    def _index_snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            self._init_schema(conn)
            file_count_row = conn.execute(
                "SELECT COUNT(*) AS count FROM files WHERE repo_id = ?", (self.repo_id,)
            ).fetchone()
            symbol_count_row = conn.execute(
                "SELECT COUNT(*) AS count FROM symbols WHERE repo_id = ?",
                (self.repo_id,),
            ).fetchone()
            import_count_row = conn.execute(
                "SELECT COUNT(*) AS count FROM imports WHERE repo_id = ?",
                (self.repo_id,),
            ).fetchone()
            indexed_at_row = conn.execute(
                "SELECT MAX(indexed_at) AS indexed_at FROM files WHERE repo_id = ?",
                (self.repo_id,),
            ).fetchone()
        files_indexed = int(file_count_row["count"]) if file_count_row is not None else 0
        symbols_indexed = int(symbol_count_row["count"]) if symbol_count_row is not None else 0
        imports_indexed = int(import_count_row["count"]) if import_count_row is not None else 0
        last_indexed_at = str(indexed_at_row["indexed_at"]) if indexed_at_row and indexed_at_row["indexed_at"] else None
        index_age_seconds: int | None = None
        if last_indexed_at:
            with contextlib.suppress(ValueError):
                parsed = datetime.fromisoformat(last_indexed_at.replace("Z", "+00:00"))
                index_age_seconds = max(0, int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()))
        return {
            "files_indexed": files_indexed,
            "symbols_indexed": symbols_indexed,
            "imports_indexed": imports_indexed,
            "last_indexed_at": last_indexed_at,
            "index_age_seconds": index_age_seconds,
        }

    def _bump_index_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT value FROM engine_state WHERE key = 'index_version'").fetchone()
        current = int(row["value"]) if row is not None else 0
        next_version = current + 1
        conn.execute(
            """
            INSERT INTO engine_state(key, value)
            VALUES ('index_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(next_version),),
        )
        # N16: a reindex (this version bump) must not serve stale neighbours.
        # The cached HNSW graph is keyed to index_version, but drop it eagerly so
        # the next query rebuilds against the fresh vectors immediately.
        self._ann_symbol_index.invalidate()
        self._index_version_cached = next_version
        return next_version

    def _payload_tokens(self, payload: Any) -> int:
        return estimate_tokens(_canonical_json(payload))

    def _compute_total_tokens(self, payload: dict[str, Any]) -> int:
        total_tokens = 0
        while True:
            candidate = dict(payload)
            candidate["total_tokens"] = total_tokens
            measured = self._payload_tokens(candidate)
            if measured == total_tokens:
                return measured
            total_tokens = measured

    def _dedupe_search_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int, int, str]] = set()
        for item in items:
            key = (
                str(item.get("symbol_id") or ""),
                str(item.get("file_path") or ""),
                int(item.get("start_line") or 0),
                int(item.get("end_line") or 0),
                str(item.get("qualified_name") or item.get("symbol_name") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _prioritize_grounded_search_items(
        self,
        items: list[dict[str, Any]],
        *,
        seed_files: list[str],
    ) -> list[dict[str, Any]]:
        if not seed_files:
            return items
        seed_set = set(seed_files)
        indexed_items = list(enumerate(items))
        indexed_items.sort(
            key=lambda entry: (
                0 if str(entry[1].get("file_path") or "") in seed_set else 1,
                entry[0],
            )
        )
        return [item for _, item in indexed_items]

    def _compact_search_items(
        self,
        items: list[dict[str, Any]],
        *,
        scope: Literal["repo", "external", "deleted"],
    ) -> list[dict[str, Any]]:
        allowed_keys = _DELETED_SEARCH_COMPACT_DEFAULT_KEYS if scope == "deleted" else _SEARCH_COMPACT_DEFAULT_KEYS
        # For external scope "origin" is the load-bearing field that distinguishes
        # external symbols from repo symbols, so it must survive compaction.
        if scope == "external":
            allowed_keys = allowed_keys | {"origin", "repo_name"}
        compacted = [{key: value for key, value in item.items() if key in allowed_keys} for item in items]
        if scope == "repo":
            result: list[dict[str, Any]] = []
            for item in compacted:
                # For commit chunks, provenance and commit_sha must survive.
                if item.get("provenance") == "commit":
                    cleaned = {
                        k: v for k, v in item.items() if k not in _SEARCH_REPO_STRIP_ITEM_KEYS or k == "provenance"
                    }
                else:
                    cleaned = {k: v for k, v in item.items() if k not in _SEARCH_REPO_STRIP_ITEM_KEYS}
                # qualified_name adds no information when it is identical to symbol_name
                if cleaned.get("qualified_name") == cleaned.get("symbol_name"):
                    cleaned.pop("qualified_name", None)
                result.append(cleaned)
            return result
        return compacted

    def _should_force_search_compaction(
        self,
        *,
        scope: Literal["repo", "external", "deleted"],
        snippet: Literal["none", "head", "full"],
        limit: int,
    ) -> bool:
        return scope == "repo" and snippet == "head" and limit >= _SEARCH_SNIPPET_FORCE_COMPACT_LIMIT

    def _effective_budget_tokens(self, operation: str, requested_budget_tokens: int) -> int:
        requested = max(1, int(requested_budget_tokens))
        safety_max = _OPERATION_TOKEN_CAPS.get(operation, resolve_output_policy(operation).max_total_tokens)
        return min(requested, safety_max)

    def _items_provenance(self, items: list[dict[str, Any]]) -> str:
        provenances = [str(item.get("provenance")) for item in items if item.get("provenance")]
        if not provenances:
            return _LOCAL_PROVENANCE
        first = provenances[0]
        if all(provenance == first for provenance in provenances):
            return first
        return _LOCAL_PROVENANCE

    def _provenance_breakdown(self, items: list[dict[str, Any]]) -> dict[str, int]:
        breakdown: dict[str, int] = {}
        for item in items:
            provenance = str(item.get("provenance") or _LOCAL_PROVENANCE)
            breakdown[provenance] = breakdown.get(provenance, 0) + 1
        return breakdown

    def _finalize_packed_payload(
        self,
        payload: dict[str, Any],
        *,
        full_total_tokens: int,
        base_tokens_saved: int = 0,
    ) -> dict[str, Any]:
        finalized = dict(payload)
        tokens_saved = max(0, base_tokens_saved)
        while True:
            finalized["tokens_saved"] = tokens_saved
            total_tokens = self._compute_total_tokens(finalized)
            updated_tokens_saved = max(base_tokens_saved, full_total_tokens - total_tokens)
            if updated_tokens_saved == tokens_saved:
                finalized["total_tokens"] = total_tokens
                return apply_field_name_shortening(finalized)
            tokens_saved = updated_tokens_saved

    def _fit_items_to_budget(
        self,
        items: list[dict[str, Any]],
        *,
        budget_tokens: int,
        essential_keys: list[str],
        optional_keys_in_drop_order: list[str],
        build_payload: Callable[[list[dict[str, Any]]], dict[str, Any]],
        enforce_protected_top_rank: bool = True,
    ) -> dict[str, Any]:
        minimal_items, _, _ = self._budget.pack(
            items,
            0,
            essential_keys=essential_keys,
            optional_keys_in_drop_order=optional_keys_in_drop_order,
        )
        protected_items = minimal_items[: min(PROTECTED_TOP_RANK, len(minimal_items))]
        protected_payload = build_payload(protected_items)
        if enforce_protected_top_rank and protected_items and protected_payload["total_tokens"] > budget_tokens:
            # Degrade gracefully: return the top-ranked item(s) even if over budget.
            # A slightly over-budget result is strictly better than a hard error with 0 items.
            return protected_payload

        best_payload = build_payload(minimal_items)
        if best_payload["total_tokens"] > budget_tokens:
            for end in range(len(minimal_items) - 1, -1, -1):
                candidate = build_payload(minimal_items[:end])
                if candidate["total_tokens"] <= budget_tokens:
                    return candidate
            return build_payload([])

        low = 0
        high = max(0, budget_tokens)
        while low <= high:
            mid = (low + high) // 2
            packed_items, _, _ = self._budget.pack(
                items,
                mid,
                essential_keys=essential_keys,
                optional_keys_in_drop_order=optional_keys_in_drop_order,
            )
            candidate = build_payload(packed_items)
            if candidate["total_tokens"] <= budget_tokens:
                best_payload = candidate
                low = mid + 1
            else:
                high = mid - 1

        return best_payload

    def _pack_items_payload(
        self,
        items: list[dict[str, Any]],
        *,
        budget_tokens: int,
        essential_keys: list[str],
        optional_keys_in_drop_order: list[str],
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra = dict(extra_payload or {})
        provenance = self._items_provenance(items)
        provenance_breakdown = self._provenance_breakdown(items)
        include_provenance_breakdown = len(provenance_breakdown) > 1
        full_payload = {
            "items": items,
            "cache_hit": False,
            "provenance": provenance,
            **extra,
        }
        if include_provenance_breakdown:
            full_payload["provenance_breakdown"] = provenance_breakdown
        full_total_tokens = self._compute_total_tokens({**full_payload, "tokens_saved": 0})

        def build_payload(packed_items: list[dict[str, Any]]) -> dict[str, Any]:
            packed_provenance_breakdown = self._provenance_breakdown(packed_items)
            return self._finalize_packed_payload(
                {
                    "items": packed_items,
                    "cache_hit": False,
                    "provenance": provenance,
                    **extra,
                    **(
                        {"provenance_breakdown": packed_provenance_breakdown}
                        if len(packed_provenance_breakdown) > 1
                        else {}
                    ),
                },
                full_total_tokens=full_total_tokens,
            )

        packed = self._fit_items_to_budget(
            items,
            budget_tokens=budget_tokens,
            essential_keys=essential_keys,
            optional_keys_in_drop_order=optional_keys_in_drop_order,
            build_payload=build_payload,
        )
        return self._maybe_attach_overflow_metadata(
            packed_payload=packed,
            full_payload=full_payload,
            full_total_tokens=full_total_tokens,
            budget_tokens=budget_tokens,
        )

    def _pack_pattern_matches(
        self,
        result: PatternSearchResult,
        *,
        budget_tokens: int,
    ) -> dict[str, Any]:
        items = [match.to_dict() for match in result.matches]
        full_payload = {
            "matches": items,
            "truncated": bool(result.truncated),
            "total_matches": result.total_matches if result.total_matches is not None else len(items),
            "cache_hit": False,
            "provenance": "ast-grep",
        }
        full_total_tokens = self._compute_total_tokens({**full_payload, "tokens_saved": 0})

        def build_payload(packed_items: list[dict[str, Any]]) -> dict[str, Any]:
            truncated = bool(result.truncated) or len(packed_items) < len(items)
            return self._finalize_packed_payload(
                {
                    "matches": packed_items,
                    "truncated": truncated,
                    "total_matches": result.total_matches if result.total_matches is not None else len(items),
                    "cache_hit": False,
                    "provenance": "ast-grep",
                },
                full_total_tokens=full_total_tokens,
            )

        packed = self._fit_items_to_budget(
            items,
            budget_tokens=budget_tokens,
            essential_keys=_PATTERN_ESSENTIAL_KEYS,
            optional_keys_in_drop_order=_PATTERN_OPTIONAL_KEYS,
            build_payload=build_payload,
            enforce_protected_top_rank=False,
        )
        return self._maybe_attach_overflow_metadata(
            packed_payload=packed,
            full_payload=full_payload,
            full_total_tokens=full_total_tokens,
            budget_tokens=budget_tokens,
        )

    def _pack_pattern_rewrite(
        self,
        result: PatternRewriteResult,
        *,
        budget_tokens: int,
    ) -> dict[str, Any]:
        # `diff` is the one essential field, so the budget packer never drops it.
        # A repo-wide rewrite would otherwise emit an unbounded verbatim diff into
        # the model context; head+tail truncate so large rewrites stay bounded
        # while small previews pass through untouched. files_changed always lists
        # every affected file regardless of truncation.
        diff_lines = (result.diff or "").splitlines(keepends=True)
        diff_head, diff_tail = 170, 30
        if len(diff_lines) > diff_head + diff_tail:
            elided = len(diff_lines) - diff_head - diff_tail
            diff = (
                "".join(diff_lines[:diff_head])
                + f"... ({elided} more diff lines elided; see files_changed)\n"
                + "".join(diff_lines[-diff_tail:])
            )
        else:
            diff = result.diff
        return self._pack_single_payload(
            {
                "diff": diff,
                "files_changed": result.files_changed,
                "provenance": "ast-grep",
            },
            budget_tokens=budget_tokens,
            essential_keys=["diff", "files_changed", "provenance"],
            optional_keys_in_drop_order=[],
        )

    def _pack_single_payload(
        self,
        payload: dict[str, Any],
        *,
        budget_tokens: int,
        essential_keys: list[str],
        optional_keys_in_drop_order: list[str],
        base_tokens_saved: int = 0,
    ) -> dict[str, Any]:
        full_payload = dict(payload)
        full_payload.setdefault("cache_hit", False)
        full_payload.setdefault("provenance", _LOCAL_PROVENANCE)
        full_total_tokens = self._compute_total_tokens({**full_payload, "tokens_saved": max(0, base_tokens_saved)})
        minimal_payload = {key: full_payload[key] for key in essential_keys if key in full_payload}

        def build_payload(packed_items: list[dict[str, Any]]) -> dict[str, Any]:
            packed_payload = dict(packed_items[0]) if packed_items else dict(minimal_payload)
            packed_payload["cache_hit"] = False
            packed_payload["provenance"] = str(full_payload.get("provenance") or _LOCAL_PROVENANCE)
            return self._finalize_packed_payload(
                packed_payload,
                full_total_tokens=full_total_tokens,
                base_tokens_saved=base_tokens_saved,
            )

        packed = self._fit_items_to_budget(
            [full_payload],
            budget_tokens=budget_tokens,
            essential_keys=[*essential_keys, "cache_hit", "tokens_saved", "provenance"],
            optional_keys_in_drop_order=optional_keys_in_drop_order,
            build_payload=build_payload,
            enforce_protected_top_rank=False,
        )
        return self._maybe_attach_overflow_metadata(
            packed_payload=packed,
            full_payload=full_payload,
            full_total_tokens=full_total_tokens,
            budget_tokens=budget_tokens,
            base_tokens_saved=base_tokens_saved,
        )

    def _maybe_attach_overflow_metadata(
        self,
        *,
        packed_payload: dict[str, Any],
        full_payload: dict[str, Any],
        full_total_tokens: int,
        budget_tokens: int,
        base_tokens_saved: int = 0,
    ) -> dict[str, Any]:
        if full_total_tokens <= budget_tokens:
            return packed_payload
        if "error" in packed_payload:
            return packed_payload
        overflow_tokens = full_total_tokens - budget_tokens
        if overflow_tokens < _OVERFLOW_SPILL_MIN_EXCESS_TOKENS:
            return packed_payload
        packed_total_tokens = int(packed_payload.get("total_tokens", self._compute_total_tokens(packed_payload)))
        reduction_tokens = max(0, full_total_tokens - packed_total_tokens)
        if reduction_tokens < _OVERFLOW_SPILL_MIN_REDUCTION_TOKENS:
            return packed_payload
        overflow_meta = self._write_overflow_artifact(full_payload)
        with_meta = dict(packed_payload)
        with_meta["overflow"] = overflow_meta
        finalized = self._finalize_packed_payload(
            with_meta,
            full_total_tokens=full_total_tokens,
            base_tokens_saved=max(base_tokens_saved, int(packed_payload.get("tokens_saved", 0) or 0)),
        )
        if finalized.get("total_tokens", 0) > budget_tokens:
            return packed_payload
        return finalized

    def _write_overflow_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        artifact_root = default_store_root() / "overflow" / "code"
        artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_payload = self._prune_overflow_artifact_payload(payload)
        canonical = _canonical_json(artifact_payload)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        filename = f"{self.repo_id}-{int(time.time() * 1000)}-{digest}.json"
        artifact_path = artifact_root / filename
        artifact_path.write_text(
            json.dumps(artifact_payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return {
            "spilled": True,
            "artifact_path": str(artifact_path),
            "artifact_format": "json",
        }

    def _prune_overflow_artifact_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        artifact_payload = cast(dict[str, Any], self._json_safe(payload))
        for key in (
            "tokens_saved",
            "total_tokens",
            "cache_hit",
            "overflow",
            "rendered",
            "rendered_format",
        ):
            artifact_payload.pop(key, None)
        return artifact_payload

    def _mark_cache_hit(self, payload: dict[str, Any]) -> dict[str, Any]:
        cached = cast(dict[str, Any], json.loads(_canonical_json(payload)))
        cached["cache_hit"] = True
        cached["provenance"] = "cached"
        cached["total_tokens"] = self._compute_total_tokens(cached)
        return cached

    def _normalize_cache_tool(self, cache_tool: str | None) -> str | None:
        normalized = (cache_tool or "all").strip().lower()
        if normalized not in _CACHE_TOOL_ALIASES:
            choices = ", ".join(sorted(_CACHE_TOOL_ALIASES))
            raise ValueError(f"cache_tool must be one of: {choices}")
        return _CACHE_TOOL_ALIASES[normalized]

    def _attach_snippet(
        self,
        symbol: SymbolRecord,
        *,
        snippet: Literal["none", "head", "full"],
        snippet_lines: int,
    ) -> SymbolRecord:
        if snippet == "none":
            return symbol.model_copy(update={"snippet": None})
        safe_line_count = max(1, snippet_lines)
        snippet_text = self._read_symbol_snippet(
            symbol.file_path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            mode=snippet,
            snippet_lines=safe_line_count,
        )
        return symbol.model_copy(update={"snippet": snippet_text})

    def _read_symbol_snippet(
        self,
        file_path: str,
        *,
        start_line: int,
        end_line: int,
        mode: Literal["head", "full"],
        snippet_lines: int,
    ) -> str:
        resolved = self._resolve_inside_repo(file_path)
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines:
            return ""
        start_index = max(0, start_line - 1)
        max_end_index = min(len(lines), start_index + snippet_lines)
        if mode == "full":
            max_end_index = min(max_end_index, max(start_index + 1, end_line))
        snippet_slice = lines[start_index:max_end_index]
        return "\n".join(snippet_slice)

    def _normalize_files_path(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = self._normalize_file_arg(value).strip().strip("/")
        if normalized in {"", "."}:
            return None
        return normalized

    def _matches_files_filters(
        self,
        file_path: str,
        *,
        path: str | None,
        pattern: str | None,
        max_depth: int | None,
    ) -> bool:
        if path and file_path != path and not file_path.startswith(f"{path}/"):
            return False
        if pattern and not _matches_file_glob(file_path, pattern):
            return False
        if max_depth is None:
            return True
        if path and file_path == path:
            relative = ""
        elif path and file_path.startswith(f"{path}/"):
            relative = file_path[len(path) + 1 :]
        else:
            relative = file_path
        depth = relative.count("/") if relative else 0
        return depth <= max_depth

    def _indexed_file_records(
        self,
        *,
        path: str | None,
        pattern: str | None,
        max_depth: int | None,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._init_schema(conn)
            file_rows = conn.execute(
                """
                SELECT file_path, language
                FROM files
                WHERE repo_id = ?
                ORDER BY file_path
                """,
                (self.repo_id,),
            ).fetchall()
            symbol_count_rows = conn.execute(
                """
                SELECT file_path, COUNT(*) AS symbol_count
                FROM symbols
                WHERE repo_id = ?
                GROUP BY file_path
                """,
                (self.repo_id,),
            ).fetchall()
            top_symbol_rows = conn.execute(
                """
                SELECT file_path, symbol_name
                FROM (
                    SELECT
                        file_path,
                        symbol_name,
                        ROW_NUMBER() OVER (
                            PARTITION BY file_path
                            ORDER BY start_line, symbol_name
                        ) AS row_no
                    FROM symbols
                    WHERE repo_id = ?
                )
                WHERE row_no <= 3
                ORDER BY file_path, row_no
                """,
                (self.repo_id,),
            ).fetchall()
        symbol_counts = {str(row["file_path"]): int(row["symbol_count"]) for row in symbol_count_rows}
        top_symbols: dict[str, list[str]] = {}
        for row in top_symbol_rows:
            file_path = str(row["file_path"])
            top_symbols.setdefault(file_path, []).append(str(row["symbol_name"]))

        records: list[dict[str, Any]] = []
        for row in file_rows:
            file_path = str(row["file_path"])
            if not self._matches_files_filters(file_path, path=path, pattern=pattern, max_depth=max_depth):
                continue
            record = IndexedFileRecord(
                file_path=file_path,
                language=str(row["language"] or "unknown"),
                symbol_count=symbol_counts.get(file_path, 0),
                top_symbols=top_symbols.get(file_path, []),
            )
            records.append(record.model_dump(mode="json", exclude_none=True))
        return records

    def _indexed_route_records(
        self,
        *,
        file_glob: str | None,
        language: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        candidates = self._indexed_file_records(path=None, pattern=file_glob, max_depth=None)
        allowed_languages = {"python", "javascript", "typescript"}
        if language is not None and language not in allowed_languages:
            return [], False
        routes: list[dict[str, Any]] = []
        truncated = False
        for candidate in candidates:
            file_path = str(candidate.get("file_path") or "")
            file_language = str(candidate.get("language") or "unknown").lower()
            if file_language not in allowed_languages:
                continue
            if language is not None and file_language != language:
                continue
            for route in self._extract_routes_from_file(file_path=file_path, language=file_language):
                routes.append(route)
                if len(routes) >= limit:
                    truncated = True
                    break
            if truncated:
                break
        routes.sort(
            key=lambda item: (
                str(item.get("file_path")),
                int(item.get("line", 0)),
                str(item.get("route")),
            )
        )
        return routes[:limit], truncated

    def _extract_routes_from_file(
        self,
        *,
        file_path: str,
        language: str,
    ) -> list[dict[str, Any]]:
        with contextlib.suppress(OSError, UnicodeDecodeError):
            source = self._resolve_inside_repo(file_path).read_text(encoding="utf-8", errors="replace")
            lines = source.splitlines()
            records: list[RouteRecord] = []
            if language == "python":
                records.extend(self._extract_python_routes(file_path=file_path, lines=lines))
            elif language in {"javascript", "typescript"}:
                records.extend(self._extract_js_routes(file_path=file_path, lines=lines, language=language))
            return [record.model_dump(mode="json", exclude_none=True) for record in records]
        return []

    def _extract_python_routes(self, *, file_path: str, lines: list[str]) -> list[RouteRecord]:
        records: list[RouteRecord] = []
        for index, line in enumerate(lines, start=1):
            fastapi_match = _FASTAPI_DECORATOR_RE.search(line)
            if fastapi_match:
                method = fastapi_match.group("verb").upper()
                if method == "WEBSOCKET":
                    method = "WS"
                records.append(
                    RouteRecord(
                        framework="fastapi",
                        method=method,
                        route=fastapi_match.group("route"),
                        file_path=file_path,
                        line=index,
                        language="python",
                        handler=self._next_python_def_name(lines, index),
                        router=fastapi_match.group("router"),
                        provenance=_LOCAL_PROVENANCE,
                    )
                )
                continue
            fastapi_api_route_match = _FASTAPI_API_ROUTE_RE.search(line)
            if fastapi_api_route_match:
                route = fastapi_api_route_match.group("route")
                methods = self._parse_methods(fastapi_api_route_match.group("rest"))
                for method in methods:
                    records.append(
                        RouteRecord(
                            framework="fastapi",
                            method=method,
                            route=route,
                            file_path=file_path,
                            line=index,
                            language="python",
                            handler=self._next_python_def_name(lines, index),
                            router=fastapi_api_route_match.group("router"),
                            provenance=_LOCAL_PROVENANCE,
                        )
                    )
                continue
            flask_match = _FLASK_ROUTE_RE.search(line)
            if flask_match:
                route = flask_match.group("route")
                methods = self._parse_methods(flask_match.group("rest"))
                for method in methods:
                    records.append(
                        RouteRecord(
                            framework="flask",
                            method=method,
                            route=route,
                            file_path=file_path,
                            line=index,
                            language="python",
                            handler=self._next_python_def_name(lines, index),
                            router=flask_match.group("router"),
                            provenance=_LOCAL_PROVENANCE,
                        )
                    )
                continue
            flask_rule_match = _FLASK_ADD_URL_RULE_RE.search(line)
            if flask_rule_match:
                route = flask_rule_match.group("route")
                methods = self._parse_methods(flask_rule_match.group("rest"))
                handler = self._parse_python_handler(flask_rule_match.group("rest"))
                for method in methods:
                    records.append(
                        RouteRecord(
                            framework="flask",
                            method=method,
                            route=route,
                            file_path=file_path,
                            line=index,
                            language="python",
                            handler=handler,
                            router=flask_rule_match.group("router"),
                            provenance=_LOCAL_PROVENANCE,
                        )
                    )
                continue
            django_match = _DJANGO_PATH_RE.search(line)
            if django_match:
                records.append(
                    RouteRecord(
                        framework="django",
                        method="ANY",
                        route=django_match.group("route"),
                        file_path=file_path,
                        line=index,
                        language="python",
                        handler=django_match.group("handler"),
                        provenance=_LOCAL_PROVENANCE,
                    )
                )
                continue
            django_url_match = _DJANGO_URL_RE.search(line)
            if django_url_match:
                records.append(
                    RouteRecord(
                        framework="django",
                        method="ANY",
                        route=django_url_match.group("route"),
                        file_path=file_path,
                        line=index,
                        language="python",
                        handler=django_url_match.group("handler"),
                        provenance=_LOCAL_PROVENANCE,
                    )
                )
        return records

    def _extract_js_routes(self, *, file_path: str, lines: list[str], language: str) -> list[RouteRecord]:
        records: list[RouteRecord] = []
        for index, line in enumerate(lines, start=1):
            match = _EXPRESS_ROUTE_RE.search(line)
            if match:
                verb = match.group("verb").upper()
                method = "ANY" if verb in {"ALL", "USE"} else verb
                records.append(
                    RouteRecord(
                        framework="express",
                        method=method,
                        route=match.group("route"),
                        file_path=file_path,
                        line=index,
                        language=language,
                        handler=match.group("handler"),
                        router=match.group("router"),
                        provenance=_LOCAL_PROVENANCE,
                    )
                )
            chain_match = _EXPRESS_ROUTE_CHAIN_RE.search(line)
            if not chain_match:
                continue
            base_route = chain_match.group("route")
            chain = chain_match.group("chain") or ""
            for method_match in _EXPRESS_CHAIN_METHOD_RE.finditer(chain):
                verb = method_match.group("verb").upper()
                method = "ANY" if verb in {"ALL", "USE"} else verb
                records.append(
                    RouteRecord(
                        framework="express",
                        method=method,
                        route=base_route,
                        file_path=file_path,
                        line=index,
                        language=language,
                        handler=method_match.group("handler"),
                        router=chain_match.group("router"),
                        provenance=_LOCAL_PROVENANCE,
                    )
                )
        return records

    def _next_python_def_name(self, lines: list[str], decorator_line: int) -> str | None:
        for line in lines[decorator_line:]:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("@"):
                continue
            match = re.match(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", stripped)
            if match:
                return match.group(1)
            break
        return None

    def _parse_methods(self, value: str | None) -> list[str]:
        if not value:
            return ["GET"]
        methods = [match.group("method").upper() for match in _METHOD_LITERAL_RE.finditer(value)]
        return methods or ["GET"]

    def _parse_python_handler(self, value: str | None) -> str | None:
        if not value:
            return None
        named = re.search(r"view_func\s*=\s*([A-Za-z_][A-Za-z0-9_\.]*)", value)
        if named:
            return named.group(1)
        positional = re.search(r",\s*([A-Za-z_][A-Za-z0-9_\.]*)", value)
        if positional:
            return positional.group(1)
        return None

    def _files_flat(
        self,
        items: list[dict[str, Any]],
        *,
        include_metadata: bool,
    ) -> list[dict[str, Any]]:
        flat: list[dict[str, Any]] = []
        for item in items:
            entry: dict[str, Any] = {"file_path": str(item["file_path"])}
            if include_metadata:
                entry["language"] = str(item.get("language") or "unknown")
                entry["symbol_count"] = int(item.get("symbol_count") or 0)
                entry["top_symbols"] = list(item.get("top_symbols") or [])
            flat.append(entry)
        return flat

    def _files_grouped(
        self,
        items: list[dict[str, Any]],
        *,
        include_metadata: bool,
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            language = str(item.get("language") or "unknown")
            entry: dict[str, Any] = {"file_path": str(item["file_path"])}
            if include_metadata:
                entry["language"] = language
                entry["symbol_count"] = int(item.get("symbol_count") or 0)
                entry["top_symbols"] = list(item.get("top_symbols") or [])
            grouped.setdefault(language, []).append(entry)
        return grouped

    def _files_tree(
        self,
        items: list[dict[str, Any]],
        *,
        include_metadata: bool,
    ) -> dict[str, Any]:
        tree: dict[str, Any] = {}
        for item in items:
            parts = str(item["file_path"]).split("/")
            cursor: dict[str, Any] = tree
            for segment in parts[:-1]:
                child = cursor.get(segment)
                if not isinstance(child, dict):
                    child = {}
                    cursor[segment] = child
                cursor = child
            file_name = parts[-1]
            if include_metadata:
                cursor[file_name] = {
                    "language": str(item.get("language") or "unknown"),
                    "symbol_count": int(item.get("symbol_count") or 0),
                }
            else:
                cursor[file_name] = {}
        return tree

    def _format_files_payload(
        self,
        items: list[dict[str, Any]],
        *,
        format: Literal["tree", "flat", "grouped"],
        include_metadata: bool,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        if format == "flat":
            return self._files_flat(items, include_metadata=include_metadata)
        if format == "grouped":
            return self._files_grouped(items, include_metadata=include_metadata)
        return self._files_tree(items, include_metadata=include_metadata)

    def _build_files_payload(
        self,
        items: list[dict[str, Any]],
        *,
        path: str | None,
        pattern: str | None,
        format: Literal["tree", "flat", "grouped"],
        include_metadata: bool,
        truncated: bool,
    ) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_root": str(self.repo_root),
            "path": path,
            "pattern": pattern,
            "format": format,
            "file_count": len(items),
            "files": self._format_files_payload(items, format=format, include_metadata=include_metadata),
            "truncated": truncated,
            "cache_hit": False,
            "provenance": _LOCAL_PROVENANCE,
        }

    def _build_routes_payload(
        self,
        items: list[dict[str, Any]],
        *,
        file_glob: str | None,
        language: str | None,
        truncated: bool,
    ) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_root": str(self.repo_root),
            "file_glob": file_glob,
            "language": language,
            "route_count": len(items),
            "routes": items,
            "truncated": truncated,
            "cache_hit": False,
            "provenance": _LOCAL_PROVENANCE,
        }

    def _python_text_search(self, query: str, search_path: Path, *, limit: int, ignore_case: bool) -> list[TextMatch]:
        query_cmp = query.lower() if ignore_case else query
        paths = [search_path] if search_path.is_file() else iter_source_files(search_path)
        matches: list[TextMatch] = []
        for path in paths:
            rel = _safe_relpath(self.repo_root, path)
            for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                hay = line.lower() if ignore_case else line
                column = hay.find(query_cmp)
                if column >= 0:
                    matches.append(TextMatch(file_path=rel, line=line_no, column=column + 1, text=line))
                    if len(matches) >= limit:
                        return matches
        return matches

    def _register_symbol_intel_providers(self) -> None:
        try:
            from atelier.infra.code_intel.scip import ScipSymbolIntelProvider
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return
        self.intel_store.register(
            ScipSymbolIntelProvider(
                repo_root=self.repo_root,
                repo_id=self.repo_id,
                state_sync=self._sync_external_artifact_state,
            )
        )

    def _sync_symbol_intel(self) -> None:
        self.intel_store.refresh()

    def _sync_external_artifact_state(self, state_key: str, signature: str) -> bool:
        with self._connect() as conn:
            self._init_schema(conn)
            row = conn.execute("SELECT value FROM engine_state WHERE key = ?", (state_key,)).fetchone()
            previous = str(row["value"]) if row is not None else None
            conn.execute(
                """
                INSERT INTO engine_state(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (state_key, signature),
            )
            if previous is not None and previous != signature:
                self._bump_index_version(conn)
                return True
        return False

    def _parse_autosync_debounce(self, raw_value: str | None) -> int:
        if raw_value is None:
            return 500
        with contextlib.suppress(ValueError):
            return max(50, int(raw_value))
        return 500

    def _autosync_status(self) -> dict[str, Any]:
        return {
            "enabled": self._autosync_enabled,
            "state": self._autosync_state,
            "mode": "incremental" if self._autosync_enabled else "scaffold_only",
            "debounce_ms": self._autosync_debounce_ms,
            "poll_ms": self._autosync_poll_ms,
            "pending_events": self._autosync_pending_events,
            "last_event_at": self._autosync_last_event_at,
            "reindex_count": self._autosync_reindex_count,
            "history": list(self._autosync_history),
        }

    def _source_tree_signature(self) -> str:
        parts: list[str] = []
        repo_root_str = str(self.repo_root)
        for path in iter_source_files(self.repo_root):
            with contextlib.suppress(OSError):
                stat = path.stat()
                # iter_source_files yields paths rooted at self.repo_root, so compute the
                # relative key with a pure-string op. _safe_relpath() would call realpath()
                # per file -- an O(files x path-depth) syscall storm that made this change
                # detector take minutes on large repos (e.g. VS Code).
                rel = os.path.relpath(path, repo_root_str)
                parts.append(f"{rel}|{stat.st_mtime_ns}|{stat.st_size}")
        digest_input = "\n".join(sorted(parts)).encode("utf-8")
        return hashlib.sha256(digest_input).hexdigest()

    def _maybe_autosync_reindex(self) -> None:
        if not self._autosync_lock.acquire(blocking=False):
            return
        try:
            self._maybe_autosync_reindex_locked()
        finally:
            self._autosync_lock.release()

    def _maybe_autosync_reindex_locked(self) -> None:
        current_signature = self._source_tree_signature()
        if self._autosync_signature is None:
            self._autosync_signature = current_signature
            self._autosync_last_sync_ms = int(time.time() * 1000)
            self._autosync_state = "idle"
            self._record_autosync_event(event="bootstrap", reason="seed_signature", reindexed=False)
            return
        if current_signature == self._autosync_signature:
            self._autosync_state = "idle"
            self._autosync_pending_events = 0
            return
        now_ms = int(time.time() * 1000)
        self._autosync_last_event_at = datetime.now(UTC).isoformat()
        self._autosync_pending_events = max(1, self._autosync_pending_events + 1)
        if now_ms - self._autosync_last_sync_ms < self._autosync_debounce_ms:
            self._autosync_state = "debouncing"
            self._record_autosync_event(event="change_detected", reason="within_debounce_window", reindexed=False)
            return
        self._autosync_state = "syncing"
        self.index_repo(force=False, block=False)
        self._autosync_signature = self._source_tree_signature()
        self._autosync_last_sync_ms = int(time.time() * 1000)
        self._autosync_pending_events = 0
        self._autosync_state = "idle"
        self._autosync_reindex_count += 1
        self._record_autosync_event(event="reindex", reason="source_signature_changed", reindexed=True)

    def _parse_autosync_poll_ms(self, raw_value: str | None) -> int:
        if raw_value is None:
            return 10000
        with contextlib.suppress(ValueError):
            return max(1000, int(raw_value))
        return 10000

    def _start_autosync_worker(self) -> None:
        if self._autosync_thread is not None:
            return
        self._autosync_thread = threading.Thread(
            target=self._autosync_worker_loop,
            name=f"atelier-code-autosync-{self.repo_id[:8]}",
            daemon=True,
        )
        self._autosync_thread.start()
        weakref.finalize(self, self._stop_autosync_worker)

    def _stop_autosync_worker(self) -> None:
        self._autosync_stop.set()

    def _autosync_worker_loop(self) -> None:
        try:
            self._deleted_history_adapter().start_background_warmup()
        except Exception:
            logging.exception("Failed to start background warmup")
        # Background-owned initial build: if nothing has populated the index yet
        # (no external prewarm / `atelier code index`), build it here so the
        # first tool call hits a warm index instead of paying a cold build on the
        # request path.
        if not self.index_ready():
            try:
                self.index_repo(force=False, block=False)
            except Exception:
                logging.exception("autosync: initial index build failed")
        if getattr(self, "_embed_prewarmed", False) is False:
            try:
                self._prewarm_symbol_embeddings()
            except Exception:
                logging.exception("Failed to prewarm symbol embeddings")
            self._embed_prewarmed = True
        if not getattr(self, "_scip_triggered", False):
            try:
                self.trigger_scip_indexing()
            except Exception:
                logging.exception("Failed to trigger SCIP indexing")
            self._scip_triggered = True
        while not self._autosync_stop.wait(self._autosync_poll_ms / 1000.0):
            try:
                if not self.index_ready():
                    # Still empty (e.g. the initial build lost an index-lock race
                    # with a concurrent prewarm). Keep retrying until it exists.
                    self.index_repo(force=False, block=False)
                else:
                    self._maybe_autosync_reindex()
            except Exception as exc:
                logging.exception("Recovered from broad exception handler")
                self._record_autosync_event(event="worker_error", reason=str(exc), reindexed=False)

    def trigger_scip_indexing(self) -> dict[str, str]:
        """Run SCIP indexers for languages detected in this repo.

        Only attempts languages whose indexer binary is installed (tier:
        ``install_time``).  Silently skips any language whose binary is absent
        or whose SCIP module cannot be imported.  Returns ``{language: status}``
        for each attempted language so callers can log progress.
        """
        try:
            from atelier.infra.code_intel.scip.bootstrap import _BOOTSTRAP_METADATA
            from atelier.infra.code_intel.scip.indexer import ScipIndexer
        except ImportError:
            return {}

        indexer = ScipIndexer(self.repo_root, self.repo_id)
        install_time = {lang for lang, m in _BOOTSTRAP_METADATA.items() if m.tier == "install_time"}
        detected = self._detected_repo_languages() & install_time
        if not detected:
            return {}

        results: dict[str, str] = {}
        for lang in sorted(detected):
            try:
                result = indexer.index_language(lang)
                results[lang] = result.status
            except Exception as exc:
                logging.exception("SCIP indexing failed for %s", lang)
                results[lang] = f"error: {exc}"
        return results

    def _detected_repo_languages(self) -> frozenset[str]:
        """Lightweight language detection from file extensions in the symbol index."""
        ext_map = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
        }
        langs: set[str] = set()
        try:
            with self._connect(readonly=True) as conn:
                for row in conn.execute(
                    "SELECT path FROM files WHERE repo_id = ? LIMIT 2000",
                    (self.repo_id,),
                ):
                    ext = Path(row[0]).suffix.lower()
                    if ext in ext_map:
                        langs.add(ext_map[ext])
        except sqlite3.Error:
            pass
        return frozenset(langs)

    def _prewarm_symbol_embeddings(self) -> None:
        """Pre-populate vector_cache for all indexed symbols.

        Called once from the autosync worker after the FTS index is ready.
        Converts the first semantic search from O(N) embed calls to a single
        SQLite scan. Skipped when no semantic ranker is configured.

        Gated behind the opt-in ANN flag: with ANN retrieval off, the default
        semantic path must stay byte-identical and must NOT create the opt-in
        ``symbol_vectors`` table, so the prewarm is skipped entirely.
        """
        if not ann_retrieval_enabled():
            return
        if not self._semantic_ranker.available:
            return
        embedder = self._semantic_ranker.embedder
        embedding_dim = embedder.dim
        if embedding_dim <= 0:
            return
        index_version = self._current_index_version()
        candidates = self._semantic_symbol_candidates(limit=2000)
        if not candidates:
            return
        with contextlib.closing(self._connect()) as conn:
            self._init_schema(conn)
            fresh_ids = self._ann_symbol_index.existing_stamped_ids(
                conn,
                embedder_name=embedder.name,
                embedding_dim=embedding_dim,
                index_version=index_version,
            )
            to_embed = [symbol for symbol in candidates if symbol.symbol_id not in fresh_ids]
            source_texts = {
                symbol.symbol_id: self._read_file_slice(symbol.file_path, symbol.start_byte, symbol.end_byte)
                for symbol in to_embed
            }
            embedded = self._semantic_ranker.embed_symbols(to_embed, source_texts=source_texts)
            content_hash_by_id = {symbol.symbol_id: symbol.content_hash for symbol in to_embed}
            new_vectors: dict[str, tuple[str, list[float]]] = {
                symbol_id: (content_hash_by_id[symbol_id], vector)
                for symbol_id, vector in embedded.items()
                if len(vector) == embedding_dim
            }
            if new_vectors:
                self._ann_symbol_index.upsert_vectors(
                    conn,
                    embedder_name=embedder.name,
                    embedding_dim=embedding_dim,
                    index_version=index_version,
                    vectors=new_vectors,
                )

    def _record_autosync_event(self, *, event: str, reason: str, reindexed: bool) -> None:
        entry = {
            "at": datetime.now(UTC).isoformat(),
            "event": event,
            "reason": reason,
            "reindexed": reindexed,
        }
        self._autosync_history.append(entry)
        if len(self._autosync_history) > 20:
            self._autosync_history = self._autosync_history[-20:]

    def _json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]
        return str(value)

    def _current_head_sha(self) -> str:
        from atelier.infra.code_intel.git_history import require_pygit2

        pygit2 = require_pygit2()
        repo = pygit2.Repository(str(self.repo_root))
        return str(repo.revparse_single("HEAD").id)

    def _safe_current_head_sha(self) -> str | None:
        with contextlib.suppress(Exception):
            value = self._current_head_sha()
            if value is None:
                return None
            return str(value)
        return None

    def _lineage_embedder_metadata(self) -> tuple[str, int]:
        from atelier.infra.code_intel.git_history.embedder import embedder_name, embedding_dim

        return embedder_name(), embedding_dim()

    def _persist_lineage_embedder_metadata(self, conn: sqlite3.Connection, *, name: str, dim: int) -> None:
        conn.executemany(
            "INSERT INTO engine_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [
                ("commit_lineage_embedder_name", name),
                ("commit_lineage_embedder_dim", str(dim)),
            ],
        )

    def _ensure_lineage_ready(self) -> None:
        """Start background lineage bootstrap if commit_chunks is empty or stale.

        Non-blocking: launches a daemon thread. Safe to call multiple times.

        Disabled by default: the commit-summary lineage walker makes one LLM
        summarize call per commit, which is prohibitively slow on deep-history
        repos (~26-40 min on VS Code). Opt in with ATELIER_LINEAGE_ENABLED=1.
        The graveyard walker (deleted/renamed symbols) is independent and stays on.
        """
        if os.getenv("ATELIER_LINEAGE_ENABLED") != "1":
            return
        with self._lineage_lock:
            if self._lineage_thread is not None:
                return
        current_head = self._safe_current_head_sha()
        if current_head is None:
            return
        current_embedder_name, current_embedder_dim = self._lineage_embedder_metadata()
        needs_update = False
        full_rebuild = False
        with contextlib.suppress(Exception), contextlib.closing(self._connect()) as conn:
            self._init_schema(conn)
            head_row = conn.execute("SELECT value FROM engine_state WHERE key = 'commit_lineage_head'").fetchone()
            previous_head = str(head_row["value"]) if head_row is not None else None
            embedder_name_row = conn.execute(
                "SELECT value FROM engine_state WHERE key = 'commit_lineage_embedder_name'"
            ).fetchone()
            stored_embedder_name = str(embedder_name_row["value"]) if embedder_name_row is not None else None
            embedder_dim_row = conn.execute(
                "SELECT value FROM engine_state WHERE key = 'commit_lineage_embedder_dim'"
            ).fetchone()
            stored_embedder_dim = int(embedder_dim_row["value"]) if embedder_dim_row is not None else None
            count_row = conn.execute("SELECT COUNT(*) AS n FROM commit_chunks").fetchone()
            chunk_count = int(count_row["n"]) if count_row is not None else 0
            stale_row = conn.execute(
                "SELECT COUNT(*) AS n FROM commit_chunks WHERE index_version < ?",
                (_LINEAGE_INDEX_VERSION,),
            ).fetchone()
            has_stale = stale_row is not None and int(stale_row["n"]) > 0
            metadata_changed = (
                stored_embedder_name != current_embedder_name or stored_embedder_dim != current_embedder_dim
            )
            has_lineage_state = (
                previous_head is not None or stored_embedder_name is not None or stored_embedder_dim is not None
            )
            full_rebuild = chunk_count > 0 and has_lineage_state and (has_stale or metadata_changed)
            if full_rebuild or previous_head != current_head or chunk_count == 0:
                needs_update = True
        if not needs_update:
            return
        with self._lineage_lock:
            # Re-check under the lock so two concurrent read tools cannot both pass
            # the initial guard and each spawn a bootstrap thread.
            if self._lineage_thread is not None:
                return
            self._lineage_rebuild_full = full_rebuild
            self._lineage_thread = threading.Thread(
                target=self._lineage_bootstrap_worker,
                name=f"atelier-lineage-{self.repo_id[:8]}",
                daemon=True,
            )
        self._lineage_thread.start()

    def _lineage_bootstrap_worker(self) -> None:
        """Background thread: walk, summarise, embed, persist commit chunks."""
        try:
            with contextlib.closing(self._connect()) as conn:
                self._init_schema(conn)
                watermark_row = conn.execute(
                    "SELECT value FROM engine_state WHERE key = 'commit_lineage_watermark'"
                ).fetchone()
                since_sha = (
                    None
                    if self._lineage_rebuild_full
                    else (str(watermark_row["value"]) if watermark_row is not None else None)
                )
            self._walk_and_summarise(since_sha=since_sha, full_rebuild=self._lineage_rebuild_full)
        except Exception:
            logging.exception("Recovered from broad exception handler")
            logger.debug(
                "lineage bootstrap failed", exc_info=True
            )  # fail-open — lineage is additive, never blocks search
        finally:
            self._lineage_rebuild_full = False

    def _walk_and_summarise(self, *, since_sha: str | None, full_rebuild: bool = False) -> None:
        """Walk commits, summarise, embed, upsert to commit_chunks in batches of 50.

        Two-pass design: summarise all commits first (LLM), then embed all summaries
        (vector model). This avoids contention when both operations share the same
        backend (e.g. a local Ollama server that serialises requests).
        """
        from atelier.infra.code_intel.git_history import require_pygit2
        from atelier.infra.code_intel.git_history.embedder import embed_summary
        from atelier.infra.code_intel.git_history.models import CommitSummary
        from atelier.infra.code_intel.git_history.summarizer import (
            SummarizerError,
            summarize_commit,
        )
        from atelier.infra.code_intel.git_history.walker import iter_commit_records

        def _get_diff_text(repo: Any, commit: Any) -> str:
            try:
                if not commit.parents:
                    return ""
                parent = commit.parents[0]
                diff = parent.tree.diff_to_tree(commit.tree)
                return diff.patch or ""
            except Exception:
                logging.exception("Recovered from broad exception handler")
                return ""

        pygit2 = require_pygit2()
        repo = pygit2.Repository(str(self.repo_root))

        # Pass 1: summarise all commits (LLM calls — no embedding yet)
        summaries: list[CommitSummary] = []
        for record in iter_commit_records(self.repo_root, since_sha=since_sha):
            try:
                commit_obj = repo.revparse_single(record.sha)
                diff_text = _get_diff_text(repo, commit_obj)
            except Exception:
                logging.exception("Recovered from broad exception handler")
                diff_text = ""

            try:
                summary = summarize_commit(record, diff_text=diff_text)
            except SummarizerError:
                continue
            except Exception:
                logging.exception("Recovered from broad exception handler")
                continue
            summaries.append(summary)

        # Pass 2: embed + persist (vector calls — LLM is now idle)
        batch: list[tuple[Any, ...]] = []
        rebuild_rows: list[tuple[Any, ...]] = []

        for summary in summaries:
            try:
                embedding_blob = embed_summary(summary)
            except Exception:
                logging.exception("Recovered from broad exception handler")
                embedding_blob = None

            row = (
                summary.sha,
                summary.author_date,
                json.dumps(summary.files_touched),
                None,  # symbols_touched — deferred to follow-up phase
                summary.summary,
                summary.summary_model,
                embedding_blob,
                _LINEAGE_INDEX_VERSION,
            )
            if full_rebuild:
                rebuild_rows.append(row)
                continue

            batch.append(row)

            if len(batch) >= 50:
                self._flush_commit_batch(batch, watermark_sha=batch[-1][0])
                batch.clear()

        if full_rebuild:
            watermark_sha = rebuild_rows[-1][0] if rebuild_rows else None
            self._replace_commit_chunks(rebuild_rows, watermark_sha=watermark_sha)
        elif batch:
            self._flush_commit_batch(batch, watermark_sha=batch[-1][0])

        current_head = self._safe_current_head_sha()
        if current_head:
            current_embedder_name, current_embedder_dim = self._lineage_embedder_metadata()
            with contextlib.closing(self._connect()) as conn:
                self._persist_lineage_embedder_metadata(conn, name=current_embedder_name, dim=current_embedder_dim)
                conn.execute(
                    "INSERT INTO engine_state(key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    ("commit_lineage_head", current_head),
                )
                conn.commit()

    def _replace_commit_chunks(self, rows: list[tuple[Any, ...]], *, watermark_sha: str | None) -> None:
        """Atomically replace commit lineage rows after a full rebuild completes."""
        with contextlib.closing(self._connect()) as conn:
            self._init_schema(conn)
            conn.execute("DELETE FROM commit_chunks")
            if rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO commit_chunks
                       (commit_sha, author_date, files_touched, symbols_touched,
                        summary, summary_model, embedding, index_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
            if watermark_sha is None:
                conn.execute("DELETE FROM engine_state WHERE key = 'commit_lineage_watermark'")
            else:
                conn.execute(
                    "INSERT INTO engine_state(key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    ("commit_lineage_watermark", watermark_sha),
                )
            conn.commit()

    def _flush_commit_batch(self, batch: list[tuple[Any, ...]], *, watermark_sha: str) -> None:
        """Upsert a batch of commit chunks and advance the resume watermark."""
        with contextlib.closing(self._connect()) as conn:
            self._init_schema(conn)
            conn.executemany(
                """INSERT OR REPLACE INTO commit_chunks
                   (commit_sha, author_date, files_touched, symbols_touched,
                    summary, summary_model, embedding, index_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                batch,
            )
            conn.execute(
                "INSERT INTO engine_state(key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("commit_lineage_watermark", watermark_sha),
            )
            conn.commit()

    def _search_commit_chunks(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[SymbolRecord]:
        """Embed query and return top-limit commit chunks as SymbolRecord objects.

        Each result has provenance="commit" and commit_sha set.
        Applies ATELIER_LINEAGE_COMMIT_SCORE_PENALTY (default 0.1) to the score.
        Returns [] if commit_chunks is empty or embeddings unavailable.
        """
        from atelier.infra.code_intel.git_history.embedder import decode_embedding
        from atelier.infra.storage.vector import cosine_similarity

        query_vec: list[float] | None = None
        with contextlib.suppress(Exception):
            query_vec = self._semantic_ranker._embed_query(query)

        if not query_vec:
            return []

        rows: list[sqlite3.Row] = []
        with contextlib.suppress(Exception), contextlib.closing(self._connect()) as conn:
            self._init_schema(conn)
            rows = conn.execute(
                "SELECT commit_sha, author_date, files_touched, summary, summary_model, embedding "
                "FROM commit_chunks WHERE embedding IS NOT NULL "
                "ORDER BY author_date DESC LIMIT 2000"
            ).fetchall()

        if not rows:
            return []

        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            try:
                stored_vec = decode_embedding(bytes(row["embedding"]))
                sim = cosine_similarity(query_vec, stored_vec)
                adjusted = sim - self._lineage_score_penalty
                scored.append((adjusted, row))
            except Exception:
                logging.exception("Recovered from broad exception handler")
                continue

        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:limit]

        results: list[SymbolRecord] = []
        for score_val, row in top:
            try:
                files = json.loads(row["files_touched"]) if row["files_touched"] else []
                primary_file = files[0] if files else ""
                sha = str(row["commit_sha"])
                results.append(
                    SymbolRecord(
                        symbol_id=sha,
                        repo_id=self.repo_id,
                        file_path=primary_file,
                        language="",
                        symbol_name=sha[:8],
                        qualified_name=str(row["summary"])[:80],
                        kind="commit",
                        signature=str(row["summary"]),
                        start_byte=0,
                        end_byte=0,
                        start_line=0,
                        end_line=0,
                        content_hash=sha,
                        score=round(score_val, 4),
                        provenance="commit",
                        commit_sha=sha,
                    )
                )
            except Exception:
                logging.exception("Recovered from broad exception handler")
                continue
        return results

    def _deleted_history_adapter(self) -> DeletedHistorySearchAdapter:
        if self._deleted_history_search_adapter is None:
            from atelier.infra.code_intel.git_history.adapter import DeletedHistorySearchAdapter

            self._deleted_history_search_adapter = DeletedHistorySearchAdapter(
                repo_root=self.repo_root,
                repo_id=self.repo_id,
                connection_factory=self.connection,
            )
        return self._deleted_history_search_adapter


__all__ = ["CodeContextEngine"]
