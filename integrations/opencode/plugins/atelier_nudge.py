#!/usr/bin/env python3
"""OpenCode chat.message adapter for Atelier prompt-time nudges."""

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
        from atelier.core.capabilities.plugin_runtime import build_opencode_user_prompt_output

        payload = json.loads(sys.stdin.read() or "{}")
        output = build_opencode_user_prompt_output(_atelier_root(), payload)
        if not output.get("no_output"):
            sys.stdout.write(json.dumps(output) + "\n")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
