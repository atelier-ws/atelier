#!/usr/bin/env python3
"""Ollama agent loop — drop-in replacement for `claude` CLI in TerminalBench.

This script runs inside the task container and implements a simple tool-calling
agent loop using Ollama's OpenAI-compatible API. It supports the same tool set
as the claude CLI (Bash, Read, Write, Edit, Glob, Grep) and outputs NDJSON
with a final ``{"type":"result", ...}`` line compatible with
:func:`terminalbench.agent_adapter.parse_stream_jsonl`.

Usage (inside container)::

    python /agent-tools/ollama_agent.py \\
        --instruction "$(cat /tests/instruction.txt)" \\
        --model qwen3.6:27b

The Ollama API base URL is auto-detected inside the container:
  - ``host.docker.internal`` (Docker Desktop on macOS/Windows)
  - Default gateway IP (Linux Docker bridge/overlay networks)
  - ``localhost`` (fallback for ``--network host`` or non-Docker)

Override via ``OLLAMA_BASE_URL`` env var or ``--base-url`` flag::

    python /agent-tools/ollama_agent.py \\
        --instruction "..." \\
        --model qwen3.6:27b \\
        --base-url http://my-host:11434/v1

Environment variables (override CLI defaults):
    OLLAMA_BASE_URL   (auto-detected if unset)
    OLLAMA_MODEL      (default: qwen3.6:27b)
    OLLAMA_API_KEY    (default: ollama)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI tool-calling format)
# ---------------------------------------------------------------------------

_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Execute a shell command. Use for building, testing, package management, git, and any CLI tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory (default: /testbed or current dir).",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 60).",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read a file's contents. Use for inspecting source files, configs, logs, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start from (1-indexed, default: 1).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read (default: all).",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write content to a file (creates or overwrites).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute or relative path to write to.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content to write.",
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Find and replace text in a file. Searches for the first occurrence of old_string and replaces it with new_string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Text to search for (must be unique in the file).",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text.",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Find files matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (e.g. **/*.py).",
                    },
                    "path": {
                        "type": "string",
                        "description": "Root directory (default: /testbed or current dir).",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search file contents with regex. Returns matching file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regular expression to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Root directory to search (default: current dir).",
                    },
                    "include": {
                        "type": "string",
                        "description": "File glob pattern (e.g. *.py).",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_CWD: str = os.getcwd()

_SYSTEM_PROMPT = f"""You are a coding agent tasked with solving programming problems.
You have access to the following tools:

1. **Bash** — Execute shell commands (build, test, git, package management, etc.)
2. **Read** — Read file contents
3. **Write** — Create or overwrite files
4. **Edit** — Find-and-replace in a file (use for surgical edits)
5. **Glob** — Find files matching a pattern
6. **Grep** — Search file contents with regex

Current working directory: {_CWD}

Rules:
- Think step by step. First explore the codebase, understand the problem, then implement the fix.
- Use Bash to run tests to verify your solution.
- For file edits, prefer Edit (surgical replacement) over Write (full overwrite).
- When you need to create a new file, use Write.
- After making changes, run the tests to verify.
- When the task is complete, call the `finish` function with a summary of what you did.
- Always write new files to the current working directory ({_CWD}) or as specified by the task.
- Do NOT assume a specific directory like /testbed/ — use the current directory.
- Check `pwd` if you are unsure about the current directory."""


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _tool_bash(command: str, cwd: str | None = None, timeout: int = 60) -> str:
    """Execute a shell command and return its output."""
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            if output:
                output += "\n--- stderr ---\n" + result.stderr
            else:
                output = result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        # Truncate very long outputs
        if len(output) > 10000:
            output = output[:10000] + f"\n... (truncated, {len(output)} total chars)"
        return output
    except subprocess.TimeoutExpired:
        return f"[Command timed out after {timeout}s]"
    except Exception as e:
        return f"[Error: {e}]"


def _tool_read(file_path: str, offset: int | None = None, limit: int | None = None) -> str:
    """Read a file's contents."""
    path = Path(file_path)
    if not path.exists():
        return f"[Error: File not found: {file_path}]"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        total = len(lines)
        start = (offset - 1) if offset and offset > 0 else 0
        end = min(start + limit, total) if limit else total
        selected = lines[start:end]
        result = "".join(selected)
        if not result.endswith("\n"):
            result += "\n"
        info = f"--- {file_path} ({start + 1}-{end}/{total} lines) ---\n"
        return info + result
    except Exception as e:
        return f"[Error reading {file_path}: {e}]"


