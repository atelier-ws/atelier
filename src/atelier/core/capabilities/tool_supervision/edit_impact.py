"""Evidence-only post-edit discovery for contract literals removed by an edit.

Renames and deprecations often span independent consumers with no call-graph edge
to the edited site: configuration keys, wire fields, and dict literals are plain
strings, invisible to symbol-level callers/callees/usages. When an edit removes a
quoted literal, surface the remaining occurrences in *other* files so the agent can
inspect parallel consumers while its implementation hypothesis is still revisable.

Detection combines two layers for precision *and* recall: ast-grep (the engine
behind the ``codemod`` tool) matches the literal as a string *node*, so it is precise
for code files -- it never matches the same text inside a larger string, a docstring,
or a comment. A language-agnostic text search (guarded by a structural heuristic)
adds the non-code consumers ast-grep can't parse (config, templates, docs). ast-grep
is authoritative for any code file it covers; text contributes the rest, and is the
sole path when the ast-grep binary is unavailable.

This module only extracts the literals and shapes the evidence. It never blocks or
rolls back an edit, and fails open (returns ``None``) on any error.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

_QUOTED_LITERAL_RE = re.compile(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"|`((?:\\.|[^`\\])*)`")
_NOISY_LITERALS = frozenset({"", "0", "1", "false", "none", "null", "true"})
_QUOTES = ("'", '"', "`")
_DELIMITERS = frozenset("[]{}():,=")
_MAX_FILE_BYTES = 1_000_000

# Edited-file extension -> ast-grep language name. ast-grep matches per language,
# so detection covers the language(s) of the files actually edited.
_EXT_TO_ASTGREP_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
}


class _TextSearcher(Protocol):
    """The slice of ``CodeContextEngine`` the text fallback depends on."""

    def search_text(self, query: str, *, path: str = ..., limit: int = ..., ignore_case: bool = ...) -> list[Any]: ...


def _quoted_literals(text: str) -> set[str]:
    out: set[str] = set()
    for match in _QUOTED_LITERAL_RE.finditer(text):
        literal = next((group for group in match.groups() if group is not None), "")
        # Escaped values can't be searched literally without language-specific
        # decoding; one-character and very long prose strings are noisy.
        if (
            2 <= len(literal) <= 80
            and "\\" not in literal
            and "\n" not in literal
            and literal.strip().lower() not in _NOISY_LITERALS
        ):
            out.add(literal)
    return out


def literal_replacements(edits: list[dict[str, Any]], *, limit: int = 6) -> dict[str, str | None]:
    """Map each removed quoted literal to its line-aligned replacement when identifiable.

    A literal present in ``old_string`` but not ``new_string`` was removed. When a
    single line swaps exactly one literal for exactly one other, that pairing is the
    rename's replacement (e.g. ``'db'`` -> ``'database'``); otherwise the value is
    ``None`` (removed, no confident replacement).
    """
    replacements: dict[str, str | None] = {}
    for edit in edits:
        old = edit.get("old_string")
        new = edit.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            continue
        for literal in _quoted_literals(old) - _quoted_literals(new):
            replacements.setdefault(literal, None)
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        if len(old_lines) != len(new_lines):
            continue
        for old_line, new_line in zip(old_lines, new_lines, strict=True):
            removed = _quoted_literals(old_line) - _quoted_literals(new_line)
            added = _quoted_literals(new_line) - _quoted_literals(old_line)
            if len(removed) == 1 and len(added) == 1:
                replacements[next(iter(removed))] = next(iter(added))
    # Prefer longer literals: more contract-specific, less noisy.
    ordered = sorted(replacements, key=lambda value: (-len(value), value))[:limit]
    return {literal: replacements[literal] for literal in ordered}


def removed_literals(edits: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    """Return quoted literals removed, rather than merely moved, by *edits*."""
    return list(literal_replacements(edits, limit=limit))


def _is_test_path(path: str) -> bool:
    name = Path(path).name.lower()
    parts = {part.lower() for part in Path(path).parts}
    return (
        bool(parts & {"test", "tests", "spec", "specs", "__tests__"})
        or name.startswith(("test_", "spec_"))
        or name.endswith(("_test.py", "_spec.rb"))
    )


def _is_structural_occurrence(line: str, literal: str) -> bool:
    """Text-fallback heuristic: True when the quoted literal is used as code, not prose.

    A real contract key sits next to a delimiter (``['db']``, ``.get('db'``,
    ``{'db':``, ``'db':``). The same token in prose sits between words
    (``the 'db' cache backend``) and is dropped as noise. ast-grep does this
    exactly; this approximates it when ast-grep is unavailable.
    """
    for quote in _QUOTES:
        token = f"{quote}{literal}{quote}"
        idx = line.find(token)
        while idx >= 0:
            before = line[idx - 1] if idx > 0 else ""
            after_index = idx + len(token)
            after = line[after_index] if after_index < len(line) else ""
            if before in _DELIMITERS or after in _DELIMITERS:
                return True
            idx = line.find(token, idx + 1)
    return False


def _astgrep_languages(touched_paths: list[str]) -> list[str]:
    languages: list[str] = []
    for path in touched_paths:
        language = _EXT_TO_ASTGREP_LANG.get(Path(path).suffix.lower())
        if language and language not in languages:
            languages.append(language)
    return languages


def _astgrep_patterns(literal: str) -> list[str]:
    # ast-grep string-literal patterns are quote-sensitive: 'x' matches only
    # single-quoted nodes, "x" only double-quoted. Try both and merge.
    return [f"{quote}{literal}{quote}" for quote in ("'", '"') if quote not in literal]


def _line_lookup(repo_root: Path, cache: dict[str, list[str]], path: str, line: int) -> str:
    lines = cache.get(path)
    if lines is None:
        try:
            target = repo_root / path
            lines = (
                []
                if target.stat().st_size > _MAX_FILE_BYTES
                else target.read_text(encoding="utf-8", errors="replace").splitlines()
            )
        except OSError:
            lines = []
        cache[path] = lines
    return lines[line - 1].strip() if 1 <= line <= len(lines) else ""


def _astgrep_detect(
    literals: list[str], repo_root: Path, touched: set[str], *, languages: list[str], limit: int
) -> dict[str, list[tuple[str, int, str]]] | None:
    """Structural detection via ast-grep. ``None`` means it could not run (caller falls back)."""
    if not languages:
        return None
    try:
        from atelier.infra.code_intel.astgrep import AstGrepAdapter, AstGrepToolUnavailable
    except Exception:  # noqa: BLE001
        return None
    adapter = AstGrepAdapter(repo_root)
    line_cache: dict[str, list[str]] = {}
    out: dict[str, list[tuple[str, int, str]]] = {literal: [] for literal in literals}
    ran = False
    for literal in literals:
        seen: set[tuple[str, int]] = set()
        for language in languages:
            for pattern in _astgrep_patterns(literal):
                try:
                    result = adapter.search(pattern=pattern, language=language, limit=limit)
                except AstGrepToolUnavailable:
                    return None  # binary missing -> let caller use the text fallback
                except Exception:  # noqa: BLE001
                    continue  # malformed pattern for this language, etc.
                ran = True
                for match in result.matches:
                    path = match.file_path
                    if not path or path in touched:
                        continue
                    line = match.line + 1  # ast-grep JSON ranges are 0-based; report 1-based
                    key = (path, line)
                    if key in seen:
                        continue
                    seen.add(key)
                    snippet = _line_lookup(repo_root, line_cache, path, line) or (match.snippet or "").strip()
                    out[literal].append((path, line, snippet))
    return out if ran else None


def _text_detect(
    literals: list[str], engine: _TextSearcher | None, touched: set[str], *, limit: int
) -> dict[str, list[tuple[str, int, str]]]:
    """Language-agnostic fallback: engine text search + structural-occurrence heuristic."""
    out: dict[str, list[tuple[str, int, str]]] = {literal: [] for literal in literals}
    if engine is None:
        return out
    for literal in literals:
        seen: set[tuple[str, int]] = set()
        for quote in _QUOTES:
            try:
                hits = engine.search_text(f"{quote}{literal}{quote}", limit=limit)
            except Exception:  # noqa: BLE001
                continue
            for hit in hits:
                path = getattr(hit, "file_path", None)
                line = getattr(hit, "line", None)
                text = getattr(hit, "text", "") or ""
                if not isinstance(path, str) or not isinstance(line, int) or path in touched:
                    continue
                if not _is_structural_occurrence(text, literal):
                    continue
                key = (path, line)
                if key in seen:
                    continue
                seen.add(key)
                out[literal].append((path, line, text.strip()))
    return out


def _combine_matches(
    astgrep_matches: list[tuple[str, int, str]] | None,
    text_matches: list[tuple[str, int, str]],
) -> list[tuple[str, int, str]]:
    """Best of both: ast-grep is authoritative for code files; text adds only the
    non-code files (config, templates, docs) ast-grep can't parse."""
    if astgrep_matches is None:
        return list(text_matches)  # ast-grep unavailable -> pure text recall
    seen = {(path, line) for path, line, _ in astgrep_matches}
    combined = list(astgrep_matches)
    for path, line, snippet in text_matches:
        if Path(path).suffix.lower() in _EXT_TO_ASTGREP_LANG:
            continue  # code file -> ast-grep already covered it precisely
        if (path, line) in seen:
            continue
        seen.add((path, line))
        combined.append((path, line, snippet))
    return combined


def contract_literal_impact(
    edits: list[dict[str, Any]],
    *,
    engine: _TextSearcher | None,
    repo_root: Path,
    touched_paths: list[str],
    max_matches_per_literal: int = 4,
    search_limit: int = 30,
) -> dict[str, Any] | None:
    """Return remaining occurrences of literals removed by *edits*, in untouched files.

    Detection prefers ast-grep (structural, precise); it degrades to *engine* text
    search when ast-grep can't run. Matches inside *touched_paths* are excluded --
    only parallel consumers the agent may have missed are evidence. Returns ``None``
    when no literal was removed or nothing remains elsewhere.
    """
    replacements = literal_replacements(edits)
    if not replacements:
        return None
    touched = set(touched_paths)
    literals = list(replacements)

    # Recall layer: language-agnostic text search (heuristic-filtered) finds
    # candidates anywhere, including non-code config/templates ast-grep can't parse.
    text_by_literal = _text_detect(literals, engine, touched, limit=search_limit)
    # Precision layer: ast-grep over every code language that actually appears
    # (edited files + text candidates). It is authoritative for code files --
    # matching string *nodes* drops the docstring/comment false positives that the
    # text heuristic only approximates away.
    candidate_paths = [match[0] for matches in text_by_literal.values() for match in matches]
    languages = _astgrep_languages(list(touched) + candidate_paths)
    astgrep_by_literal = _astgrep_detect(literals, repo_root, touched, languages=languages, limit=search_limit)

    residuals: list[dict[str, Any]] = []
    for literal in literals:
        astgrep_found = astgrep_by_literal.get(literal) if astgrep_by_literal is not None else None
        found = _combine_matches(astgrep_found, text_by_literal.get(literal) or [])
        if not found:
            continue
        # Production consumers before tests, then stable by location.
        found.sort(key=lambda match: (_is_test_path(match[0]), match[0], match[1]))
        rendered = [
            {"path": path, "line": line, "snippet": snippet[:240]}
            for path, line, snippet in found[:max_matches_per_literal]
        ]
        residuals.append({"removed": literal, "replacement": replacements[literal], "matches": rendered})
    if not residuals:
        return None
    return {
        "status": "review_required",
        "reason": (
            "This edit removed contract literals that still occur in other files. These are "
            "parallel consumers (config keys, wire fields, adapters, tests) with no call-graph "
            "link to the edited site -- inspect each before concluding the change is complete. "
            "For a compatibility rename, prefer the new key and fall back to the legacy key."
        ),
        "remaining_contract_consumers": residuals,
    }


# --------------------------------------------------------------------------- #
# Sibling-implementation discovery                                            #
#                                                                             #
# Some parallel implementations of one behavior share neither a call-graph    #
# edge nor a quoted contract literal -- only a cluster of distinctive API     #
# identifiers (e.g. two functions that both drive a matplotlib formatter:     #
# ``formatter``/``locator``/``format_ticks``). When an edit changes such a    #
# function, surface the other functions that reference the same *rare*        #
# identifier cluster so the agent can apply the change there too. Rarity is    #
# what makes this precise: an identifier in many files carries no signal and   #
# is dropped; only identifiers shared by a handful of files count, and a       #
# sibling must share several of them. No embedder required (the offline        #
# hashing backend can't rank semantic siblings); this is pure co-occurrence.   #
# --------------------------------------------------------------------------- #

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CONTEXT_LINES = 30

# Identifiers too common to carry a sibling signal. Rarity (file-count) filtering
# does the real work; this just avoids spending a search on tokens we'd discard.
_COMMON_IDENTIFIERS = frozenset(
    {
        "async",
        "await",
        "break",
        "class",
        "const",
        "continue",
        "default",
        "except",
        "finally",
        "function",
        "global",
        "import",
        "lambda",
        "nonlocal",
        "raise",
        "return",
        "super",
        "while",
        "yield",
        "false",
        "none",
        "null",
        "true",
        "undefined",
        "this",
        "self",
        "cls",
        "append",
        "array",
        "bool",
        "bytes",
        "count",
        "data",
        "dict",
        "error",
        "errors",
        "extend",
        "field",
        "fields",
        "float",
        "format",
        "index",
        "input",
        "items",
        "keys",
        "kwargs",
        "list",
        "name",
        "names",
        "number",
        "object",
        "options",
        "output",
        "params",
        "print",
        "range",
        "result",
        "results",
        "source",
        "start",
        "string",
        "target",
        "tuple",
        "type",
        "value",
        "values",
        "config",
        "content",
        "context",
        "method",
        "module",
        "update",
    }
)


def _candidate_identifiers(text: str, *, limit: int) -> list[str]:
    """Distinctive-looking identifiers from *text*, longest first (capped at *limit*).

    Drops keywords/builtins, short tokens, and private/dunder names. Rarity
    filtering downstream removes whatever common tokens slip through.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _IDENTIFIER_RE.finditer(text):
        token = match.group(0)
        if len(token) < 5 or token.startswith("_"):
            continue
        if token.lower() in _COMMON_IDENTIFIERS:
            continue
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    # Longer identifiers are more likely to be distinctive API names.
    ordered.sort(key=lambda token: (-len(token), token))
    return ordered[:limit]


def _anchor_line(lines: list[str], new_string: str) -> int:
    """Index of the first file line that contains a substantive line of *new_string*."""
    for raw in new_string.splitlines():
        needle = raw.strip()
        if len(needle) >= 4:
            for i, line in enumerate(lines):
                if needle in line:
                    return i
    return -1


def _edit_context_windows(edits: list[dict[str, Any]], repo_root: Path, touched: set[str]) -> list[str]:
    """Post-edit source windows (the enclosing region of each code edit)."""
    windows: list[str] = []
    for edit in edits:
        path = edit.get("file_path") or edit.get("path")
        new = edit.get("new_string")
        if not isinstance(path, str) or not isinstance(new, str):
            continue
        display = path.split("#", 1)[0]
        if Path(display).suffix.lower() not in _EXT_TO_ASTGREP_LANG:
            continue  # code files only
        try:
            content = (repo_root / display).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(content) > _MAX_FILE_BYTES:
            continue
        lines = content.splitlines()
        anchor = _anchor_line(lines, new)
        if anchor < 0:
            continue
        lo = max(0, anchor - _CONTEXT_LINES)
        hi = min(len(lines), anchor + _CONTEXT_LINES)
        windows.append("\n".join(lines[lo:hi]))
    return windows


def _files_referencing(engine: _TextSearcher, symbol: str, touched: set[str], *, limit: int) -> set[str]:
    """Untouched code files that reference *symbol* as a whole word."""
    out: set[str] = set()
    word = re.compile(rf"\b{re.escape(symbol)}\b")
    try:
        hits = engine.search_text(symbol, limit=limit)
    except Exception:  # noqa: BLE001
        return out
    for hit in hits:
        path = getattr(hit, "file_path", None)
        text = getattr(hit, "text", "") or ""
        if not isinstance(path, str) or path in touched:
            continue
        if Path(path).suffix.lower() not in _EXT_TO_ASTGREP_LANG:
            continue
        if word.search(text):
            out.add(path)
    return out


def sibling_symbol_impact(
    edits: list[dict[str, Any]],
    *,
    engine: _TextSearcher | None,
    repo_root: Path,
    touched_paths: list[str],
    max_candidates: int = 24,
    max_files_per_symbol: int = 8,
    min_shared: int = 3,
    max_siblings: int = 3,
    search_limit: int = 80,
) -> dict[str, Any] | None:
    """Return untouched functions that share a distinctive identifier cluster with an edit.

    A candidate identifier counts only when it is *rare* (referenced in at most
    ``max_files_per_symbol`` untouched files) and present somewhere other than the
    edited file; a sibling file must share at least ``min_shared`` such rare
    identifiers. Returns ``None`` when nothing qualifies. Needs no embedder.
    """
    if engine is None:
        return None
    touched = set(touched_paths)
    windows = _edit_context_windows(edits, repo_root, touched)
    if not windows:
        return None
    candidates: list[str] = []
    for window in windows:
        for token in _candidate_identifiers(window, limit=max_candidates):
            if token not in candidates:
                candidates.append(token)
    candidates = candidates[:max_candidates]
    if not candidates:
        return None

    shared_by_file: dict[str, list[str]] = {}
    for symbol in candidates:
        files = _files_referencing(engine, symbol, touched, limit=search_limit)
        if not files or len(files) > max_files_per_symbol:
            continue  # absent elsewhere, or too common to signal a sibling
        for path in files:
            shared_by_file.setdefault(path, []).append(symbol)

    siblings = [(path, syms) for path, syms in shared_by_file.items() if len(syms) >= min_shared]
    if not siblings:
        return None
    siblings.sort(key=lambda item: (_is_test_path(item[0]), -len(item[1]), item[0]))
    rendered = [{"path": path, "shared_symbols": sorted(syms)[:8]} for path, syms in siblings[:max_siblings]]
    return {
        "status": "review_required",
        "reason": (
            "This edit changed a function that shares a distinctive cluster of API symbols "
            "with the functions below -- likely parallel implementations of the same behavior, "
            "with no call-graph or contract-literal link to the edited site. If your change is "
            "a behavior the codebase applies in parallel, apply it there too (or confirm it "
            "does not belong) before concluding."
        ),
        "sibling_implementations": rendered,
    }


__all__ = [
    "contract_literal_impact",
    "literal_replacements",
    "removed_literals",
    "sibling_symbol_impact",
]
