#!/usr/bin/env python3
"""PreToolUse hook that nudges file and SQL shell work toward Atelier tools."""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        from atelier.core.capabilities.plugin_runtime import classify_bash, rewrite_agent

        tool_name = payload.get("tool_name", "") or ""
        tool_input = payload.get("tool_input", {}) or {}
        if tool_name == "Bash":
            result = classify_bash(str(tool_input.get("command", "") or ""))
            if result.get("no_output"):
                return 0
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "allow",
                            "additionalContext": result.get("additional_context", ""),
                        }
                    }
                )
            )
            return 0
        if tool_name == "Agent":
            result = rewrite_agent(
                tool_input.get("subagent_type"),
                is_free_plan=os.environ.get("ATELIER_FREE_PLAN") == "1",
            )
            if result.get("updated_input"):
                updated = dict(tool_input)
                updated.update(result["updated_input"])
                print(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "allow",
                                "updatedInput": updated,
                            }
                        }
                    )
                )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
