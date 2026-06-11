#!/usr/bin/env python3
"""Codex PostToolUse savings reporter backed by Atelier runtime state."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _atelier_root() -> Path:
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".atelier"


def main() -> int:
    try:
        from atelier.core.capabilities.plugin_runtime import (
            build_codex_post_tool_use_savings_output,
        )

        payload = json.loads(sys.stdin.read() or "{}")
        build_codex_post_tool_use_savings_output(_atelier_root(), payload)
        # PostToolUse records telemetry and savings state only. Prompt-time
        # guidance is emitted by UserPromptSubmit so tool completion stays quiet.
    except (ImportError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
