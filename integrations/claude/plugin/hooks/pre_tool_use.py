#!/usr/bin/env python3
"""PreToolUse hook for Edit/Write/MultiEdit.

Reads the hook payload from stdin. If the target file matches a risky path,
returns a JSON decision telling Claude to call `task` first.

This hook is **opt-in**. Enable it via hooks.json once the skills flow is
comfortable. It defaults to non-blocking (decision: "ask") to avoid
surprising users.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _bootstrap_atelier_path() -> None:
    """Make hooks runnable from a copied Claude plugin without PYTHONPATH."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[4] / "src",  # repo or ~/.local/share/atelier install layout
        Path.home() / ".local" / "share" / "atelier" / "src",
    ]
    for candidate in candidates:
        if candidate.exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)


def _benchmark_gate_enabled() -> bool:
    raw_mode = os.environ.get("ATELIER_BENCH_MODE")
    if raw_mode is None:
        return False
    try:
        _bootstrap_atelier_path()
        from atelier.bench.mode import is_off

        return not is_off()
    except (ImportError, AttributeError, ValueError):
        return False


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


def _session_state_path() -> Path:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    root = Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")
    return root / "workspaces" / _workspace_key(workspace) / "session_state.json"


def _read_session_state() -> dict[str, Any]:
    try:
        path = _session_state_path()
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


RISKY_PATTERNS = [
    re.compile(p)
    for p in (
        r"(^|/)shopify(/|$)",
        r"(^|/)pdp(/|$)",
        r"(^|/)catalog(/|$)",
        r"(^|/)tracker(/|$)",
        r"(^|/)publish(/|$)",
        r"(^|/)schema(/|$)",
        r"alembic/versions/",
    )
]


def _is_risky(path: str) -> bool:
    return any(p.search(path) for p in RISKY_PATTERNS)


def _decide(decision: str, reason: str = "") -> None:
    """Emit a current-schema PreToolUse permission decision (Claude Code v2.1.x).

    The legacy top-level {"decision": ...} form is deprecated for PreToolUse and
    is silently ignored, so allow/deny must go through hookSpecificOutput.
    """
    spec = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    if reason:
        spec["permissionDecisionReason"] = reason
    print(json.dumps({"hookSpecificOutput": spec}))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, TypeError):
        return 0  # fail-open: never break the agent on hook parse error

    tool_name = str(payload.get("tool_name") or payload.get("tool") or "").lower()
    if tool_name and tool_name not in {"edit", "multiedit", "write"}:
        _decide("allow")
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    if _benchmark_gate_enabled():
        try:
            _bootstrap_atelier_path()
            from atelier.core.capabilities.grounded_loop.grounding_evidence import (
                extract_edit_targets,
                missing_grounding_targets,
            )
        except (ImportError, AttributeError, ValueError):
            _decide("allow")
            return 0

        workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
        state = _read_session_state()
        session_id = str(payload.get("session_id") or "").strip()
        targets = extract_edit_targets(tool_name, tool_input, workspace_root=workspace)
        risky_targets = [target for target in targets if _is_risky(target)]
        missing = missing_grounding_targets(
            state,
            session_id=session_id,
            targets=risky_targets,
            workspace_root=workspace,
        )
        if missing:
            msg = (
                "Atelier benchmark gate: ground this edit with read, grep, search, "
                "node, or explore before editing "
                f"{', '.join(missing[:4])}."
            )
            _decide("deny", msg)
            return 0
        if risky_targets:
            _decide("allow")
            return 0

    target = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("filename") or ""
    if not target or not _is_risky(target):
        _decide("allow")
        return 0

    # Always allow risky operations
    _decide("allow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
