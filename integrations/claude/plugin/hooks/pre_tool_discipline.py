#!/usr/bin/env python3
"""PreToolUse loop-discipline hook: read-after-edit guard + cycle-cap block.

Single PreToolUse hook that enforces two discipline rules, sharing session
state (keyed by workspace hash) with ``loop_discipline_post.py``:

* **read tool** -> (1) any file read clears an armed cycle-cap ``test_gate``
  (a read is the re-grounding step we want), then (2) the read-after-edit guard
  blocks the one wasteful case: a full re-read (``expand=true``, no range) of a
  file already edited this session. Targeted range reads and outline reads are
  always allowed.
* **shell tool** whose command is a test/build run -> if the gate is armed
  (set by ``loop_discipline_post.py`` after N consecutive failures), DENY the
  run with a hard block. The gate stays armed until a file read clears it.

Fail-open: any error exits 0 and prints nothing. Master opt-out via
ATELIER_LOOP_DISCIPLINE=0; the read-after-edit guard alone opts out via
ATELIER_READ_AFTER_EDIT_GUARD=0.
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

# Mirror of loop_discipline_post.py's _TEST_CMD so this hook stays import-free.
_TEST_CMD = re.compile(
    r"\b(cargo|pytest|go\s+test|npm\s+(?:test|run)|jest|tox|unittest|swift\s+test|gradle|mvn|make)\b|(?<!\w)test(?!\w)"
)


def _root() -> Path:
    raw = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    return Path(raw) if raw else Path.home() / ".atelier"


def _state_path() -> Path:
    # Keyed by workspace hash (matches loop_discipline_post.py) for per-task isolation.
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


def _is_read(name: str, ti: dict[str, Any]) -> bool:
    if name.endswith("__read") or name == "read":
        return True
    # name-agnostic fallback: a read has a path but is neither edit nor shell
    return "path" in ti and "edits" not in ti and "command" not in ti


def _is_shell(name: str, ti: dict[str, Any]) -> bool:
    return "command" in ti or name.endswith("__shell") or name in {"shell", "bash"}


def main() -> int:
    if os.environ.get("ATELIER_LOOP_DISCIPLINE", "1") == "0":
        return 0
    try:
        return _run()
    except Exception:  # noqa: BLE001 -- fail-open: never block on hook errors
        return 0


def _run() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, TypeError, OSError):
        return 0
    name = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        return 0

    state = _load()

    if _is_read(name, ti):
        # Any file read is the re-grounding step -- clear an armed cycle-cap gate.
        if state.get("test_gate"):
            state["test_gate"] = False
            _save(state)
        # Read-after-edit guard (separately opt-out-able).
        if os.environ.get("ATELIER_READ_AFTER_EDIT_GUARD", "1") != "0":
            raw_path = str(ti.get("path") or "")
            has_range = bool(ti.get("range")) or "#" in raw_path
            if bool(ti.get("expand")) and not has_range:
                base = Path(raw_path.split("#")[0]).name
                edited = {str(p) for p in (state.get("edited_paths") or [])}
                if base and base in edited:
                    reason = (
                        f"You edited {base} this session; its edit response already returned the changed region. "
                        "Avoid expand=true here -- it re-sends the whole file and is re-cached on every later turn. "
                        'Read the specific lines you need instead, e.g. range="L1-L120".'
                    )
                    print(json.dumps({"decision": "block", "reason": reason}))
        return 0

    if _is_shell(name, ti):
        command = str(ti.get("command") or "")
        if _TEST_CMD.search(command) and state.get("test_gate"):
            reason = (
                "Denied: 3+ consecutive test/build failures. Re-read the failing test AND the code "
                "under test in full, state the actual contract in one sentence, then make ONE "
                "root-caused fix. Test runs are blocked until you read the relevant file(s)."
            )
            print(json.dumps({"decision": "block", "reason": reason}))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
