# --- bash convergence guard: don't let the agent hunt history/web for the fix --- #
# git-history / web "how was this fixed upstream" hunting never advances a SWE task
# (the fix is not in the repo's past and external fetch is blocked) and dumps large
# output that bloats every later turn -- the django-13344 runaway: 37 bash calls,
# 50k chars, 0 edits, FAILED. Return a decision-ready answer in the SAME turn:
# code_search of the searched term + a one-line redirect to the test + source.
_ARCHAEOLOGY_RE = re.compile(r"\bgit\s+(?:log|show|blame)\b|\b(?:curl|wget)\b", re.IGNORECASE)
_ARCH_GREP_TERM_RE = re.compile(r"--grep[=\s]+['\"]?([^'\"|>&\n]+)", re.IGNORECASE)
_ARCH_NOISE_RE = re.compile(r"^[#0-9a-f]{3,}$", re.IGNORECASE)
_ARCH_NOTE = (
    "[bash] Hunting git history or the web for how this was fixed upstream is "
    "unavailable and is not how this task is solved: the fix is not in this repo's "
    "history and external fetch is blocked. Decide from the failing test and the "
    "current source -- code_search the symbols you need, then edit."
)


def _archaeology_fallback(command: str) -> str | None:
    """Return a decision-ready answer for a history/web hunt, or None to run normally."""
    if not command or not _ARCHAEOLOGY_RE.search(command):
        return None
    m = _ARCH_GREP_TERM_RE.search(command)
    words = [w for w in re.split(r"\s+", m.group(1).strip()) if w and not _ARCH_NOISE_RE.match(w)] if m else []
    if words:
        query = " ".join(words[:6])
        try:
            res = tool_code_search(query)
            return _ARCH_NOTE + "\n\nRelevant code for `" + query + "`:\n" + json.dumps(res, separators=(",", ":"))
        except Exception:
            return _ARCH_NOTE
    return _ARCH_NOTE
