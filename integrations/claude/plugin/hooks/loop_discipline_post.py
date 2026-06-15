#!/usr/bin/env python3
"""PostToolUse loop-discipline hook: cycle-cap + edit tracking.

Runs on every PostToolUse and filters internally (name-agnostic across hosts):

* **edit tool** -> record the edited file basenames so the PreToolUse
  read-after-edit guard can block a redundant full re-read.
* **shell tool** -> count *consecutive* failing test/build commands. A failing
  ``cargo test`` / ``pytest`` returns normal output with a non-zero exit code
  (not a tool error), so PostToolUseFailure never sees it -- we inspect the
  result text here. At/above a threshold of consecutive failures we set
  ``test_gate`` in shared state, which arms a HARD PreToolUse block in
  ``pre_tool_discipline.py`` (further test runs are denied until a file read
  clears the gate). We also emit a one-time model-facing nudge exactly when the
  streak first crosses the threshold. A passing test resets the streak (and
  disarms the gate); non-test commands leave both untouched.

Fail-open: any error exits 0 and prints nothing. Threshold via
ATELIER_CYCLE_CAP_THRESHOLD (default 3, matching the persona's cycle ceiling).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _threshold() -> int:
    try:
        return max(2, int(os.environ.get("ATELIER_CYCLE_CAP_THRESHOLD", "3") or "3"))
    except ValueError:
        return 3


_TEST_CMD = re.compile(
    r"\b(cargo|pytest|go\s+test|npm\s+(?:test|run)|jest|tox|unittest|swift\s+test|gradle|mvn|make)\b|(?<!\w)test(?!\w)"
)
_FAIL_MARKER = re.compile(
    r"FAILED|error\[E|panicked|AssertionError|Traceback|test result: FAILED|\d+\s+failed|\bFAIL\b"
)


def _root() -> Path:
    raw = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    return Path(raw) if raw else Path.home() / ".atelier"


def _state_path() -> Path:
    # Key by workspace hash so concurrent/sequential tasks (each with its own
    # CLAUDE_WORKSPACE_ROOT) never share a fail-streak or edited-paths set.
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    return _root() / "workspaces" / h / "loop_discipline.json"


def _load() -> dict[str, Any]:
    with contextlib.suppress(OSError, json.JSONDecodeError):
        data = json.loads(_state_path().read_text("utf-8"))
        if isinstance(data, dict):
            return data
    return {}


def _save(state: dict[str, Any]) -> None:
    with contextlib.suppress(OSError):
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state), encoding="utf-8")


def _is_edit(name: str, ti: dict[str, Any]) -> bool:
    return isinstance(ti.get("edits"), list) or name.endswith("__edit") or name == "edit"


def _is_shell(name: str, ti: dict[str, Any]) -> bool:
    return "command" in ti or name.endswith("__shell") or name in {"shell", "bash"}


def _edit_targets(ti: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("file_path", "path", "filename"):
        val = ti.get(key)
        if isinstance(val, str) and val:
            out.append(val)
    edits = ti.get("edits")
    if isinstance(edits, list):
        for entry in edits:
            if isinstance(entry, dict):
                fp = entry.get("file_path") or entry.get("path")
                if isinstance(fp, str) and fp:
                    out.append(fp)
    return out


def _response_text(resp: Any) -> str:
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return "\n".join(b.get("text", "") for b in resp if isinstance(b, dict))
    if isinstance(resp, dict):
        parts: list[str] = []
        content = resp.get("content")
        if isinstance(content, list):
            parts.extend(b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
        for key in ("stdout", "stderr", "output", "error"):
            val = resp.get(key)
            if isinstance(val, str):
                parts.append(val)
        return "\n".join(parts) if parts else json.dumps(resp)[:4000]
    return str(resp)[:4000]


def _command_failed(text: str) -> bool:
    m = re.search(r"exit_code=(\d+)", text)
    if m:
        return m.group(1) != "0"
    return bool(_FAIL_MARKER.search(text))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, TypeError, OSError):
        return 0
    name = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        return 0

    state = _load()

    if _is_edit(name, ti):
        edited = set(state.get("edited_paths") or [])
        for target in _edit_targets(ti):
            edited.add(Path(target.split("#")[0]).name)
        state["edited_paths"] = sorted(edited)[-80:]
        _save(state)
        return 0

    if _is_shell(name, ti):
        command = str(ti.get("command") or "")
        if not _TEST_CMD.search(command):
            return 0  # non-test command: leave the streak untouched
        text = _response_text(payload.get("tool_response") or payload.get("tool_result") or {})
        failed = _command_failed(text)
        prev_streak = int(state.get("fail_streak", 0) or 0)
        fail_streak = prev_streak + 1 if failed else 0
        threshold = _threshold()
        state["fail_streak"] = fail_streak
        # Arm/disarm the PreToolUse cycle-cap block. Once armed it stays armed
        # (streak no longer resets here) until a file read clears the gate.
        state["test_gate"] = fail_streak >= threshold
        _save(state)
        # Nudge exactly once, at the moment the streak crosses the threshold.
        if failed and fail_streak == threshold:
            msg = (
                f"{threshold}+ consecutive test/build failures. STOP reactive editing. Re-read the "
                "failing test AND the code under test in full, state the actual contract in one "
                "sentence, then make ONE root-caused fix. If results look stale or cached, run the "
                "toolchain's clean once (cargo clean / rm -rf build / drop caches) before retrying."
            )
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
