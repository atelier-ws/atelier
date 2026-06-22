#!/usr/bin/env python3
"""agentStart hook for GitHub Copilot CLI.

Clears the workspace-scoped savings side log so each session starts fresh.
Payload: {sessionId, transcriptPath, timestamp, cwd}
"""

import json
import os
import sys
from pathlib import Path


def _atelier_root() -> Path:
    return Path(os.environ.get("ATELIER_ROOT", "") or Path.home() / ".atelier")


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


def _session_savings_path(workspace: str) -> Path:
    """Resolve the per-session savings path, mirroring the MCP writer.

    Must match stop.py's reader and mcp_server.py's writer:
    1. If a host session-id env var is set (GITHUB_COPILOT_SESSION_ID, plus
       CLAUDE_CODE_SESSION_ID for parity) -> sessions/<sid>/savings.jsonl.
    2. Else workspaces/<sha256(resolve(ATELIER_WORKSPACE_ROOT or cwd))[:12]>/
       session_savings.jsonl.
    """
    for env_var in ("GITHUB_COPILOT_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        sid = os.environ.get(env_var, "").strip()
        if sid:
            return _atelier_root() / "sessions" / sid / "savings.jsonl"
    workspace = str(Path(os.environ.get("ATELIER_WORKSPACE_ROOT") or workspace).resolve())
    h = _workspace_key(workspace)
    return _atelier_root() / "workspaces" / h / "session_savings.jsonl"


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    workspace = (
        payload.get("cwd")
        or os.environ.get("COPILOT_PROJECT_DIR")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )

    path = _session_savings_path(workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    except OSError:
        pass


if __name__ == "__main__":
    main()
