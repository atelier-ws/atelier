#!/usr/bin/env python3
"""PostToolUse hook — non-blocking trigger for the live/automated reviewer.

Fires after Edit/Write/MultiEdit, AFTER post_tool_use.py has recorded the
``file_edit`` event. Does only cheap work: load reviewer settings, count edits,
and (when enabled) detach a reviewer child that runs the actual review
out-of-band. Returns 0 immediately — never blocks the turn. Fail-open.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def _session_state_path() -> Path:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    root = Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")
    return root / "workspaces" / h / "session_state.json"


def _read_session_state() -> dict:  # type: ignore[type-arg]
    p = _session_state_path()
    try:
        return json.loads(p.read_text("utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _atelier_root() -> Path:
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    if root:
        return Path(root)
    state = _read_session_state()
    if state.get("atelier_root"):
        return Path(state["atelier_root"])
    return Path.home() / ".atelier"


def _spawn(session_id: str, mode: str, path: str, root: Path) -> None:
    """Detach a reviewer child. Never waits — returns control immediately."""
    override = os.environ.get("ATELIER_REVIEWER_CHILD_CMD")
    cmd = shlex.split(override) if override else [sys.executable, "-m", "atelier.core.capabilities.live_reviewer.child"]
    cmd += ["--session", session_id, "--mode", mode, "--path", path, "--root", str(root)]
    env = dict(os.environ)
    env["ATELIER_IN_REVIEW"] = "1"
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env=env,
    )


def main() -> int:
    # A reviewer's own activity must never trigger another reviewer.
    if os.environ.get("ATELIER_IN_REVIEW"):
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0

    tool_name = payload.get("tool_name", "") or ""
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        return 0
    tool_input = payload.get("tool_input", {}) or {}
    edited = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("filename") or ""
    if not edited:
        return 0

    try:
        from atelier.core.capabilities.live_reviewer.edit_counter import count_file_edits
        from atelier.core.capabilities.live_reviewer.settings import load_reviewer_settings

        root = _atelier_root()
        settings = load_reviewer_settings(root)
        if not settings.enabled:
            return 0
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return 0
        count = count_file_edits(root / "sessions" / session_id / "run.json")
        if settings.deep_edit_count_reviewer and count > 0 and count % settings.deep_edit_count_interval == 0:
            _spawn(session_id, "deep", edited, root)
        elif settings.live_reviewer:
            _spawn(session_id, "live", edited, root)
    except Exception:  # noqa: BLE001 - hook must never block the turn
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