def _tool_write(file_path: str, content: str) -> str:
    """Write content to a file (creates parent dirs)."""
    path = Path(file_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"[Wrote {len(content)} bytes to {file_path}]"
    except Exception as e:
        return f"[Error writing {file_path}: {e}]"


def _tool_edit(file_path: str, old_string: str, new_string: str) -> str:
    """Find and replace in a file."""
    path = Path(file_path)
    if not path.exists():
        return f"[Error: File not found: {file_path}]"
    try:
        content = path.read_text(encoding="utf-8")
        if old_string not in content:
            return f"[Error: old_string not found in {file_path}]"
        count = content.count(old_string)
        if count > 1:
            return f"[Error: Found {count} occurrences of old_string in {file_path}. Provide more context to disambiguate.]"
        new_content = content.replace(old_string, new_string)
        path.write_text(new_content, encoding="utf-8")
        return f"[Applied edit to {file_path} ({len(old_string)}B -> {len(new_string)}B)]"
    except Exception as e:
        return f"[Error editing {file_path}: {e}]"


def _tool_glob(pattern: str, path: str | None = None) -> str:
    """Find files matching a glob pattern."""
    root = Path(path) if path else Path.cwd()
    try:
        matches = sorted(root.rglob(pattern))
        if not matches:
            return f"[No files matching '{pattern}' in {root}]"
        result = "\n".join(str(m.relative_to(root)) for m in matches)
        return result
    except Exception as e:
        return f"[Error globbing: {e}]"


def _tool_grep(pattern: str, path: str | None = None, include: str | None = None) -> str:
    """Search file contents with regex."""
    search_path = path or "."
    cmd = ["rg", "-n", "--no-heading", "--color", "never"]
    if include:
        cmd.extend(["--include", include])
    cmd.append(pattern)
    cmd.append(search_path)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            output = result.stdout
            if len(output) > 5000:
                output = output[:5000] + f"\n... (truncated, {len(output)} total chars)"
            return output
        elif result.returncode == 1:
            return "[No matches found]"
        else:
            return f"[Grep error: {result.stderr[:500]}]"
    except FileNotFoundError:
        # Fallback to Python glob + grep
        try:
            matches = []
            root = Path(search_path)
            for f in root.rglob("*"):
                if f.is_file() and (not include or f.match(include)):
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                        for i, line in enumerate(text.splitlines(), 1):
                            if pattern in line:
                                matches.append(f"{f}:{i}:{line[:200]}")
                    except Exception:
                        pass
            if not matches:
                return "[No matches found]"
            result = "\n".join(matches[:100])
            if len(matches) > 100:
                result += f"\n... ({len(matches)} total matches)"
            return result
        except Exception as e:
            return f"[Error: {e}]"


_TOOL_MAP: dict[str, Any] = {
    "Bash": _tool_bash,
    "Read": _tool_read,
    "Write": _tool_write,
    "Edit": _tool_edit,
    "Glob": _tool_glob,
    "Grep": _tool_grep,
}


# ---------------------------------------------------------------------------
# Finish tool (signals task completion)
# ---------------------------------------------------------------------------

_FINISH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Call this function when the task is complete and all tests pass.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Summary of what was done to complete the task.",
                },
            },
            "required": ["summary"],
        },
    },
}

_ALL_TOOLS = [*_TOOLS, _FINISH_TOOL]


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


def _openai_client(base_url: str, api_key: str) -> Any:
    """Create an OpenAI-compatible client pointing at Ollama."""
    from openai import OpenAI

    return OpenAI(base_url=base_url, api_key=api_key)


