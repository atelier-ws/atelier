"""Read-context source minifier (LINEAR-03, D-09, D-10, D-11).

Pure-function whitespace transforms applied to file bodies BEFORE they
are injected into the reader-profile conversation. Writer-profile reads
NEVER call this module (D-09); writer paths must read exact bytes so the
implementer never sees a mutated source.

Safety guarantees (T-13-02):
* No ``exec`` / ``eval`` / ``compile`` / dynamic import.
* Regex string-only transforms.
* For whitespace-significant languages (Python, YAML, Makefile, Haml)
  leading whitespace on every non-blank line is byte-preserved (D-10).
* The conservative transform (strip trailing tabs/spaces + collapse
  ≥3-newline runs to exactly two) is applied to every language,
  including unknown ones (safest universal path).

Telemetry contract (D-11): callers wrap each minified read in a
:class:`MinificationDelta` and surface the ``to_dict()`` payload so
savings can be attributed separately from any cache reuse.
"""

from __future__ import annotations

import re

from atelier.core.capabilities.prompt_compilation.tokens import (
    estimate_tokens as _count_tokens,
)

_BLANK_RUN = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_WHITESPACE_SIGNIFICANT: frozenset[str] = frozenset({"python", "py", "yaml", "yml", "makefile", "haml"})
_AGGRESSIVE_INLINE_SAFE: frozenset[str] = frozenset({"c", "cpp", "c++", "cs", "go", "java", "json", "kotlin"})


def minify_source(text: str, lang: str) -> tuple[str, int, int]:
    """Return ``(minified, original_tokens, minified_tokens)``.

    Args:
        text: Original file body.
        lang: Source language identifier (case-insensitive). Whitespace-
            significant languages are routed through the safest path
            (D-10) — only trailing tab/space stripping and blank-run
            collapsing are applied. Other languages currently take the
            same conservative path; aggressive intra-line collapses are
            deferred to keep the universal safety guarantee.

    The transform is referentially transparent: same inputs always
    produce the same outputs; no I/O, no logging, no global state.
    """
    original = text
    out = _conservative_minify(text)
    normalized = lang.lower()
    if normalized in _AGGRESSIVE_INLINE_SAFE:
        out = _collapse_inline_whitespace(out)
    return out, _count_tokens(original), _count_tokens(out)


def _conservative_minify(text: str) -> str:
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


__all__ = ["minify_source"]
