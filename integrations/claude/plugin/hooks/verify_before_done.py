#!/usr/bin/env python3
"""Stop hook: verify-before-done.

A code change is not done until it has been *executed* against a behavioral
check. This hook nudges once when a session edited source files but the
transcript shows no test run and no execution of the changed code.

Generic and language-agnostic: it keys on tool *shape* (an edit tool touched a
code file; a shell command matched a test runner or an interpreter running
code), never on any project, task, or framework specifics. Mechanical checks
(type-check / lint / format) deliberately do not count as verification.

Bounded and fail-open by design -- a hard iteration cap backfired here before
(see loop_discipline_post.py), so this fires at most once per session (it
returns immediately when ``stop_hook_active`` is set) and any error exits 0
without blocking. Opt out entirely with ATELIER_VERIFY_BEFORE_DONE=0.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Source-code suffixes that warrant a behavioral check after an edit. Editing
# only docs/config/data (.md/.json/.yaml/.txt/...) does not trip the gate.
_CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".ipynb",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".java",
        ".kt",
        ".kts",
        ".scala",
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".h",
        ".hpp",
        ".cs",
        ".swift",
        ".m",
        ".mm",
        ".ex",
        ".exs",
        ".erl",
        ".clj",
        ".hs",
        ".ml",
        ".lua",
        ".dart",
        ".sh",
    }
)

# A shell command that runs a recognized test runner. Language-agnostic.
_TEST_RUN = re.compile(
    r"""(?xi)
    \b(
        pytest | py\.test | nose2? | tox | nox
      | unittest | runtests
      | go\s+test | cargo\s+test | dotnet\s+test | mix\s+test | phpunit
      | jest | vitest | mocha | ava | rspec | minitest | ctest
      | bazel\s+test | ([./\w]*gradlew|gradle|mvn)\b[^\n]*\btest
      | (npm|pnpm|yarn|bun)\s+(run\s+\S+|test)
      | (rake|bundle\s+exec)\b[^\n]*\b(test|spec|rspec)
      | manage\.py\s+test
    )\b
    """
)

# A shell command that *executes* code, e.g. `python repro.py`, `python -c ...`,
# `node check.js`. Lenient on purpose: counting more things as "verified" biases
# toward NOT firing, which keeps the gate from nagging legitimate work.
_CODE_RUN = re.compile(
    r"""(?xi)
    (?:^|[;&|]\s*|\s)
    (python[0-9.]*|node|deno|bun|ruby|php|perl|Rscript|julia)\s+
    (-c\b|-e\b|-m\s+\S|[^\s;|&]+\.(py|js|mjs|ts|rb|php|pl|R|jl))
    """
)


def _disabled() -> bool:
    v = os.environ.get("ATELIER_VERIFY_BEFORE_DONE")
    return v is not None and v.strip().lower() in {"0", "false", "off", "no"}


def _is_edit_tool(name: str) -> bool:
    return name in {"edit", "write", "multiedit", "notebookedit"} or name.endswith("edit")


def _edit_targets(tool_input: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("file_path", "path", "filename"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            out.append(val)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for entry in edits:
            if isinstance(entry, dict):
                fp = entry.get("file_path") or entry.get("path")
                if isinstance(fp, str) and fp:
                    out.append(fp)
    return out


def _is_code_path(path: str) -> bool:
    return Path(path.split("#")[0]).suffix.lower() in _CODE_SUFFIXES


def scan_transcript(transcript_path: str | None) -> tuple[list[str], bool]:
    """Return (edited code files, whether a behavioral check was executed)."""
    edited: list[str] = []
    verified = False
    if not transcript_path:
        return edited, verified
    p = Path(transcript_path)
    if not p.exists():
        return edited, verified
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return edited, verified
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = str(block.get("name") or "").split("__")[-1].lower()
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                continue
            if _is_edit_tool(name):
                edited.extend(t for t in _edit_targets(tool_input) if _is_code_path(t))
            elif name in {"bash", "shell"}:
                cmd = str(tool_input.get("command") or "")
                if _TEST_RUN.search(cmd) or _CODE_RUN.search(cmd):
                    verified = True
    return edited, verified


_REASON = (
    "verify-before-done: this session edited code ({n} file(s): {sample}) but the "
    "transcript shows no executed test and no run of the changed code. Run the test "
    "that exercises this change -- or reproduce the behavior in the shell -- and confirm "
    "it passes before finishing. Mechanical checks (type-check / lint / format) do not "
    "count. If you have already verified another way, note how and stop again."
)


def decide(payload: dict[str, Any]) -> dict[str, str] | None:
    if _disabled():
        return None
    # Bounded: Claude Code sets stop_hook_active after a prior Stop block, so we
    # never re-block the same session (a hard cap backfired before).
    if payload.get("stop_hook_active") is True:
        return None
    edited, verified = scan_transcript(payload.get("transcript_path"))
    if not edited or verified:
        return None
    uniq = sorted({Path(p.split("#")[0]).name for p in edited})
    reason = _REASON.format(n=len(uniq), sample=", ".join(uniq[:4]))
    return {"decision": "block", "reason": reason}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        result = decide(payload)
        if result is not None:
            print(json.dumps(result))
    except Exception:  # noqa: BLE001 -- fail-open: never break the agent on a hook error
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
