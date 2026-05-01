#!/usr/bin/env python3
"""PostToolUse hook — capture Bash command + output into the active RunLedger.

Fires after every Bash tool call. Records the command, stdout, stderr, and
return code as a ``command_result`` event in ``runs/<run_id>.json``.

Stdout/stderr are truncated to 4 KB each to cap ledger file size.
Fail-open: any error exits silently (code 0) — never blocks the agent.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

_MAX_OUTPUT_BYTES = 4096  # 4 KB per stream


# ---------------------------------------------------------------------------
# State helpers (mirrors post_tool_use.py)
# ---------------------------------------------------------------------------


def _session_state_path() -> Path:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    return Path(workspace) / ".atelier" / "session_state.json"


def _read_session_state() -> dict:  # type: ignore[type-arg]
    p = _session_state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))  # type: ignore[no-any-return]
    except Exception:
        return {}


def _atelier_root() -> Path:
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    if root:
        return Path(root)
    state = _read_session_state()
    if state.get("atelier_root"):
        return Path(state["atelier_root"])
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    return Path(workspace) / ".atelier"


def _active_run_id() -> str | None:
    return _read_session_state().get("active_run_id")


# ---------------------------------------------------------------------------
# RunLedger event writer
# ---------------------------------------------------------------------------


def _append_command_result_event(
    run_id: str,
    command: str,
    stdout: str,
    stderr: str,
    return_code: int | None,
) -> None:
    """Append a command_result event to runs/<run_id>.json atomically."""
    runs_dir = _atelier_root() / "runs"
    run_file = runs_dir / f"{run_id}.json"
    if not run_file.exists():
        return

    try:
        data = json.loads(run_file.read_text("utf-8"))
    except Exception:
        return

    events: list[dict] = data.setdefault("events", [])  # type: ignore[assignment]

    # Build a short summary line
    short_cmd = command.strip()[:80] + ("…" if len(command.strip()) > 80 else "")
    ok = return_code == 0 if return_code is not None else True
    summary = f"{'✓' if ok else '✗'} {short_cmd}"

    events.append(
        {
            "kind": "command_result",
            "at": datetime.datetime.now(datetime.UTC).isoformat(),
            "summary": summary,
            "payload": {
                "command": command,
                "stdout": stdout[:_MAX_OUTPUT_BYTES] if stdout else "",
                "stderr": stderr[:_MAX_OUTPUT_BYTES] if stderr else "",
                "return_code": return_code,
                "truncated": len(stdout or "") > _MAX_OUTPUT_BYTES or len(stderr or "") > _MAX_OUTPUT_BYTES,
            },
        }
    )
    data["events"] = events

    # Atomic write via temp file + rename
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=run_file.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = tmp.name
        Path(tmp_path).replace(run_file)
    except Exception:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # fail-open

    tool_name: str = payload.get("tool_name", "") or ""
    if tool_name != "Bash":
        return 0

    tool_input: dict = payload.get("tool_input", {}) or {}  # type: ignore[assignment]
    tool_response: dict = payload.get("tool_response", {}) or {}  # type: ignore[assignment]

    command: str = tool_input.get("command", "") or ""
    if not command:
        return 0

    stdout: str = tool_response.get("stdout", "") or ""
    stderr: str = tool_response.get("stderr", "") or ""
    # Claude Code may return exit code in different fields
    return_code: int | None = (
        tool_response.get("returnCode")
        or tool_response.get("return_code")
        or tool_response.get("exitCode")
    )

    try:
        run_id = _active_run_id()
        if not run_id:
            return 0
        _append_command_result_event(run_id, command, stdout, stderr, return_code)
    except Exception:
        pass  # fail-open: never block the agent

    return 0


if __name__ == "__main__":
    sys.exit(main())
