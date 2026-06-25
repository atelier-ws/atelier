"""Session-local shell-command gates: verbatim-retry and diagnostic-silencing.

Escalation model mirrors the read-discipline nudge: the first violation
executes with a warning attached; an identical repeat is blocked with
guidance. State is process-local and resets with the server.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class GateDecision:
    action: str  # "allow" | "warn" | "block"
    reason: str = ""


_lock = threading.Lock()
_failed: dict[str, int] = {}
_retry_warned: set[str] = set()
_silence_warned: set[str] = set()

_SILENCE_RE = re.compile(r"2>\s*/dev/null|&>\s*/dev/null|>\s*/dev/null\s+2>&1")

# Commands whose stderr carries the diagnostics needed to debug a failure.
_DIAGNOSTIC_HEADS = frozenset(
    {
        "apt",
        "apt-get",
        "dpkg",
        "pip",
        "pip3",
        "uv",
        "npm",
        "pnpm",
        "yarn",
        "cargo",
        "make",
        "cmake",
        "gcc",
        "g++",
        "cc",
        "clang",
        "go",
        "mvn",
        "gradle",
    }
)


def _normalize(command: str) -> str:
    return " ".join(command.split())


def _silences_diagnostics(norm: str) -> bool:
    if not _SILENCE_RE.search(norm):
        return False
    return any(token in _DIAGNOSTIC_HEADS for token in norm.split())


# Tool-redirect coaching: shell commands that duplicate Atelier's indexed tools.
# Surfaced once per class per session as a non-blocking warning so the model
# switches to the cheaper `grep`/`read`/`sql` tool. Never blocks.
_redirect_warned: set[str] = set()

_SEARCH_HEADS = frozenset({"grep", "rg", "ag", "ack", "find", "cat", "head", "tail"})
_SQL_HEADS = frozenset(
    {"psql", "mysql", "mariadb", "sqlite3", "pg_dump", "mongosh", "mongo", "redis-cli", "clickhouse-client"}
)
_HEAD_SKIP = frozenset({"sudo", "command", "time", "nice", "env", "nohup", "stdbuf"})


def _first_head(norm: str) -> str:
    """First real command word, skipping env assignments and wrapper commands."""
    for token in norm.split():
        if token in _HEAD_SKIP:
            continue
        if "=" in token and not token.startswith(("-", "/")):
            continue  # FOO=bar env assignment
        return token.rsplit("/", 1)[-1]  # /usr/bin/grep -> grep
    return ""


def _redirect_hint(norm: str) -> tuple[str, str] | None:
    """Coaching for a leading shell command that duplicates an Atelier tool.

    Only the *first* command word is inspected, so piped output filters like
    ``ps aux | grep node`` are left alone — only a top-level code search/read or
    database command is nudged.
    """
    head = _first_head(norm)
    if head in _SEARCH_HEADS:
        return (
            "search",
            f"Prefer the `Explore` tool over shell `{head}` for code exploration.",
        )
    return None


def pre_run_gate(command: str) -> GateDecision:
    """Decide whether *command* may run, runs with a warning, or is blocked."""
    norm = _normalize(command)
    if not norm:
        return GateDecision("allow")
    with _lock:
        if _failed.get(norm):
            if norm in _retry_warned:
                return GateDecision(
                    "block",
                    "this exact command already failed twice this session.",
                )
            _retry_warned.add(norm)
            return GateDecision(
                "warn",
                "this exact command failed earlier this session.",
            )
        if _silences_diagnostics(norm):
            if norm in _silence_warned:
                return GateDecision("allow")
            _silence_warned.add(norm)
            return GateDecision("allow")
        hint = _redirect_hint(norm)
        if hint is not None:
            cls, message = hint
            if cls not in _redirect_warned:
                _redirect_warned.add(cls)
                return GateDecision("warn", message)
    return GateDecision("allow")


def note_result(command: str, *, exit_code: int | None, timed_out: bool = False) -> None:
    """Record the outcome of *command* so future identical runs can be gated."""
    norm = _normalize(command)
    if not norm:
        return
    failed = timed_out or (exit_code is not None and exit_code != 0)
    with _lock:
        if failed:
            _failed[norm] = _failed.get(norm, 0) + 1
        else:
            _failed.pop(norm, None)
            _retry_warned.discard(norm)


def note_workspace_changed() -> None:
    """Forget failure memory after a file edit.

    A verbatim re-run is only pathological when nothing changed between
    attempts; once the workspace is edited, retrying the same command is
    legitimate iteration.
    """
    with _lock:
        _failed.clear()
        _retry_warned.clear()


def reset() -> None:
    """Clear process-local state (tests)."""
    with _lock:
        _failed.clear()
        _retry_warned.clear()
        _silence_warned.clear()
        _redirect_warned.clear()
