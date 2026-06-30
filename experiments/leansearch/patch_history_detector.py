"""Add a GENERIC version-history archaeology spiral detector to the worktree
mcp_server.py, alongside the existing gather + test-churn interventions.

Not benchmark-specific: an unbroken streak of commit-history reads (git
log/show/blame/bisect/rev-list/reflog) with no intervening edit is a stuck
pattern in ANY git repo -- the agent is hunting the answer in history instead of
reasoning from the code. Resets on edit; rides the FIXME must-act channel.
"""

import py_compile
from pathlib import Path

P = Path("/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py")
src = P.read_text()

if "_history_archaeology_intervention" in src:
    raise SystemExit("already patched")

HOOK_ANCHOR = "                    response_text = _test_churn_intervention(name, _spill_args, response_text)"
HOOK_NEW = (
    HOOK_ANCHOR + "\n                    response_text = _history_archaeology_intervention"
    "(name, _spill_args, response_text)"
)

FUNC_ANCHOR = r'''            "You may be fixing a symptom, not the cause."
        )
    return f"FIXME (convergence): {reason}\n\n{response_text}"'''

NEW_FUNC = r'''# Version-history archaeology spiral: repeatedly reading commit history
# (git log/show/blame/bisect/rev-list/reflog) without an intervening edit is a
# generic stuck-pattern -- the agent hunts the answer in history instead of
# reasoning from the code in front of it. Resets on edit (real progress), like the
# gather streak; rides the FIXME must-act channel since the plain text channel is
# ignored under load. git diff/status/stash (navigation) are intentionally NOT counted.
_HISTORY_STREAK = [0]
_HISTORY_TIERS = (6, 12)
_HISTORY_CMD_RE = re.compile(
    r"\bgit\b(?:\s+-\S+|\s+-C\s+\S+)*\s+(?:log|show|blame|bisect|rev-list|reflog|whatchanged)\b",
    re.IGNORECASE,
)


def _history_archaeology_intervention(tool_name: str, args: object, response_text: str) -> str:
    """Escalate via FIXME when version-history reads pile up with no intervening edit."""
    if tool_name in {"edit", "codemod"}:  # an edit is real progress -> reset
        _HISTORY_STREAK[0] = 0
        return response_text
    if tool_name != "bash":
        return response_text
    command = str(args.get("command") or "") if isinstance(args, dict) else ""
    if not _HISTORY_CMD_RE.search(command):
        return response_text
    _HISTORY_STREAK[0] += 1
    n = _HISTORY_STREAK[0]
    if n < _HISTORY_TIERS[0]:
        return response_text
    if n >= _HISTORY_TIERS[1]:
        reason = (
            f"{n} version-history reads (git log/show/blame) with no edit in between -- mining "
            "history is not converging you on a fix. Stop reading history: re-read the symbol under "
            "change and whatever defines its expected behavior (test, caller, or spec), state the "
            "root cause in one line, then EDIT. Reading more history will not write the change for you."
        )
    else:
        reason = (
            f"{n} commit/blame reads with no edit in between -- you may be hunting the answer in "
            "history instead of reasoning from the code. Re-read the symbol under change and its "
            "expected behavior, then edit rather than searching history again."
        )
    return f"FIXME (convergence): {reason}\n\n{response_text}"'''

if src.count(HOOK_ANCHOR) != 1:
    raise SystemExit(f"hook anchor count={src.count(HOOK_ANCHOR)} (expected 1)")
if src.count(FUNC_ANCHOR) != 1:
    raise SystemExit(f"func anchor count={src.count(FUNC_ANCHOR)} (expected 1)")

src = src.replace(HOOK_ANCHOR, HOOK_NEW, 1)
src = src.replace(FUNC_ANCHOR, FUNC_ANCHOR + "\n\n\n" + NEW_FUNC + "\n", 1)
P.write_text(src)
py_compile.compile(str(P), doraise=True)
print("patched OK: hook + _history_archaeology_intervention added; py_compile passed")
