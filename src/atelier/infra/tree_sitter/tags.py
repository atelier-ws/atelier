"""Symbol tag extraction used by the PageRank repo map."""

from __future__ import annotations

import ast
import re
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from atelier.core.capabilities.semantic_file_memory.treesitter_ast import (
    definition_node_kinds,
    supported_tree_sitter_languages,
    transparent_node_kinds,
    tree_sitter_parser,
)
from atelier.infra.code_intel.languages import language_for_path

TagKind = Literal["definition", "reference"]
_LEGACY_REGEX_LANGUAGES = frozenset({"javascript", "typescript", "go", "rust"})
_DATA_LANGUAGES = frozenset({"json", "toml", "yaml"})
_NO_REFERENCE_LANGUAGES = _DATA_LANGUAGES | frozenset({"bash", "sql"})
_IDENTIFIER_KINDS = frozenset(
    {
        "bare_key",
        "constant",
        "dotted_key",
        "field_identifier",
        "identifier",
        "name",
        "namespace_identifier",
        "package_identifier",
        "property_identifier",
        "simple_identifier",
        "string_content",
        "type_identifier",
        "variable_name",
        "word",
    }
)


@dataclass(frozen=True)
class Tag:
    name: str
    kind: TagKind
    file: str
    line: int
    byte_range: tuple[int, int]


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    total = 0
    for line in text.splitlines(keepends=True):
        total += len(line.encode("utf-8"))
        offsets.append(total)
    return offsets


def _line_for_byte(offsets: list[int], byte_offset: int) -> int:
    return max(1, bisect_right(offsets, byte_offset))


def _node_attr(node: Any, name: str) -> Any:
    val = getattr(node, name)
    return val() if callable(val) else val


def _child_count(node: Any) -> int:
    return int(_node_attr(node, "child_count"))


def _children(node: Any) -> list[Any]:
    return [node.child(index) for index in range(_child_count(node))]


def _kind(node: Any) -> str:
    return str(_node_attr(node, "kind") or _node_attr(node, "type") or "")


def _byte_range(node: Any) -> tuple[int, int]:
    return int(_node_attr(node, "start_byte")), int(_node_attr(node, "end_byte"))


def _node_text(source: bytes, node: Any) -> str:
    start, end = _byte_range(node)
    return source[start:end].decode("utf-8", errors="replace").strip()


def _child_by_field_name(node: Any, field_name: str) -> Any | None:
    child_by_field_name = getattr(node, "child_by_field_name", None)
    if child_by_field_name is None:
        return None
    child = child_by_field_name(field_name)
    return child if child is not None else None


def _walk(node: Any) -> list[Any]:
    nodes = [node]
    for child in _children(node):
        nodes.extend(_walk(child))
    return nodes


def _first_descendant(node: Any, kinds: frozenset[str]) -> Any | None:
    for candidate in _walk(node):
        if _kind(candidate) in kinds:
            return candidate
    return None


def _definition_name_node(node: Any, language: str) -> Any | None:
    kind = _kind(node)
    if language == "bash":
        if kind == "function_definition":
            return next((child for child in _children(node) if _kind(child) == "word"), None)
        return _first_descendant(node, frozenset({"variable_name"}))
    if language == "json" and kind == "pair":
        return _first_descendant(_children(node)[0], frozenset({"string_content"})) if _children(node) else None
    if language == "toml" and kind in {"pair", "table", "table_array_element"}:
        return _first_descendant(node, frozenset({"bare_key", "dotted_key"}))
    if language == "yaml" and kind == "block_mapping_pair":
        return _child_by_field_name(node, "key") or (_children(node)[0] if _children(node) else None)
    if language == "sql":
        return _first_descendant(node, frozenset({"identifier"}))

    for field_name in ("name", "declarator"):
        field_node = _child_by_field_name(node, field_name)
        if field_node is not None:
            identifier = _first_descendant(field_node, _IDENTIFIER_KINDS)
            return identifier or field_node
    return _first_descendant(node, _IDENTIFIER_KINDS)


def _definition_candidates(root: Any, language: str, definition_kinds: frozenset[str]) -> list[Any]:
    if language in {"json", "yaml"}:
        unwrap = transparent_node_kinds(language)
        candidates: list[Any] = []

        def visit(node: Any) -> None:
            for child in _children(node):
                kind = _kind(child)
                if kind in unwrap:
                    visit(child)
                elif kind in definition_kinds:
                    candidates.append(child)

        visit(root)
        return candidates
    return [node for node in _walk(root) if _kind(node) in definition_kinds]


