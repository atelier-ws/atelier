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

Telemetry contract (D-11): callers (``PhaseRunner``) wrap each minified
read in a :class:`MinificationDelta` and append the ``to_dict()``
payload to :attr:`PhaseCacheStats.minify_deltas` so the benchmark
(13-04) can attribute savings separately from cache reuse.
"""

from __future__ import annotations

import re

from atelier.core.capabilities.prompt_compilation.tokens import (
    estimate_tokens as _count_tokens,
)

_BLANK_RUN = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_WHITESPACE_SIGNIFICANT: frozenset[str] = frozenset({"python", "py", "yaml", "yml", "makefile", "haml"})


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
    out = _TRAILING_WS.sub("", text)
    out = _BLANK_RUN.sub("\n\n", out)
    # The whitespace-significant set currently gates only future
    # aggressive transforms; we honour it by NEVER adding intra-line
    # collapses here. Reference the set so it remains part of the
    # public contract and lints clean.
    _ = lang.lower() in _WHITESPACE_SIGNIFICANT
    return out, _count_tokens(original), _count_tokens(out)


__all__ = ["minify_source"]
