"""On-demand tool-usage orientation (N8).

Returns Atelier's tool-usage playbook on demand so the optimal-sequencing
guidance can live in ONE fetch instead of being duplicated verbatim in every
system prompt. Content is static and deterministic -- no I/O, no model calls --
so the same fetch is byte-stable across sessions and cheap to cache.

The canonical sequence Atelier optimizes for is:

    explore  ->  navigate  ->  edit  ->  verify

Callers may request a focused ``topic`` to retrieve a single section instead of
the whole playbook; an unknown topic falls back to the overview plus the list of
valid topics (never an error), so this capability always returns usable text.
"""

from __future__ import annotations

from typing import Any

# Ordered so the rendered playbook reads as the canonical lifecycle. Each value
# is a (title, body) pair; bodies are plain text so any host can surface them.
_SECTIONS: dict[str, tuple[str, str]] = {
    "explore": (
        "1. Explore (orient before touching anything)",
        (
            "Ground yourself before editing. Use `search` for ranked/relevant\n"
            "snippets and `grep` for regex/glob/type-filtered matches. Use\n"
            "`node` to read a definition by name and `read` (outline mode) to\n"
            "skim large files cheaply. Batch independent reads in one `read`\n"
            "call. Do NOT start editing until you can name the files and symbols\n"
            "that define the deliverable and its constraints."
        ),
    ),
    "navigate": (
        "2. Navigate (build the call graph in your head)",
        (
            "Once grounded, walk the code structure with the focused SCIP tools\n"
            "instead of more grep: `node` to read a single definition and\n"
            "`explore` for grouped context -- one `explore` call returns the\n"
            "definition plus its callers, callees, and usages folded in. Prefer\n"
            "these exact tools over text search once you know the symbol --\n"
            "results are indexed and exact, not textual guesses."
        ),
    ),
    "edit": (
        "3. Edit (smallest correct change)",
        (
            "Make the narrowest change that satisfies the task. Use `edit` with\n"
            "multiple descriptors in ONE call for multi-file changes rather than\n"
            "editing file-by-file. Use `codemod` for AST-shaped rewrites that\n"
            "text replace cannot express safely. Re-read against a fresh range\n"
            "or expanded outline before editing so old/new strings match. Delete\n"
            "dead code outright -- never leave deprecation shims or tombstones."
        ),
    ),
    "verify": (
        "4. Verify (prove it before reporting)",
        (
            "Close the loop with the narrowest authoritative check. Run the\n"
            "repo's lint, typecheck, and the smallest relevant test selection\n"
            "via `bash`. Preserve failure evidence: read the delta, change the\n"
            "input/scope/approach on failure -- do not blindly retry the same\n"
            "command. Report verbatim pass/fail tails, not a paraphrase."
        ),
    ),
    "selection": (
        "Tool selection cheat-sheet",
        (
            "- Ranked relevance / 'where is X handled?'  -> `search`\n"
            "- Regex / glob / type-filtered text match    -> `grep`\n"
            "- Find a definition by name                  -> `grep` / `search`\n"
            "- Read one definition's body                 -> `node`\n"
            "- Callers / callees / usages of a symbol     -> `explore` (folds the call graph + references into one call)\n"
            "- Grouped context for a change               -> `explore`\n"
            "- Read a file (outline first on large)       -> `read`\n"
            "- Apply edits (batch multi-file)             -> `edit`\n"
            "- AST-shaped structural rewrite              -> `codemod`\n"
            "- Run a command / tests                      -> `bash`\n"
            "- Recall durable cross-session knowledge     -> `memory`"
        ),
    ),
}

_OVERVIEW = (
    "Atelier tool-usage playbook. Canonical sequence:\n"
    "    explore -> navigate -> edit -> verify\n"
    "Each phase has dedicated tools; do them in order and prefer the focused\n"
    "SCIP tools (`node` for one definition, `explore` for the call graph and\n"
    "references) over repeated grep once you know the symbol."
)


def available_topics() -> list[str]:
    """Return the focused-topic keys accepted by :func:`orientation_playbook`."""
    return list(_SECTIONS.keys())


def orientation_playbook(topic: str | None = None) -> dict[str, Any]:
    """Return the tool-usage playbook, optionally focused on one ``topic``.

    With ``topic`` unset (or empty) the full ordered playbook is returned. With a
    known ``topic`` only that section is returned. An unknown ``topic`` is never
    an error: it returns the overview plus ``topics`` so the caller can retry,
    and sets ``unknown_topic`` to the requested value.
    """
    normalized = (topic or "").strip().lower()
    if not normalized:
        sections = [{"key": key, "title": title, "body": body} for key, (title, body) in _SECTIONS.items()]
        text = _OVERVIEW + "\n\n" + "\n\n".join(f"{title}\n{body}" for title, body in _SECTIONS.values())
        return {
            "topic": None,
            "sequence": ["explore", "navigate", "edit", "verify"],
            "overview": _OVERVIEW,
            "sections": sections,
            "topics": available_topics(),
            "text": text,
        }

    if normalized in _SECTIONS:
        title, body = _SECTIONS[normalized]
        return {
            "topic": normalized,
            "sections": [{"key": normalized, "title": title, "body": body}],
            "topics": available_topics(),
            "text": f"{title}\n{body}",
        }

    return {
        "topic": None,
        "unknown_topic": normalized,
        "overview": _OVERVIEW,
        "topics": available_topics(),
        "text": (f"Unknown topic {normalized!r}. Valid topics: {', '.join(available_topics())}.\n\n{_OVERVIEW}"),
    }


__all__ = ["available_topics", "orientation_playbook"]
