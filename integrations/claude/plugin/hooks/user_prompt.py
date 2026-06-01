#!/usr/bin/env python3
"""UserPromptSubmit hook — capture user prompts into the RunLedger.

Fires each time the user submits a message.  Records the prompt text as an
``agent_message`` event (kind chosen for visibility in the timeline) so the
full conversation context is preserved in the ledger.

Prompt text is truncated to 8 KB to cap ledger file size while keeping full
context for normal prompts.

Fail-open: any error exits silently (code 0) — never blocks the agent.

Payload received on stdin:
  {
    "session_id": "abc123",
    "transcript_path": "...",
    "cwd": "...",
    "permission_mode": "default",
    "hook_event_name": "UserPromptSubmit",
    "prompt": "Write a function to calculate factorial"
  }
"""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PROMPT_BYTES = 8192  # 8 KB


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _session_state_path() -> Path:
    import hashlib

    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    root = Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")
    return root / "workspaces" / h / "session_state.json"


def _read_session_state() -> dict:  # type: ignore[type-arg]
    p = _session_state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))  # type: ignore[no-any-return]
    except Exception:
        logger.exception("Failed to read session state")
        return {}


def _write_session_state(state: dict[str, Any]) -> None:
    path = _session_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(state, tmp, indent=2)
            tmp_path = tmp.name
        Path(tmp_path).replace(path)
    except Exception:
        logger.exception("Failed to write session state")
        if tmp_path:
            with contextlib.suppress(Exception):
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


# ---------------------------------------------------------------------------
# RunLedger event writer
# ---------------------------------------------------------------------------


def _append_prompt_event(session_id: str, prompt: str) -> None:
    runs_dir = _atelier_root() / "runs"
    run_file = runs_dir / f"{session_id}.json"
    if not run_file.exists():
        return

    try:
        data = json.loads(run_file.read_text("utf-8"))
    except Exception:
        logger.exception("Failed to read run file")
        return

    events: list[dict[str, Any]] = data.setdefault("events", [])
    truncated = len(prompt) > _MAX_PROMPT_BYTES
    stored_prompt = prompt[:_MAX_PROMPT_BYTES]
    short = stored_prompt[:100].replace("\n", " ")

    events.append(
        {
            "kind": "agent_message",
            "at": datetime.datetime.now(datetime.UTC).isoformat(),
            "summary": f"user: {short}{'…' if len(stored_prompt) > 100 else ''}",
            "payload": {
                "role": "user",
                "prompt": stored_prompt,
                "truncated": truncated,
                "event": "UserPromptSubmit",
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
        logger.exception("Failed to update run file")
        if tmp_path:
            with contextlib.suppress(Exception):
                Path(tmp_path).unlink(missing_ok=True)


def _persist_last_user_prompt(prompt: str) -> None:
    state = _read_session_state()
    state["last_user_prompt"] = prompt
    _write_session_state(state)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Context-window estimation
# ---------------------------------------------------------------------------

# Sonnet context window (200k tokens). One token ≈ 4 bytes of UTF-8 text.
_CONTEXT_WINDOW_TOKENS = 200_000
_BYTES_PER_TOKEN = 4
_COMPACT_WARN_PCT = 70  # warn when estimated context exceeds this percent


def _estimate_context_pct(transcript_path: str) -> int | None:
    """Return estimated context utilisation [0-100] from transcript file size.

    Fail-open: returns None on any error.
    """
    try:
        size = Path(transcript_path).stat().st_size
        estimated_tokens = size // _BYTES_PER_TOKEN
        return min(100, round(estimated_tokens * 100 / _CONTEXT_WINDOW_TOKENS))
    except OSError:
        return None


def _emit_compact_warning(pct: int) -> None:
    """Write a compact-nudge line to stdout so Claude Code injects it as context."""
    msg = (
        f"[Atelier] Context estimated at ~{pct}% of window. "
        "Call mcp__atelier__compact now, then tell the user to run /compact "
        "before starting multi-step work."
    )
    # Claude Code UserPromptSubmit hooks can inject context by writing
    # {"type": "context", "content": "..."} to stdout.
    sys.stdout.write(json.dumps({"type": "context", "content": msg}) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0

    prompt: str = payload.get("prompt", "") or ""
    if not prompt.strip():
        return 0
    stored_prompt = prompt[:_MAX_PROMPT_BYTES]

    # Context-window check — inject a nudge when transcript is large.
    transcript_path: str = payload.get("transcript_path", "") or ""
    if transcript_path:
        pct = _estimate_context_pct(transcript_path)
        if pct is not None and pct >= _COMPACT_WARN_PCT:
            _emit_compact_warning(pct)

    # Autopilot (M5): inject scoped context for this prompt. Fail-open.
    try:
        _persist_last_user_prompt(stored_prompt)
        from atelier.core.capabilities.autopilot.factory import run_and_emit

        run_and_emit("user_prompt", {"prompt": prompt})
    except (ImportError, OSError, ValueError):
        pass

    try:
        session_id = _active_session_id()
        if not session_id:
            return 0
        _append_prompt_event(session_id, stored_prompt)
    except (OSError, TypeError, ValueError):
        pass  # fail-open

    return 0


if __name__ == "__main__":
    sys.exit(main())
