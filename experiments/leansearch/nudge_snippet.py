# Convergence nudge: the top remaining cost sink is tasks that SPIRAL -- gather
# (search/read/bash) without ever committing an edit, running to the 150-turn
# ceiling and failing (django-13344, django-15128). Track investigative calls
# since the last edit (per process = per agent run); after a run of them, append
# ONE soft line nudging the agent to decide and edit. No hard block, tool-agnostic.
_NONEDIT_STREAK = [0]
_NUDGE_EVERY = 12
_INVESTIGATIVE_TOOLS = frozenset({"bash", "read", "code_search", "grep", "search", "explore"})


def _convergence_nudge(tool_name: str) -> str:
    """Soft anti-spiral: one nudge line after a long gather-without-edit streak."""
    if tool_name in {"edit", "codemod"}:  # a commit resets the streak
        _NONEDIT_STREAK[0] = 0
        return ""
    if tool_name not in _INVESTIGATIVE_TOOLS:
        return ""
    _NONEDIT_STREAK[0] += 1
    n = _NONEDIT_STREAK[0]
    if n and n % _NUDGE_EVERY == 0:
        return (
            f"\n\n{n} investigative calls (search/read/bash) without an edit. "
            "You very likely have enough now: make the change in one bulk edit, then run "
            "the covering test once. Searching/reading more rarely converges -- decide from "
            "the failing test and the code you have already seen."
        )
    return ""
