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
import hashlib
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _session_state_path() -> Path:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    root = Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")
    return root / "workspaces" / h / "session_state.json"


def _read_session_state() -> dict[str, Any]:
    p = _session_state_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_session_state(updates: dict[str, Any]) -> None:
    p = _session_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    state = _read_session_state()
    state.update(updates)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=p.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(state, tmp, indent=2)
            tmp_path = tmp.name
        Path(tmp_path).replace(p)
    except OSError:
        if tmp_path:
            with suppress(Exception):
                Path(tmp_path).unlink(missing_ok=True)


def _atelier_root() -> Path:
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    if root:
        return Path(root)
    state = _read_session_state()
    if state.get("atelier_root"):
        return Path(state["atelier_root"])
    return Path.home() / ".atelier"


def _active_session_id() -> str | None:
    state = _read_session_state()
    return state.get("session_id") or state.get("active_session_id")


def _claude_settings_path() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def _apply_session_bootstrap(payload: dict[str, Any]) -> bool:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        return False
    try:
        from atelier.core.capabilities.plugin_runtime import apply_session_start_files
    except (ImportError, AttributeError):
        return False
    with suppress(Exception):
        apply_session_start_files(
            _atelier_root(),
            plugin_root,
            config_dir=_claude_settings_path().parent,
            payload=payload,
            current_version=os.environ.get("ATELIER_VERSION", "0.0.0"),
        )
        return True
    return False


def _initialize_session_stats(payload: dict[str, Any]) -> None:
    try:
        from atelier.core.capabilities.plugin_runtime import update_session_stats

        update_session_stats(_atelier_root(), payload)
    except (ImportError, OSError, json.JSONDecodeError, TypeError):
        pass


# ---------------------------------------------------------------------------
# RunLedger event writer
# ---------------------------------------------------------------------------


def _append_session_start_event(
    session_id: str,
    source: str,
    model: str,
    cwd: str,
    transcript_path: str,
) -> None:
    run_file = _atelier_root() / "sessions" / session_id / "run.json"
    if not run_file.exists():
        return

    try:
        data = json.loads(run_file.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    events: list[dict[str, Any]] = data.setdefault("events", [])
    events.append(
        {
            "kind": "note",
            "at": datetime.datetime.now(datetime.UTC).isoformat(),
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
    except OSError:
        if tmp_path:
            with suppress(Exception):
                Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, TypeError):
        return 0

    session_id_raw: str = payload.get("session_id", "") or ""
    source: str = payload.get("source", "startup") or "startup"
    model: str = payload.get("model", "") or ""
    cwd: str = payload.get("cwd", "") or ""
    transcript_path: str = payload.get("transcript_path", "") or ""

    try:
        # Write session_id + transcript_path to session_state so other hooks
        # and the MCP server can read a one-shot session-id/model bridge.
        if session_id_raw:
            state_update: dict[str, Any] = {
                "session_id": session_id_raw,
                "atelier_root": str(_atelier_root()),
            }
            if model:
                state_update["model"] = model
            if transcript_path:
                state_update["transcript_path"] = transcript_path
            _write_session_state(state_update)

        # On /clear, drop a marker so the statusline snapshots the current
        # cumulative live cost as a baseline and shows only post-clear spend.
        # Claude's cost.total_cost_usd is process-cumulative and does NOT reset
        # on /clear; the hook can't see it, but the statusline can. We do this
        # for clear only — /compact continues the same task, so its cost stands.
        if source == "clear" and session_id_raw:
            with suppress(Exception):
                reset_dir = _atelier_root() / "statusline_cost_reset"
                reset_dir.mkdir(parents=True, exist_ok=True)
                (reset_dir / session_id_raw).write_text("", encoding="utf-8")
                # Also write a workspace-keyed marker so the statusline can
                # find it even when /clear assigns a new session_id. Claude
                # Code fires SessionStart(clear) with the pre-clear session_id,
                # but the statusline renders with the post-clear session_id, so
                # the session-keyed marker above is never matched.
                # The workspace key uses the same encoding Claude Code applies
                # to project dirs: replace "/" with "-" in the cwd.
                if cwd:
                    ws_key = cwd.replace("/", "-")
                    (reset_dir / f"ws_{ws_key}").write_text("", encoding="utf-8")
        if not _apply_session_bootstrap(payload):
            _initialize_session_stats(payload)

        session_id: str | None = _active_session_id() or session_id_raw
        if not session_id:
            return 0

        _append_session_start_event(session_id, source, model, cwd, transcript_path)
    except (OSError, TypeError, ValueError):
        pass  # fail-open

    # Update notification: show a system message if Atelier was auto-updated
    try:
        state_path = _atelier_root() / "update_state.json"
        if state_path.exists():
            update_data = json.loads(state_path.read_text("utf-8"))
            if (
                isinstance(update_data, dict)
                and update_data.get("current_version")
                and update_data.get("previous_version")
                and update_data["current_version"] != update_data["previous_version"]
                and not update_data.get("notified")
            ):
                prev_ver = update_data["previous_version"]
                cur_ver = update_data["current_version"]
                method = update_data.get("method", "auto")
                msg = (
                    f"Atelier updated from {prev_ver} → {cur_ver} (via {method}). "
                    "Release notes: https://github.com/atelier-ws/atelier/releases"
                )
                sys.stdout.write(json.dumps({"systemMessage": msg}) + "\n")
                sys.stdout.flush()
                # Mark as notified
                update_data["notified"] = True
                state_path.write_text(json.dumps(update_data, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass  # fail-open

    # Autopilot (M5): warm relevant prior context for this repo. Fail-open.
    try:
        from atelier.core.capabilities.autopilot.factory import run_and_emit

        run_and_emit("session_start", {"cwd": cwd})
    except (ImportError, OSError, json.JSONDecodeError, TypeError):
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
