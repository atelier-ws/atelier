#!/usr/bin/env python3
"""PostToolUse nudge — coach the model to batch edits.

Runs on every PostToolUse and filters internally to the Atelier ``edit`` tool
(identified by an ``edits`` list in tool_input, so it is name-agnostic across
hosts). When the model makes several single-edit calls in a row, emit a one-line
systemMessage suggesting it batch multiple edits into one call. Fail-open: any
error exits 0 and prints nothing.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

SINGLE_STREAK_THRESHOLD = 3


def _atelier_root() -> Path:
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    return Path(root) if root else Path.home() / ".atelier"


def _workspace_key(path: str) -> str:
    import re
    from hashlib import sha256
    from pathlib import Path as _Path

    resolved = _Path(path).expanduser().resolve()
    home = _Path.home().resolve()
    try:
        parts = resolved.relative_to(home).parts
    except ValueError:
        parts = [p for p in resolved.parts if p and p != "/"]
    sanitized = [re.sub(r"[^a-zA-Z0-9.\-_]", "-", p) for p in parts if p]
    label = re.sub(r"-{2,}", "-", "-".join(sanitized)).strip("-")
    if len(label) > 120:
        label = label[:110].rstrip("-") + "--" + sha256(str(resolved).encode()).hexdigest()[:6]
    return label or sha256(str(resolved).encode()).hexdigest()[:12]


def _session_id() -> str:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = _workspace_key(workspace)
    state = _atelier_root() / "workspaces" / h / "session_state.json"
    try:
        data = json.loads(state.read_text("utf-8"))
        return str(data.get("session_id") or data.get("active_session_id") or "default")
    except (OSError, json.JSONDecodeError):
        return "default"


def _is_edit_tool(tool_name: str, tool_input: dict) -> bool:
    if isinstance(tool_input.get("edits"), list):
        return True
    name = tool_name.lower()
    return name == "edit" or name.endswith("__edit")


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict) or not _is_edit_tool(tool_name, tool_input):
        return 0

    edits = tool_input.get("edits")
    count = len(edits) if isinstance(edits, list) else 1

    state_path = _atelier_root() / "edit_batching_nudge" / f"{_session_id()}.json"
    streak = 0
    nudged = False
    with contextlib.suppress(OSError, json.JSONDecodeError, ValueError):
        prev = json.loads(state_path.read_text("utf-8"))
        streak = int(prev.get("streak", 0))
        nudged = bool(prev.get("nudged_streak", False))

    if count <= 1:
        streak += 1
    else:
        streak = 0
        nudged = False

    nudge_now = streak >= SINGLE_STREAK_THRESHOLD and not nudged
    if nudge_now:
        nudged = True

    with contextlib.suppress(OSError):
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"streak": streak, "nudged_streak": nudged}), encoding="utf-8")

    if nudge_now:
        msg = (
            f"{streak} single-edit calls in a row. The `edit` tool batches — put every change for this "
            "step in one call's `edits` array (multiple files too) to cut round-trips and cost."
        )
        # additionalContext is model-facing (it adjusts behaviour) rather than a
        # user-only systemMessage — the point is to change how the model edits.
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
