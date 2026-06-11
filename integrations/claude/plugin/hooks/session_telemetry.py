#!/usr/bin/env python3
"""Lifecycle hook that maintains Atelier's session-local telemetry state."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _atelier_root() -> Path:
    return Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        from atelier.core.capabilities.plugin_runtime import update_session_stats

        # Pure state upkeep — this hook emits nothing. Model-facing nudges are
        # limited to the user_prompt batching nudge and the failure-hook rescue
        # nudge; everything heuristic was removed as unproven noise.
        update_session_stats(_atelier_root(), payload)
    except (json.JSONDecodeError, TypeError, ImportError, AttributeError, OSError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