def _call_model(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Send a chat completion request to Ollama."""
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=_ALL_TOOLS,
        temperature=0,
        max_tokens=4096,
    )
    choice = resp.choices[0]
    return {
        "message": choice.message,
        "usage": {
            "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
        },
    }


def _execute_tool_call(tc: Any) -> str:
    """Execute a single tool call and return the result as a string."""
    name = tc.function.name
    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError as e:
        return f"[Error parsing arguments for {name}: {e}]"

    if name == "finish":
        return json.dumps({"status": "finished", "summary": args.get("summary", "")})

    handler = _TOOL_MAP.get(name)
    if handler is None:
        return f"[Error: Unknown tool '{name}']"

    try:
        return handler(**args)
    except TypeError as e:
        return f"[Error: Invalid arguments for {name}: {e}]"
    except Exception as e:
        return f"[Error executing {name}: {e}]"


def run_agent(
    instruction: str,
    model: str,
    base_url: str,
    api_key: str,
    max_turns: int = 40,
) -> None:
    """Run the tool-calling agent loop and output NDJSON to stdout."""
    client = _openai_client(base_url=base_url, api_key=api_key)
    start_time = time.time()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]

    total_prompt_tokens = 0
    total_completion_tokens = 0
    finished = False
    stop_reason = "end_turn"

    for turn in range(max_turns):
        turn_start = time.time()

        # Output a progress line
        _emit_line({"type": "turn", "turn": turn, "message": f"Starting turn {turn}"})

        try:
            result = _call_model(client, model, messages)
        except Exception as e:
            error_msg = str(e)
            _emit_line({"type": "error", "message": error_msg})
            stop_reason = "error"
            break

        msg = result["message"]
        usage = result["usage"]
        total_prompt_tokens += usage["prompt_tokens"]
        total_completion_tokens += usage["completion_tokens"]

        # Handle tool calls
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            for tc in msg.tool_calls:
                name = tc.function.name
                tool_start = time.time()
                tool_result = _execute_tool_call(tc)
                tool_elapsed = time.time() - tool_start

                _emit_line(
                    {
                        "type": "tool",
                        "tool": name,
                        "arguments": tc.function.arguments,
                        "result": tool_result,
                        "duration_ms": round(tool_elapsed * 1000),
                    }
                )

                if name == "finish":
                    finished = True
                    stop_reason = "finished"
                    break

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )

            if finished:
                break

            turn_elapsed = time.time() - turn_start
            _emit_line(
                {
                    "type": "turn_end",
                    "turn": turn,
                    "duration_ms": round(turn_elapsed * 1000),
                }
            )
        else:
            # Model responded with a text answer — we're done
            content = msg.content or ""
            messages.append({"role": "assistant", "content": content})
            stop_reason = "end_turn"
            break
    else:
        stop_reason = "max_turns"

    elapsed_ms = round((time.time() - start_time) * 1000)

    # Emit final result line
    _emit_line(
        {
            "type": "result",
            "usage": {
                "input_tokens": total_prompt_tokens,
                "output_tokens": total_completion_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "total_cost_usd": 0.0,
            "duration_ms": elapsed_ms,
            "duration_api_ms": elapsed_ms,
            "num_turns": turn + 1,
            "is_error": stop_reason == "error",
            "stop_reason": stop_reason,
        }
    )


def _emit_line(obj: dict[str, Any]) -> None:
    """Write a single NDJSON line to stdout and flush."""
    sys.stdout.write(json.dumps(obj, default=str) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Ollama host auto-detection
# ---------------------------------------------------------------------------


def _resolve_ollama_base_url() -> str:
    """Auto-detect the Ollama server URL from inside a Docker container.

    Resolution order:
      1. ``OLLAMA_BASE_URL`` environment variable (explicit override).
      2. ``host.docker.internal`` — works on Docker Desktop (macOS/Windows).
      3. Default gateway IP — works on Linux Docker bridge/overlay networks.
      4. ``localhost`` — fallback for non-Docker or ``--network host``.
    """
    env_url = os.environ.get("OLLAMA_BASE_URL")
    if env_url:
        return env_url

    # Try Docker Desktop's special DNS name.
    try:
        socket.getaddrinfo("host.docker.internal", 11434)
        return "http://host.docker.internal:11434/v1"
    except socket.gaierror:
        pass

    # Try the default gateway (works on any Docker bridge network).
    # Method 1: ``ip route`` (available in most full images).
    try:
        result = subprocess.run(
            ["sh", "-c", "ip route show default | awk '{print $3}'"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        gateway = result.stdout.strip()
        if gateway and re.match(r"^\d+\.\d+\.\d+\.\d+$", gateway):
            return f"http://{gateway}:11434/v1"
    except Exception:
        pass

    # Method 2: ``/proc/net/route`` (available in all Linux containers).
    try:
        with open("/proc/net/route") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "00000000":
                    # Gateway is hex, little-endian (e.g. 010011AC → 172.17.0.1)
                    gw_hex = parts[2]
                    if len(gw_hex) == 8:
                        gw_bytes = bytes.fromhex(gw_hex)
                        gateway = ".".join(str(b) for b in reversed(gw_bytes))
                        if gateway and re.match(r"^\d+\.\d+\.\d+\.\d+$", gateway):
                            return f"http://{gateway}:11434/v1"
    except Exception:
        pass

    # Fallback: localhost.
    return "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ollama coding agent for TerminalBench",
    )
    parser.add_argument(
        "--instruction",
        required=True,
        help="Task instruction for the agent.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "qwen3.6:27b"),
        help="Ollama model name (default: qwen3.6:27b, or $OLLAMA_MODEL).",
    )
    parser.add_argument(
        "--base-url",
        default=_resolve_ollama_base_url(),
        help="Ollama API base URL (auto-detected by default; set $OLLAMA_BASE_URL to override).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OLLAMA_API_KEY", "ollama"),
        help="Ollama API key (default: ollama, or $OLLAMA_API_KEY).",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=40,
        help="Maximum agent turns (default: 40).",
    )

    args = parser.parse_args()

    try:
        run_agent(
            instruction=args.instruction,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            max_turns=args.max_turns,
        )
    except Exception as e:
        _emit_line(
            {
                "type": "result",
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "total_cost_usd": 0.0,
                "duration_ms": 0,
                "duration_api_ms": 0,
                "num_turns": 0,
                "is_error": True,
                "stop_reason": f"fatal_error: {e}",
            }
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
