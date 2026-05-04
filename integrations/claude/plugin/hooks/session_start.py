#!/usr/bin/env python3
"""SessionStart hook — capture session metadata into the RunLedger.

Fires once when a Claude Code session starts (or resumes / clears / compacts).
Records session_id, model, cwd, source, and timestamp as a ``note`` event in
the active RunLedger.  Also writes ``session_id`` into session_state.json so
other hooks and the Stop hook can correlate events to the session.

Fail-open: any error exits silently (code 0) — never blocks the agent.

Payload received on stdin:
  {
    "session_id": "abc123",
    "transcript_path": "/path/to/session.jsonl",
    "cwd": "/path/to/workspace",
    "hook_event_name": "SessionStart",
    "source": "startup" | "resume" | "clear" | "compact",
    "model": "claude-sonnet-4-6"
  }
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# State helpers
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


def _write_session_state(updates: dict) -> None:  # type: ignore[type-arg]
    p = _session_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    state = _read_session_state()
    state.update(updates)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


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


def _append_session_start_event(
    run_id: str,
    session_id: str,
    source: str,
    model: str,
    cwd: str,
    transcript_path: str,
) -> None:
    runs_dir = _atelier_root() / "runs"
    run_file = runs_dir / f"{run_id}.json"
    if not run_file.exists():
        return

    try:
        data = json.loads(run_file.read_text("utf-8"))
    except Exception:
        return

    events: list[dict] = data.setdefault("events", [])  # type: ignore[assignment]
    events.append(
        {
            "kind": "note",
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "summary": f"session {source} — {model or 'unknown model'}",
            "payload": {
                "session_id": session_id,
                "source": source,
                "model": model,
                "cwd": cwd,
                "transcript_path": transcript_path,
                "event": "SessionStart",
            },
        }
    )
    data["events"] = events

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
        return 0

    session_id: str = payload.get("session_id", "") or ""
    source: str = payload.get("source", "startup") or "startup"
    model: str = payload.get("model", "") or ""
    cwd: str = payload.get("cwd", "") or ""
    transcript_path: str = payload.get("transcript_path", "") or ""

    try:
        # Write session_id to session_state so other hooks/Stop can use it
        if session_id:
            _write_session_state({"session_id": session_id})

        run_id = _active_run_id()
        if not run_id:
            return 0

        _append_session_start_event(
            run_id, session_id, source, model, cwd, transcript_path
        )
    except Exception:
        pass  # fail-open

    return 0


if __name__ == "__main__":
    sys.exit(main())
