# Edit-test-fail churn: the costly spiral is edit->test->FAIL repeated without ever
# going green. Tracked separately from the gather streak (which resets on every
# edit, so it is blind to this). Escalation rides the FIXME must-act channel -- the
# plain text channel is ignored under load (58 ignored nudges on one
# spiral) -- and pushes the agent BACK TO PLANNING instead of repeating the loop it
# is stuck in. Only sustained failure (no pass) escalates, so a converging task
# that hits a green resets and never sees it.
_FAILED_TEST_STREAK = [0]
_EDITS_SINCE_GREEN = [0]
_TEST_CHURN_TIERS = (3, 5, 8)
_TEST_RUN_RE = re.compile(
    r"\b(?:pytest|py\.test|runtests|nosetests|tox|unittest)\b|manage\.py\s+test"
    r"|python[0-9.]*\s+\S*repro\S*\.py|python[0-9.]*\s+-m\s+(?:pytest|unittest)",
    re.IGNORECASE,
)
_TEST_FAIL_RE = re.compile(
    r"\b\d+\s+failed\b|\bFAILED\b|\bERRORS?\b|Traceback \(most recent call last\)"
    r"|\bAssertionError\b|^E\s|\b\d+\s+errors?\b",
    re.IGNORECASE | re.MULTILINE,
)
_TEST_PASS_RE = re.compile(
    r"\b\d+\s+passed\b|^OK\b|\bRan\s+\d+\s+tests?\b",
    re.IGNORECASE | re.MULTILINE,
)


def _classify_test_outcome(command: str, text: str) -> str | None:
    """PASS / FAIL for a bash command's result text, or None if it is not a test run
    (or the outcome is ambiguous, which must not count toward the streak)."""
    if not _TEST_RUN_RE.search(command or ""):
        return None
    if _TEST_FAIL_RE.search(text or ""):
        return "FAIL"
    if _TEST_PASS_RE.search(text or ""):
        return "PASS"
    return None


def _test_churn_intervention(tool_name: str, args: object, response_text: str) -> str:
    """Escalate via FIXME (back-to-planning) when edit->test->FAIL repeats with no pass."""
    if tool_name in {"edit", "codemod"}:
        _EDITS_SINCE_GREEN[0] += 1
        return response_text
    if tool_name != "bash":
        return response_text
    command = str(args.get("command") or "") if isinstance(args, dict) else ""
    outcome = _classify_test_outcome(command, response_text)
    if outcome is None:
        return response_text
    if outcome == "PASS":
        _FAILED_TEST_STREAK[0] = 0
        _EDITS_SINCE_GREEN[0] = 0
        return response_text
    _FAILED_TEST_STREAK[0] += 1
    n = _FAILED_TEST_STREAK[0]
    e = _EDITS_SINCE_GREEN[0]
    if n < _TEST_CHURN_TIERS[0]:
        return response_text
    if n >= _TEST_CHURN_TIERS[2]:
        reason = (
            f"{n} test runs have failed across {e} edits without a single pass -- you have spent the "
            "turn budget without converging. Make your single best-justified fix NOW and STOP the "
            "edit+test loop; the current diff is your answer. More edits will not fix a wrong diagnosis."
        )
    elif n >= _TEST_CHURN_TIERS[1]:
        reason = (
            f"{n} failing test runs, {e} edits, still red -- STOP editing and step back to PLANNING. "
            "Re-read the requirement from scratch, list 2-3 candidate root causes, pick ONE and justify "
            "it before the next edit. Repeating edits will not help if the diagnosis is wrong."
        )
    else:
        reason = (
            f"{n} test runs failed across {e} edits with no pass. Before editing again: re-read the "
            "EXACT failing assertion and the function under test, then state the root cause in one line. "
            "You may be fixing a symptom, not the cause."
        )
    return f"FIXME (convergence): {reason}\n\n{response_text}"
