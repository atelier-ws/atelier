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
            f"Prefer the `grep` tool (regex/glob/type search, token-budgeted output) or `read` "
            f"(outline/range/batch) over shell `{head}` for finding and reading code — one indexed "
            "round-trip is far cheaper than piping shell text into context. The command ran; use the "
            "tool for subsequent searches.",
        )
    if head in _SQL_HEADS:
        return (
            "sql",
            f"Prefer the `sql` tool (auto-LIMIT, schema introspection, batched queries) over shell "
            f"`{head}` for database work. The command ran; use the tool next time.",
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
                    "this exact command already failed twice this session; "
                    "change the input, scope, timeout, tool, or approach before retrying",
                )
            _retry_warned.add(norm)
            return GateDecision(
                "warn",
                "this exact command failed earlier this session; an unchanged retry that "
                "fails again will be blocked - consider a different input, timeout, or approach",
            )
        if _silences_diagnostics(norm):
            if norm in _silence_warned:
                return GateDecision(
                    "block",
                    "stderr redirection to /dev/null on install/build commands is blocked after "
                    "the first warning; rerun without silencing so failures stay diagnosable",
                )
            _silence_warned.add(norm)
            return GateDecision(
                "warn",
                "this command silences stderr on an install/build step; diagnostics will be "
                "lost if it fails - prefer running it without the /dev/null redirection",
            )
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
