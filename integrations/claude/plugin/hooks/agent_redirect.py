#!/usr/bin/env python3
"""PreToolUse hook — redirect built-in subagent spawns to Atelier agents.

When the model spawns the built-in ``Explore`` or ``Plan`` subagent, rewrite it
to the Atelier equivalent (which uses Atelier's indexed search/read tools via
``updatedInput``) and announce the swap through ``additionalContext`` so the
change is transparent, not silent. Everything else is left untouched. Fail-open.
"""

from __future__ import annotations

import json
import sys

# Built-in read-only explorer/planner types that Atelier improves on. We do NOT
# rewrite ``general-purpose`` (it can edit; rewriting would change behaviour).
_REWRITE = {
    "Explore": "atelier:explore",
    "Plan": "atelier:plan",
}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    requested = str(tool_input.get("subagent_type") or "")
    target = _REWRITE.get(requested)
    if not target:
        return 0

    updated = dict(tool_input)
    updated["subagent_type"] = target
    reason = (
        f"Spawning {target} instead of built-in {requested} — it uses Atelier's indexed search/read "
        f'tools (cheaper, fewer round-trips). Use subagent_type "{target}" directly next time.'
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": updated,
                    "additionalContext": reason,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
