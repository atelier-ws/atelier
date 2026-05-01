"""Session parser for Atelier — converts raw JSONL session content into a
readable conversation timeline.

Public API::

    from atelier.gateway.integrations._session_parser import parse_session_turns

    turns = parse_session_turns(content, source="claude")
    # Each turn: {"kind": str, "at": str | None, "summary": str, "content": str}

Supported sources: ``"claude"``, ``"codex"``, ``"opencode"``.

At most 300 turns are returned. Content is stored in full (no truncation).
"""

from __future__ import annotations

import json
import re
from typing import Any

# Maximum number of turns to return
_MAX_TURNS = 300
# Maximum content length for diffs display
_MAX_CONTENT = 500

# System-message prefixes to skip in user blocks (Claude + Codex)
_SYSTEM_PREFIXES_CLAUDE = (
    "<local-command",
    "<ide_",
    "<command-",
    "<thinking>",
)

_SYSTEM_PREFIXES_CODEX = (
    "<user_instructions>",
    "<environment_context>",
    "<permissions instructions>",
    "<permissions_instructions>",
    "# AGENTS.md instructions",
    "AGENTS.md instructions",
    "<local-command",
    "<ide_",
    "<thinking>",
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_session_turns(content: str, source: str) -> list[dict[str, Any]]:
    """Parse raw JSONL *content* for *source* into a list of turn dicts.

    Each dict has keys: ``kind``, ``at``, ``summary``, ``content``.
    Kinds: ``user_message``, ``agent_message``, ``shell_command``,
    ``file_edit``, ``tool_call``, ``patch``.
    """
    if source == "claude":
        turns = _parse_claude(content)
    elif source == "codex":
        turns = _parse_codex(content)
    elif source == "opencode":
        turns = _parse_opencode(content)
    else:
        turns = []

    return turns[:_MAX_TURNS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trunc(text: str) -> str:
    """Return text as-is (no truncation)."""
    return text


def _turn(
    kind: str,
    summary: str,
    content: str,
    at: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "at": at,
        "summary": summary,
        "content": _trunc(content),
    }


def _extract_text_from_claude_content(content: Any) -> str:
    """Extract plain text from a Claude user-message content field.

    Skips system-injected blocks (local-command, ide_, command-).
    """
    if isinstance(content, str):
        text = content.strip()
        if any(text.startswith(p) for p in _SYSTEM_PREFIXES_CLAUDE):
            return ""
        return text
    if isinstance(content, list):
        parts: list[str] = []
        for blk in content:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") != "text":
                continue
            t = blk.get("text", "").strip()
            if not t:
                continue
            if any(t.startswith(p) for p in _SYSTEM_PREFIXES_CLAUDE):
                continue
            parts.append(t)
        return " ".join(parts).strip()
    return ""


def _files_from_patch(patch_text: str) -> list[str]:
    """Extract file paths from a Codex apply_patch diff."""
    files: list[str] = []
    for ln in patch_text.splitlines():
        m = re.match(
            r"^\*\*\*\s+(?:Update|Add|Delete|Move|Rename)\s+File:\s+(.+)$",
            ln,
            re.IGNORECASE,
        )
        if m:
            files.append(m.group(1).strip())
    return files


def _is_codex_system_message(text: str) -> bool:
    """Return True if text is a system-injected Codex message."""
    if any(text.startswith(p) for p in _SYSTEM_PREFIXES_CODEX):
        return True
    if re.search(r"<\s*(local-command\w*|ide_\w*|thinking)\b", text, re.IGNORECASE):
        return True
    # Very long messages that look like system prompts
    return bool(len(text) > 3000 and "AGENTS.md" in text)


# ---------------------------------------------------------------------------
# Claude parser
# ---------------------------------------------------------------------------


def _parse_claude(content: str) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        ev_type = ev.get("type", "")
        at: str | None = ev.get("timestamp") or None

        # Skip ai-title (captured as task in trace), queue-operation, progress, etc.
        if ev_type in ("ai-title", "queue-operation", "progress", "last-prompt"):
            continue

        if ev_type == "user":
            if ev.get("isMeta"):
                continue
            msg = ev.get("message") or {}
            text = _extract_text_from_claude_content(msg.get("content", ""))
            if not text:
                continue
            turns.append(_turn("user_message", text[:80], text, at=at))

        elif ev_type == "assistant":
            msg = ev.get("message") or {}
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")

                if btype == "text":
                    text = block.get("text", "").strip()
                    if not text:
                        continue
                    turns.append(_turn("agent_message", text[:80], text, at=at))

                elif btype == "reasoning":
                    text = block.get("text", "").strip()
                    if text:
                        turns.append(_turn("thinking", text[:80], text, at=at))

                elif btype == "redacted":
                    # Redacted content (thinking or other)
                    text = block.get("text", "").strip()
                    if text:
                        turns.append(_turn("thinking", "[redacted]", text, at=at))

                elif btype == "tool_use":
                    name = block.get("name", "unknown")
                    inp = block.get("input") or {}

                    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                        fp = inp.get("file_path") or inp.get("path", "")
                        summary = f"{name}({fp})"
                        turns.append(
                            _turn(
                                "file_edit",
                                summary,
                                json.dumps(inp, ensure_ascii=False),
                                at=at,
                            )
                        )

                    elif name == "Bash":
                        cmd = str(inp.get("command", ""))
                        summary = cmd[:100]
                        turns.append(_turn("shell_command", summary, cmd, at=at))

                    else:
                        summary = f"{name}(...)"
                        turns.append(
                            _turn(
                                "tool_call",
                                summary,
                                json.dumps(inp, ensure_ascii=False),
                                at=at,
                            )
                        )

    return turns


# ---------------------------------------------------------------------------
# Codex parser — detects format A vs B
# ---------------------------------------------------------------------------


def _parse_codex(content: str) -> list[dict[str, Any]]:
    """Parse Codex JSONL — auto-detects Format A (event_msg) vs Format B (flat)."""
    fmt = _detect_codex_format(content)
    if fmt == "event_msg":
        return _parse_codex_format_a(content)
    return _parse_codex_format_b(content)


def _detect_codex_format(content: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev_type = ev.get("type")
        if ev_type == "session_meta":
            return "event_msg"
        if ev_type in ("message", "reasoning", "function_call", "function_call_output"):
            return "flat"
        if ev_type is None and "id" in ev and "timestamp" in ev:
            return "flat"
        return "event_msg"
    return "event_msg"


def _parse_codex_format_a(content: str) -> list[dict[str, Any]]:
    """Format A: event_msg-wrapped (VSCode extension / older CLI)."""
    turns: list[dict[str, Any]] = []

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        ev_type = ev.get("type", "")

        if ev_type == "event_msg":
            payload = ev.get("payload") or {}
            ptype = payload.get("type", "")

            if ptype == "user_message":
                msg = str(payload.get("message", "")).strip()
                if not msg or _is_codex_system_message(msg):
                    continue
                turns.append(_turn("user_message", msg[:80], msg))

            elif ptype == "agent_message":
                msg = str(payload.get("message", "")).strip()
                if not msg:
                    continue
                turns.append(_turn("agent_message", msg[:80], msg))

            elif ptype == "exec_command_end":
                cmd_raw = payload.get("command", "")
                if isinstance(cmd_raw, list):
                    cmd = str(cmd_raw[-1]) if cmd_raw else ""
                else:
                    cmd = str(cmd_raw)
                if cmd:
                    turns.append(_turn("shell_command", cmd[:100], cmd))

            elif ptype == "patch_apply_end":
                changes: dict[str, Any] = payload.get("changes") or {}
                first_path = next(iter(changes), "") if changes else ""
                summary = first_path or "patch applied"
                turns.append(_turn("file_edit", summary, json.dumps(list(changes.keys()))))

        elif ev_type == "response_item":
            # Codex TUI emits response_item with function_call, message, etc.
            payload = ev.get("payload") or {}
            rtype = payload.get("type", "")

            if rtype == "function_call":
                name = payload.get("name", "unknown")
                args_raw = payload.get("arguments", "{}")
                if isinstance(args_raw, dict):
                    args = args_raw
                else:
                    try:
                        args = json.loads(str(args_raw))
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                if name == "apply_patch":
                    patch_text = str(args.get("patch", ""))
                    files = _files_from_patch(patch_text)
                    summary = files[0] if files else "patch"
                    turns.append(_turn("file_edit", summary, patch_text))
                elif name in ("exec_command", "shell_command"):
                    cmd = str(args.get("cmd") or args.get("command") or "")
                    if cmd:
                        turns.append(_turn("shell_command", cmd[:100], cmd))
                else:
                    summary = f"{name}(...)"
                    turns.append(_turn("tool_call", summary, json.dumps(args, ensure_ascii=False)))

            elif rtype == "message":
                # Agent message from response_item wrapper
                for blk in payload.get("content", []):
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") not in ("output_text", "text"):
                        continue
                    text = str(blk.get("text", "")).strip()
                    if text:
                        turns.append(_turn("agent_message", text[:80], text))

            elif ev_type == "reasoning":
                # Chain-of-thought / thinking block
                text = str(ev.get("text") or ev.get("content", "")).strip()
                if text:
                    turns.append(_turn("thinking", text[:80], text))

            elif ev_type == "redacted":
                # Redacted thinking
                text = str(ev.get("text") or "").strip()
                if text:
                    turns.append(_turn("thinking", "[redacted]", text))

    return turns


def _parse_codex_format_b(content: str) -> list[dict[str, Any]]:
    """Format B: flat objects (Codex TUI / newer CLI)."""
    turns: list[dict[str, Any]] = []

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        ev_type = ev.get("type")

        if ev_type == "message":
            role = ev.get("role", "")
            if role == "user":
                for blk in ev.get("content") or []:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") not in ("input_text", "text"):
                        continue
                    text = str(blk.get("text", "")).strip()
                    if not text or _is_codex_system_message(text):
                        continue
                    turns.append(_turn("user_message", text[:80], text))
                    break  # one user turn per message event

            elif role == "assistant":
                for blk in ev.get("content") or []:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") not in ("output_text", "text"):
                        continue
                    text = str(blk.get("text", "")).strip()
                    if not text:
                        continue
                    turns.append(_turn("agent_message", text[:80], text))
                    break

        elif ev_type == "function_call":
            name = str(ev.get("name") or "unknown")
            args_raw = ev.get("arguments", "{}")
            if isinstance(args_raw, dict):
                args: dict[str, Any] = args_raw
            else:
                try:
                    args = json.loads(str(args_raw))
                except (json.JSONDecodeError, TypeError):
                    args = {}

            if name == "apply_patch":
                patch_text = str(args.get("patch", ""))
                files = _files_from_patch(patch_text)
                summary = files[0] if files else "patch"
                turns.append(_turn("file_edit", summary, patch_text))

            elif name in ("exec_command", "shell_command"):
                cmd = str(args.get("cmd") or args.get("command") or "")
                turns.append(_turn("shell_command", cmd[:100], cmd))

            else:
                summary = f"{name}(...)"
                turns.append(_turn("tool_call", summary, json.dumps(args, ensure_ascii=False)))

        elif ev_type == "reasoning":
            # Chain-of-thought / thinking block
            text = str(ev.get("text") or ev.get("content", "")).strip()
            if text:
                turns.append(_turn("thinking", text[:80], text))

        elif ev_type == "redacted":
            # Redacted thinking
            text = str(ev.get("text") or "").strip()
            if text:
                turns.append(_turn("thinking", "[redacted]", text))

    return turns


# ---------------------------------------------------------------------------
# OpenCode parser
# ---------------------------------------------------------------------------


def _parse_opencode(content: str) -> list[dict[str, Any]]:
    """Parse OpenCode JSONL serialised by OpenCodeImporter (_type wrapper)."""
    turns: list[dict[str, Any]] = []

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        _type = ev.get("_type", "")
        data: dict[str, Any] = ev.get("data") or {}

        if _type == "message":
            role = data.get("role", "")
            if role == "user":
                # Check for thinking/reasoning in parts first
                for part in data.get("parts") or []:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type", "")
                    if ptype == "reasoning":
                        text = str(part.get("text", "")).strip()
                        if text:
                            turns.append(_turn("thinking", text[:80], text))
                    elif ptype == "text":
                        text = str(part.get("text", "")).strip()
                        if text:
                            text = str(part.get("text", "")).strip()
                            if text:
                                turns.append(_turn("user_message", text[:80], text))
                # Fallback to content string
                if not any(t.get("kind") == "user_message" for t in turns[-5:]):
                    text = _opencode_user_text(data)
                    if text:
                        turns.append(_turn("user_message", text[:80], text))

            elif role == "assistant":
                # Check for thinking/reasoning in parts first
                has_thinking = False
                for part in data.get("parts") or []:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type", "")
                    if ptype == "reasoning":
                        text = str(part.get("text", "")).strip()
                        if text:
                            turns.append(_turn("thinking", text[:80], text))
                            has_thinking = True
                if not has_thinking:
                    text = _opencode_assistant_text(data)
                    if text:
                        turns.append(_turn("agent_message", text[:80], text))

        elif _type == "part":
            ptype = data.get("type", "")
            tool = data.get("tool", "")

            if ptype == "tool":
                state: dict[str, Any] = data.get("state") or {}
                inp: dict[str, Any] = state.get("input") or {}

                if tool == "bash":
                    cmd = str(inp.get("command", ""))
                    turns.append(_turn("shell_command", cmd[:100], cmd))

                elif tool in ("edit", "write", "multiedit"):
                    fp = inp.get("filePath") or inp.get("path") or inp.get("file_path", "")
                    summary = f"{tool}({fp})"
                    turns.append(_turn("file_edit", summary, json.dumps(inp, ensure_ascii=False)))

                else:
                    summary = f"{tool}(...)"
                    turns.append(_turn("tool_call", summary, json.dumps(inp, ensure_ascii=False)))

            elif ptype == "patch":
                files: list[str] = data.get("files") or []
                summary = files[0] if files else "patch"
                turns.append(_turn("patch", summary, json.dumps(files)))

            elif ptype == "reasoning":
                # Standalone reasoning part
                text = str(data.get("text") or "").strip()
                if text:
                    turns.append(_turn("thinking", text[:80], text))

    return turns


def _opencode_user_text(data: dict[str, Any]) -> str:
    """Extract displayable text from an OpenCode user message data dict."""
    # Try summary.diffs
    summary = data.get("summary") or {}
    if isinstance(summary, dict):
        diffs = summary.get("diffs")
        if diffs:
            return str(diffs)[:_MAX_CONTENT]

    # Try parts array
    for part in data.get("parts") or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text = str(part.get("text", "")).strip()
            if text:
                return text

    # Try content string
    content = data.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    return ""


def _opencode_assistant_text(data: dict[str, Any]) -> str:
    """Extract displayable text from an OpenCode assistant message data dict."""
    for part in data.get("parts") or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text = str(part.get("text", "")).strip()
            if text:
                return text
    content = data.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return ""
