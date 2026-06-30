# Escalating convergence intervention (firm, never a hard block). A spiral is the
# agent gathering more data hoping for clarity; a polite line is ignored because
# gathering still works. So escalate by removing the fuel and forcing the decision
# -- edit/test always execute, and one edit resets everything. Because the runtime
# sees every search/read in the session, it can hand back a CONSOLIDATED list of
# what the agent already examined.
_NONEDIT_STREAK = [0]
_SEEN_PATHS: list[str] = []
_SEEN_QUERIES: list[str] = []
_INVESTIGATIVE_TOOLS = frozenset({"bash", "read", "code_search", "grep", "search", "explore"})
_NUDGE_AT = 10
_CONSOLIDATE_AT = 16
_DEGRADE_AT = 23


def _note_gather(tool_name: str, args: object) -> None:
    if not isinstance(args, dict):
        return
    if tool_name == "read":
        vals = args.get("files") or []
        if not vals:
            v = args.get("path") or args.get("symbol") or args.get("file_path")
            vals = v if isinstance(v, list) else ([v] if v else [])
        for v in vals:
            s = str(v)
            if s and s not in _SEEN_PATHS:
                _SEEN_PATHS.append(s)
    else:
        q = args.get("query") or args.get("content_regex") or args.get("pattern")
        if q and str(q) not in _SEEN_QUERIES:
            _SEEN_QUERIES.append(str(q))


def _convergence_intervention(tool_name: str, args: object, response_text: str) -> str:
    """Escalate from nudge -> consolidate -> degrade as a gather-without-edit streak grows."""
    if tool_name in {"edit", "codemod"}:  # a commit resets the streak
        _NONEDIT_STREAK[0] = 0
        return response_text
    if tool_name not in _INVESTIGATIVE_TOOLS:
        return response_text
    _note_gather(tool_name, args)
    _NONEDIT_STREAK[0] += 1
    n = _NONEDIT_STREAK[0]
    if n < _NUDGE_AT:
        return response_text
    seen = ", ".join(_SEEN_PATHS[:6]) or "the files from your searches"
    decision = f"{n} search/read calls with 0 edits -- you are spiraling. You have already " f"examined: {seen}."
    if n >= _DEGRADE_AT:  # firm: suppress the bulky gather output, keep a head + the decision
        return (
            f"STOP GATHERING. {decision}\n\n"
            "(further read-only output suppressed this turn; your next action must be an "
            f"edit or a test run)\n\n{response_text[:400]}"
        )
    if n >= _CONSOLIDATE_AT:  # consolidate: surface the decision list up front
        return f"{decision}\n\n{response_text}"
    return f"{response_text}\n\n{decision}"  # nudge