def _treesitter_tags(path: Path, text: str, language: str) -> list[Tag] | None:
    parser = tree_sitter_parser(language)
    if parser is None:
        return None
    try:
        tree = parser.parse(text)
    except Exception:
        return None

    source = text.encode("utf-8")
    offsets = _line_offsets(text)
    root = _node_attr(tree, "root_node")
    definition_kinds = definition_node_kinds(language)
    tags: list[Tag] = []
    seen: set[tuple[str, TagKind, int, int]] = set()

    for node in _definition_candidates(root, language, definition_kinds):
        name_node = _definition_name_node(node, language)
        if name_node is None:
            continue
        start, end = _byte_range(name_node)
        name = _node_text(source, name_node)
        if not name:
            continue
        kind: TagKind = "definition"
        key = (name, kind, start, end)
        if key in seen:
            continue
        seen.add(key)
        tags.append(Tag(name, kind, str(path), _line_for_byte(offsets, start), (start, end)))

    if language not in _NO_REFERENCE_LANGUAGES:
        for node in _walk(root):
            if _kind(node) not in _IDENTIFIER_KINDS:
                continue
            start, end = _byte_range(node)
            name = _node_text(source, node)
            if not name:
                continue
            kind = "reference"
            key = (name, kind, start, end)
            if key in seen:
                continue
            seen.add(key)
            tags.append(Tag(name, kind, str(path), _line_for_byte(offsets, start), (start, end)))

    return tags


def _python_tags(path: Path, text: str) -> list[Tag]:
    offsets = _line_offsets(text)
    tags: list[Tag] = []
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            line = int(getattr(node, "lineno", 1))
            tags.append(Tag(node.name, "definition", str(path), line, (offsets[line - 1], offsets[line])))
        elif isinstance(node, ast.Name):
            line = int(getattr(node, "lineno", 1))
            tags.append(Tag(node.id, "reference", str(path), line, (offsets[line - 1], offsets[line])))
    return tags


def _regex_tags(path: Path, text: str, language: str) -> list[Tag]:
    patterns = {
        "javascript": r"(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)",
        "typescript": r"(?:function|class|interface|type|const|let|var)\s+([A-Za-z_$][\w$]*)",
        "go": r"(?:func|type|var|const)\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)",
        "rust": r"(?:fn|struct|enum|trait|impl)\s+([A-Za-z_][\w]*)",
    }
    def_re = re.compile(patterns.get(language, patterns["javascript"]))
    ident_re = re.compile(r"[A-Za-z_][$\w]*")
    tags: list[Tag] = []
    byte_offset = 0
    for line_no, line in enumerate(text.splitlines(keepends=True), start=1):
        for match in def_re.finditer(line):
            tags.append(
                Tag(
                    match.group(1),
                    "definition",
                    str(path),
                    line_no,
                    (byte_offset + match.start(1), byte_offset + match.end(1)),
                )
            )
        for match in ident_re.finditer(line):
            tags.append(
                Tag(
                    match.group(0),
                    "reference",
                    str(path),
                    line_no,
                    (byte_offset + match.start(0), byte_offset + match.end(0)),
                )
            )
        byte_offset += len(line.encode("utf-8"))
    return tags


def detect_language(path: Path) -> str | None:
    # Delegate to the canonical registry (DLS-LANG-04). Preserves the
    # str | None contract: extract_tags_from_text short-circuits to [] on None.
    lang = language_for_path(path)
    return lang.name if lang is not None else None


def extract_tags_from_text(text: str, file_path: str | Path, language: str | None = None) -> list[Tag]:
    """Extract definition/reference tags from source text without reading from disk."""

    path = Path(file_path)
    resolved_language = language or detect_language(path)
    if resolved_language is None:
        return []
    if resolved_language == "python":
        try:
            return _python_tags(path, text)
        except SyntaxError:
            return []
    if resolved_language in supported_tree_sitter_languages():
        tags = _treesitter_tags(path, text, resolved_language)
        if tags is not None:
            return tags
        if resolved_language not in _LEGACY_REGEX_LANGUAGES:
            return []
    return _regex_tags(path, text, resolved_language)


def extract_tags(file_path: str | Path, language: str | None = None) -> list[Tag]:
    """Extract definition/reference tags from a supported source file."""

    path = Path(file_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return extract_tags_from_text(text, path, language=language)


__all__ = ["Tag", "detect_language", "extract_tags", "extract_tags_from_text"]
