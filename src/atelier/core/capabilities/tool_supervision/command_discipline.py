"""Session-local shell-command gates: verbatim-retry and diagnostic-silencing.

Escalation model mirrors the read-discipline nudge: the first violation
executes with a warning attached; an identical repeat is blocked with
guidance. State is process-local and resets with the server.
"""

from __future__ import annotations

import re
import shlex
import threading
from dataclasses import dataclass
from pathlib import Path


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
# Graduated per class per session: the FIRST violation executes with a warning
# naming the replacement tool; a REPEAT in the same class is blocked (search and
# read classes only — `find` and db shells stay warn-once, their shell uses are
# too often legitimate). Set ATELIER_SHELL_REDIRECT_BLOCK=0 to keep everything
# warn-only. Rationale: one nudge per session measurably does not change
# behavior — sessions still run 50+ grep/cat calls through bash and save
# nothing; the indexed tools only pay off if they are actually used.
_redirect_warned: set[str] = set()

_SEARCH_HEADS = frozenset({"grep", "rg", "ag", "ack"})
_READ_HEADS = frozenset({"cat", "head", "tail"})
_FIND_HEADS = frozenset({"find"})
_SQL_HEADS = frozenset(
    {"psql", "mysql", "mariadb", "sqlite3", "pg_dump", "mongosh", "mongo", "redis-cli", "clickhouse-client"}
)
# Classes that escalate warn -> block on repeat. find/sql never block.
_BLOCKING_CLASSES = frozenset({"search", "read"})
_HEAD_SKIP = frozenset({"sudo", "command", "time", "nice", "env", "nohup", "stdbuf"})


def _redirect_block_enabled() -> bool:
    import os

    return os.environ.get("ATELIER_SHELL_REDIRECT_BLOCK", "1").strip().lower() not in {"0", "false", "no"}


def _first_head(norm: str) -> str:
    """First real command word, skipping env assignments and wrapper commands."""
    for token in norm.split():
        if token in _HEAD_SKIP:
            continue
        if "=" in token and not token.startswith(("-", "/")):
            continue  # FOO=bar env assignment
        return token.rsplit("/", 1)[-1]  # /usr/bin/grep -> grep
    return ""


def _is_repo_path(token: str, cwd: str | None) -> bool:
    """Whether an absolute-path *token* falls inside the workspace at *cwd*.

    Relative paths and an unknown *cwd* are assumed in-repo (conservative:
    don't suppress the hint without positive evidence it's out of scope).
    """
    if not cwd:
        return True
    try:
        root = Path(cwd).resolve()
        candidate = Path(token).resolve()
    except OSError:
        return True
    return candidate == root or root in candidate.parents


def _redirect_hint(norm: str, cwd: str | None) -> tuple[str, str, str] | None:
    """Coaching for a leading shell command that duplicates an Atelier tool.

    Returns ``(class, warn_message, block_message)`` or None. Only the *first*
    command word is inspected, so piped output filters like ``ps aux | grep
    node`` are left alone — only a top-level code search/read or database
    command is gated. Also skipped when an argument is an absolute path outside
    the workspace (e.g. ``grep foo /tmp/scratch.html``) — code_search/read only
    cover the workspace, so the redirect would be wrong.
    """
    head = _first_head(norm)
    if head in _SQL_HEADS:
        msg = f"Prefer the `sql` tool over shell `{head}` for database access."
        return ("sql", msg, msg)
    if head not in _SEARCH_HEADS and head not in _READ_HEADS and head not in _FIND_HEADS:
        return None
    try:
        tokens = shlex.split(norm)
    except ValueError:
        tokens = norm.split()
    if any(tok.startswith("/") and not _is_repo_path(tok, cwd) for tok in tokens[1:]):
        return None
    if head in _READ_HEADS:
        # Writes/heredocs (`cat > f`, `cat <<EOF`) and follows (`tail -f`) are
        # not file-content dumps — the `read` tool cannot replace them.
        if ">" in norm or "<<" in norm or "-f" in tokens or "-F" in tokens:
            return None
        return (
            "read",
            f"Use the `read` tool instead of shell `{head}` for file content — "
            "it batches files=[...] and takes exact ranges/head=/tail=.",
            f"shell `{head}` for workspace file content is disabled after coaching: "
            "use the `read` tool (files=[...], :Lx-Ly ranges, head=/tail=).",
        )
    if head in _FIND_HEADS:
        msg = f"Prefer the `code_search` tool over shell `{head}` for locating code."
        return ("find", msg, msg)
    return (
        "search",
        f"Use the `code_search` tool instead of shell `{head}` for code exploration — "
        "one call searches the index and returns grouped source plus the call graph; "
        "use `read` for known paths.",
        f"shell `{head}` over workspace code is disabled after coaching: use the "
        "`code_search` tool (indexed; returns grouped source, callers/callees, and "
        "`candidate_files`) and `read` for known paths. Absolute paths outside the "
        "workspace are exempt.",
    )


def pre_run_gate(command: str, *, cwd: str | None = None) -> GateDecision:
    """Decide whether *command* may run, runs with a warning, or is blocked."""
    norm = _normalize(command)
    if not norm:
        return GateDecision("allow")
    with _lock:
        if _failed.get(norm):
            if norm in _retry_warned:
                return GateDecision(
                    "block",
                    "this exact command already failed twice this session — change the "
                    "approach (different input, scope, or tool) instead of retrying verbatim.",
                )
            _retry_warned.add(norm)
            return GateDecision(
                "warn",
                "this exact command failed earlier this session.",
            )
        if _silences_diagnostics(norm):
            if norm in _silence_warned:
                return GateDecision(
                    "block",
                    "this command still silences stderr (2>/dev/null) — those diagnostics "
                    "are exactly what's needed to debug a failure; rerun without silencing.",
                )
            _silence_warned.add(norm)
            return GateDecision(
                "warn",
                "stderr is being silenced (2>/dev/null) on a diagnostic command — "
                "keep stderr visible so failures stay debuggable.",
            )
        hint = _redirect_hint(norm, cwd)
        if hint is not None:
            cls, warn_msg, block_msg = hint
            if cls not in _redirect_warned:
                _redirect_warned.add(cls)
                return GateDecision("warn", warn_msg)
            if cls in _BLOCKING_CLASSES and _redirect_block_enabled():
                return GateDecision("block", block_msg)
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
