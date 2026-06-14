#!/usr/bin/env python3
"""SessionStart hook — background indexer for all-sessions Recall.

When ``recallAutoIndex`` is enabled in plugin_settings.json, detaches a child
that incrementally indexes past session transcripts into the archival vector
store so Recall can search across ALL sessions. On by default (the local
embedder is free); set ``recallAutoIndex`` to false to disable. The
``atelier recall index`` CLI is available regardless.

Fail-open and non-blocking: returns 0 immediately, never waits on the child.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


def _session_state_path() -> Path:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    root = Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")
    return root / "workspaces" / h / "session_state.json"


def _read_session_state() -> dict[str, Any]:
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


def _auto_index_enabled(root: Path) -> bool:
    try:
        from atelier.core.capabilities.plugin_runtime import plugin_settings_path

        data = json.loads(plugin_settings_path(root).read_text("utf-8"))
    except (OSError, json.JSONDecodeError, ImportError):
        return False
    # On by default: only an explicit false disables the background indexer.
    if not isinstance(data, dict):
        return True
    return bool(data.get("recallAutoIndex", True))


def _spawn(root: Path) -> None:
    override = os.environ.get("ATELIER_RECALL_CHILD_CMD")
    cmd = shlex.split(override) if override else [sys.executable, "-m", "atelier.core.capabilities.session_recall"]
    cmd += ["--root", str(root)]
    env = dict(os.environ)
    env["ATELIER_IN_REVIEW"] = "1"  # reuse the reviewer guard so this never recurses into review hooks
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
    if os.environ.get("ATELIER_IN_REVIEW"):
        return 0
    try:
        sys.stdin.read()  # drain payload; SessionStart carries no fields we need
        root = _atelier_root()
        if _auto_index_enabled(root):
            _spawn(root)
    except Exception:  # noqa: BLE001 - hook must never block session start
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
