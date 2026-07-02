#!/usr/bin/env python3
"""Codex PreToolUse grounding gate backed by Atelier runtime state.

Emits a Codex ``permissionDecision: deny`` only when an active benchmark gate
requires read/grep/search grounding before editing a risky path. Otherwise it
stays silent (the edit proceeds). Fail-open: any error exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _atelier_root() -> Path:
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    return Path(root) if root else Path.home() / ".atelier"


def main() -> int:
    try:
        from atelier.core.capabilities.plugin_runtime import build_codex_pre_tool_use_output

        payload = json.loads(sys.stdin.read() or "{}")
        output = build_codex_pre_tool_use_output(_atelier_root(), payload)
        hook_output = output.get("hookSpecificOutput")
        if isinstance(hook_output, dict):
            sys.stdout.write(json.dumps({"hookSpecificOutput": hook_output}) + "\n")
    except (ImportError, json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
