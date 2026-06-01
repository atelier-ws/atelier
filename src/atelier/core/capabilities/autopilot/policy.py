"""Behavior selection policy for autopilot choreography (M5)."""

from __future__ import annotations

import re

from .models import AutopilotConfig

_TRIGGER_BEHAVIOR: dict[str, str] = {
    "session_start": "session_warm",
    "user_prompt": "scoped_inject",
    "post_edit": "counterexamples",
}

# Prompt-gating: only inject scoped context when the prompt looks like a coding
# task. Skips meta/conversational prompts ("what is X?", "thanks", "yes") that
# would otherwise trigger irrelevant context injection (context spam).
_CODE_SIGNAL = re.compile(
    r"""(
        \b[\w./-]+\.(?:py|tsx?|jsx?|go|rs|java|rb|cc?|cpp|hpp?|cs|kt|php|swift|scala|sh|md|ya?ml|toml|json|sql)\b
      | \b[a-z][a-z0-9]*_[a-z0-9_]+\b      # snake_case identifier
      | \b[a-z]+[A-Z][a-zA-Z]*\b           # camelCase identifier
      | \w+\(                               # call syntax foo(
      | \b\w+/\w+                           # path-like a/b
      | (?i:\b(?:error|traceback|exception|failed|assertion|stacktrace)\b)
    )""",
    re.VERBOSE,
)
_CODING_VERBS: frozenset[str] = frozenset(
    {
        "fix",
        "implement",
        "refactor",
        "add",
        "debug",
        "test",
        "build",
        "run",
        "edit",
        "rename",
        "optimize",
        "write",
        "create",
        "update",
        "remove",
        "delete",
        "install",
        "configure",
        "integrate",
        "migrate",
        "wire",
        "patch",
        "revert",
        "merge",
        "benchmark",
    }
)


def should_inject_for_prompt(prompt: str) -> bool:
    """Return True when *prompt* looks like a coding task worth injecting for."""
    text = (prompt or "").strip()
    if not text:
        return False
    if _CODE_SIGNAL.search(text):
        return True
    low = text.lower()
    return any(re.search(rf"\b{verb}\b", low) for verb in _CODING_VERBS)


def select_behavior(trigger: str, config: AutopilotConfig) -> str | None:
    """Return the behavior to fire for *trigger*, or None if disabled/unknown."""
    behavior = _TRIGGER_BEHAVIOR.get(trigger)
    if behavior is None:
        return None
    if behavior == "session_warm" and not config.session_warm:
        return None
    if behavior == "scoped_inject" and not config.scoped_inject:
        return None
    if behavior == "counterexamples" and not config.counterexamples:
        return None
    return behavior
