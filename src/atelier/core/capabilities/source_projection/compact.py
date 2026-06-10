"""Read-side compact source projection helpers.

This module only builds transformed read projections. It does not participate in
writer paths; future projection-aware edit support should build on these models
without changing the current exact-write invariants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from atelier.core.capabilities.prompt_compilation.tokens import (
    estimate_tokens as _count_tokens,
)
from atelier.core.capabilities.source_projection.mapping import build_compact_mapping
from atelier.core.capabilities.source_projection.models import ProjectionMapping

_BLANK_RUN = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_WHITESPACE_SIGNIFICANT: frozenset[str] = frozenset({"python", "py", "yaml", "yml", "makefile", "haml"})
_AGGRESSIVE_INLINE_SAFE: frozenset[str] = frozenset({"c", "cpp", "c++", "cs", "go", "java", "json", "kotlin"})


@dataclass(frozen=True)
class CompactProjectionResult:
    content: str
    original_tokens: int
    projected_tokens: int
    mapping: ProjectionMapping | None = None

    @property
    def saved_tokens(self) -> int:
        return max(0, self.original_tokens - self.projected_tokens)

    @property
    def applied(self) -> bool:
        return self.projected_tokens < self.original_tokens


def build_compact_projection(
    text: str,
    lang: str,
    *,
    path: str = "",
    include_mapping: bool = False,
) -> CompactProjectionResult:
    """Return the read-side compact projection for ``text``."""
    original = text
    out = _conservative_compact(text)
    normalized = lang.lower()
    if normalized in _AGGRESSIVE_INLINE_SAFE:
        out = _collapse_inline_whitespace(out)
    mapping = None
    if include_mapping:
        mapping = build_compact_mapping(
            source_text=original,
            projected_text=out,
            path=path,
            lang=lang,
        )
    return CompactProjectionResult(
        content=out,
        original_tokens=_count_tokens(original),
        projected_tokens=_count_tokens(out),
        mapping=mapping,
    )


def _conservative_compact(text: str) -> str:
    out = _TRAILING_WS.sub("", text)
    return _BLANK_RUN.sub("\n\n", out)


def _collapse_inline_whitespace(text: str) -> str:
    out: list[str] = []
    quote: str = ""
    escaped = False
    pending_space = False
    at_line_start = True

    for char in text:
        if quote:
            out.append(char)
            if quote != "`" and escaped:
                escaped = False
                continue
            if quote != "`" and char == "\\":
                escaped = True
                continue
            if char == quote and (quote == "`" or not escaped):
                quote = ""
            continue

        if char == "\n":
            pending_space = False
            out.append(char)
            at_line_start = True
            continue

        if at_line_start and char in " \t":
            out.append(char)
            continue

        if char in " \t":
            pending_space = True
            at_line_start = False
            continue

        if pending_space:
            out.append(" ")
            pending_space = False

        if char in {"'", '"', "`"}:
            quote = char
            escaped = False
        out.append(char)
        at_line_start = False
    return "".join(out)


__all__ = ["CompactProjectionResult", "build_compact_projection"]
