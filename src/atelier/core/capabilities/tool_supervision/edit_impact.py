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

# Decorators whose removal silently strips attributes/methods callers may use, with
# no call-graph edge to surface the breakage. ``functools.lru_cache``/``cache`` add
# ``.cache_clear``/``.cache_info``/``.cache_parameters`` to the wrapped function;
# removing the decorator makes every ``fn.cache_clear()`` elsewhere an AttributeError.
# Generic stdlib contract -- not project-specific. Extend this map (e.g. cached_property)
# as other attribute-providing decorators prove worth surfacing.
_DECORATOR_PROVIDED_ATTRS: dict[str, tuple[str, ...]] = {
    "lru_cache": ("cache_clear", "cache_info", "cache_parameters"),
    "cache": ("cache_clear", "cache_info", "cache_parameters"),
}
# A cache decorator immediately above a (possibly async) def -- captures both.
_CACHE_DECORATED_DEF_RE = re.compile(
    r"@(?:\w+\.)*(?P<deco>" + "|".join(_DECORATOR_PROVIDED_ATTRS) + r")\b[^\n]*\n\s*(?:async\s+)?def\s+(?P<name>\w+)"
)
_NOISY_LITERALS = frozenset(
    {
        "",
        "0",
        "1",
        "false",
        "true",
        "none",
        "null",
        # Common bool synonyms -- too short and ubiquitous to be meaningful contract
        # literals (e.g. env-var coercions like `in {"1", "true", "yes", "on"}`
        # appear in dozens of unrelated places and generate FIXME noise).
        "yes",
        "no",
        "on",
        "off",
    }
)
# A literal found in this many distinct files is ambient vocabulary (e.g. common
# bool synonyms, status words) rather than a contract identifier. Skip it.
_MAX_LITERAL_FILE_SPREAD = 4

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


def _removed_cache_decorated_symbols(edits: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(decorator, symbol) pairs whose cache decorator this edit removed.

    Flags only a decorator present above ``def NAME`` in *old* and absent above the
    same ``def NAME`` in *new* -- i.e. genuinely stripped, not merely relocated to a
    new helper (the helper keeps the decorator, so its own name is never flagged).
    """
    out: list[tuple[str, str]] = []
    for edit in edits:
        old = edit.get("old_string")
        new = edit.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            continue
        for match in _CACHE_DECORATED_DEF_RE.finditer(old):
            deco, name = match.group("deco"), match.group("name")
            still = re.search(
                r"@(?:\w+\.)*" + re.escape(deco) + r"\b[^\n]*\n\s*(?:async\s+)?def\s+" + re.escape(name) + r"\b",
                new,
            )
            if not still and (deco, name) not in out:
                out.append((deco, name))
    return out


def decorator_contract_impact(
    edits: list[dict[str, Any]],
    *,
    engine: _TextSearcher | None,
    touched_paths: list[str],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Sites in untouched files that call a decorator-provided method this edit removed.

    e.g. removing ``@lru_cache`` from ``get_resolver`` breaks ``get_resolver.cache_clear()``
    in another file -- a semantic dependency invisible to literal matching. Deterministic
    (decorator removal is textual; the method names are a fixed stdlib vocabulary) and
    low-noise (fires only when the decorator is removed AND its method is used elsewhere).
    """
    pairs = _removed_cache_decorated_symbols(edits)
    if not pairs or engine is None:
        return []
    touched = set(touched_paths)
    sites: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for deco, name in pairs:
        for attr in _DECORATOR_PROVIDED_ATTRS.get(deco, ()):
            access = f"{name}.{attr}"
            try:
                hits = engine.search_text(access, path=".", limit=20, ignore_case=False)
            except Exception:  # noqa: BLE001 -- evidence-only; never break the edit
                hits = []
            for hit in hits:
                path = getattr(hit, "file_path", None)
                line = getattr(hit, "line", None)
                text = getattr(hit, "text", "") or ""
                if not isinstance(path, str) or path in touched:
                    continue
                if access not in text:  # precise: the actual attribute access, not a name collision
                    continue
                key = (path, int(line) if isinstance(line, int) else -1)
                if key in seen:
                    continue
                seen.add(key)
                sites.append(
                    {
                        "path": path,
                        "line": line,
                        "old": f"@{deco} on {name}()",
                        "new": f"{access} no longer exists",
                        "snippet": text.strip()[:80],
                    }
                )
                if len(sites) >= limit:
                    return sites
    return sites


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
    max_matches_per_literal: int = 2,
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

    sites: list[dict[str, Any]] = []
    for literal in literals:
        astgrep_found = astgrep_by_literal.get(literal) if astgrep_by_literal is not None else None
        found = _combine_matches(astgrep_found, text_by_literal.get(literal) or [])
        if not found:
            continue
        # Rarity gate: a literal found in many files is ambient vocabulary (common
        # bool synonyms, generic status words), not a contract -- skip it.
        if len({match[0] for match in found}) > _MAX_LITERAL_FILE_SPREAD:
            continue
        # Production consumers before tests, then stable by location.
        found.sort(key=lambda match: (_is_test_path(match[0]), match[0], match[1]))
        for path, line, snippet in found[:max_matches_per_literal]:
            sites.append(
                {
                    "path": path,
                    "line": line,
                    "old": literal,
                    "new": replacements[literal],
                    "snippet": snippet[:80],
                }
            )
    if not sites:
        return None
    return {
        "reason": ("These sites still use the old form you just changed -- update each or say why not."),
        "sites": sites,
    }


__all__ = [
    "contract_literal_impact",
    "decorator_contract_impact",
    "literal_replacements",
    "removed_literals",
]
