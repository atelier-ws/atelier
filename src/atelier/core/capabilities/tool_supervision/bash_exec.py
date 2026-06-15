"""Shell command execution with token-aware output compaction."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from atelier.core.capabilities.tool_supervision import command_discipline
from atelier.core.foundation.redaction import redact_tool_output

_ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_SEARCH_REGEX_METACHARS = re.compile(r"[][{}()|^$*+?\\]")
# Shell file-write patterns: cat > file or cat >> file (write redirect)
_SHELL_FILE_WRITE_RE = re.compile(r"\bcat\s+>>?", re.IGNORECASE)
# Inline interpreter writes: python -c / heredoc scripts that write workspace
# files (open(...,'w'), .write_text(...)) — same edit-tool bypass as cat >.
_INTERP_WRITE_RE = re.compile(
    r"""\bpython[0-9.]*\b.*(?:
        open\([^)]*,\s*['"][wax]b?\+?['"]   # open(path, 'w'/'a'/'x')
        | \.write_text\(
        | \.write_bytes\(
    )""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
# A shell short-option cluster requesting no-exec parse mode (``-n``, ``-nx``).
# Among bash/sh/zsh/fish single-char invocation options only ``-n`` contains an
# 'n', so a single-dash cluster containing 'n' implies syntax-check-only.
_SHELL_NOEXEC_SHORT_RE = re.compile(r"^-[a-zA-Z]*n[a-zA-Z]*$")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


# Hard ceiling on how many bytes of stdout/stderr are materialized into memory
# from a single command. A runaway child (`cat /dev/zero`, `yes`, `gzip -dc`,
# a chatty build) would otherwise fill the temp file to disk and OOM on a full
# `.read()`. `max_lines` truncation only runs *after* materialization, so the
# cap must happen at read time. Configurable via env, with a 64KiB floor so it
# can never be set so low that ordinary output is mangled.
_MAX_OUTPUT_BYTES = max(
    64 * 1024,
    int(os.environ.get("ATELIER_SHELL_MAX_OUTPUT_BYTES", str(4 * 1024 * 1024))),
)

# On-disk ceiling for a managed command's temp spool. `subprocess.Popen` writes
# the child's output straight to the temp file's fd, so the read-time
# `_MAX_OUTPUT_BYTES` cap cannot bound it -- `cat /dev/zero` would fill the disk
# before any poll runs. The spool pump (`_pump_capped`) stops appending once
# this ceiling is reached. Defaults to the output cap (read side then catches
# every truncated spool); a larger value retains more for later inspection.
_MAX_SPOOL_BYTES = max(
    _MAX_OUTPUT_BYTES,
    int(os.environ.get("ATELIER_SHELL_MAX_SPOOL_BYTES", str(_MAX_OUTPUT_BYTES))),
)

# Read granularity for `_pump_capped`; large enough to keep the drain loop cheap
# without buffering an unbounded amount per iteration.
_PUMP_CHUNK_CHARS = 64 * 1024


def _cap_text(text: str) -> tuple[str, bool]:
    """Bound *text* to the output-byte ceiling, returning (text, truncated).

    Truncation is measured in UTF-8 bytes to mirror on-disk size; the returned
    string is cut on a character boundary at or just under the cap.
    """
    encoded = text.encode("utf-8", "replace")
    if len(encoded) <= _MAX_OUTPUT_BYTES:
        return text, False
    capped = encoded[:_MAX_OUTPUT_BYTES].decode("utf-8", "ignore")
    return capped, True


def _read_capped(handle: Any) -> tuple[str, bool]:
    """Read at most the output-byte ceiling from a seeked temp-file *handle*.

    Reads one character past the cap to detect a larger file without slurping
    it whole, so memory stays bounded regardless of on-disk size. Returns
    (text, truncated).
    """
    chunk = handle.read(_MAX_OUTPUT_BYTES + 1)
    if len(chunk) <= _MAX_OUTPUT_BYTES:
        return chunk, False
    return chunk[:_MAX_OUTPUT_BYTES], True


def _pump_capped(src: Any, write: Callable[[str], Any], cap: int) -> bool:
    """Copy text from *src* into *write*, appending at most *cap* UTF-8 bytes.

    Reads in fixed chunks until EOF. Once the running byte count reaches *cap*
    the overflow is read and discarded rather than written, so the source pipe
    keeps draining (no deadlock when both stdout and stderr are large) while the
    in-memory or on-disk sink stays bounded. Byte accounting mirrors `_cap_text`,
    cutting a straddling chunk on a character boundary at or just under the cap.
    Returns True if the stream exceeded the cap.
    """
    written = 0
    truncated = False
    while True:
        chunk = src.read(_PUMP_CHUNK_CHARS)
        if not chunk:
            break
        if written >= cap:
            truncated = True
            continue
        encoded = chunk.encode("utf-8", "replace")
        if written + len(encoded) <= cap:
            write(chunk)
            written += len(encoded)
            continue
        prefix = encoded[: cap - written].decode("utf-8", "ignore")
        if prefix:
            write(prefix)
        written = cap
        truncated = True
    return truncated


_OUTPUT_CAP_NOTICE = (
    "\n... (output exceeded {cap} bytes and was truncated by Atelier; narrow the command or redirect to a file) ..."
)


def _head_tail_lines(lines: list[str], head: int, tail: int) -> tuple[str, int, int]:
    if len(lines) <= head + tail:
        return "\n".join(lines), 0, 0
    omitted_lines = lines[head : len(lines) - tail]
    omitted = len(omitted_lines)
    omitted_chars = sum(len(line) for line in omitted_lines)
    parts = [*lines[:head], f"... ({omitted} lines omitted) ...", *lines[-tail:]]
    return "\n".join(parts), omitted, omitted_chars


@dataclass
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    truncated: bool
    lines_omitted: int
    command: str
    chars_omitted: int = 0
    policy_category: str = "generic"
    policy_action: str = "allow"
    policy_reason: str = ""
    rewrite_target: str | None = None
    rewrite_payload: dict[str, Any] | None = None
    discipline: str = ""


@dataclass(frozen=True)
class CommandPolicyDecision:
    category: str
    action: str
    reason: str = ""
    rewrite_target: str | None = None
    rewrite_payload: dict[str, Any] | None = None


@dataclass
class _ManagedCommand:
    command: str
    proc: subprocess.Popen[str]
    stdout_file: Any
    stderr_file: Any
    started: float
    timeout: int
    max_lines: int
    state: str = "running"
    discipline_warning: str = ""
    reaped: bool = False
    # Drain threads spooling the child's piped output into the temp files, and a
    # flag set when either spool hit the on-disk ceiling. Joining the threads
    # before a read guarantees all surviving bytes are flushed to disk.
    readers: list[threading.Thread] = field(default_factory=list)
    spool_truncated: bool = False


_MANAGED_COMMANDS: dict[str, _ManagedCommand] = {}
_MANAGED_COMMANDS_LOCK = threading.Lock()
# Grace period before the watcher reaps a finished-but-never-polled session,
# so a poll that arrives just after completion still finds its output.
_DETACHED_REAP_GRACE_S = 300.0


def _rewrite_cat(tokens: list[str]) -> CommandPolicyDecision:
    if len(tokens) != 2:
        return CommandPolicyDecision(category="file-read", action="allow")
    return CommandPolicyDecision(
        category="file-read",
        action="rewrite",
        reason="Use Atelier read for file content access",
        rewrite_target="read",
        rewrite_payload={"file_path": tokens[1]},
    )


def _rewrite_search(tokens: list[str], command_name: str) -> CommandPolicyDecision:
    ignore_case = False
    file_type: str | None = None
    cleaned: list[str] = []
    seen_double_dash = False
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--":
            seen_double_dash = True
            i += 1
            continue
        if tok.startswith("-") and not seen_double_dash:
            # Handle --type=python or --type python or -t python
            if tok.startswith("--type="):
                file_type = tok.split("=", 1)[1]
            elif tok in {"--type", "-t"} and i + 1 < len(tokens):
                i += 1
                file_type = tokens[i]
            elif "i" in tok and tok != "-":
                ignore_case = True
            i += 1
            continue
        cleaned.append(tok)
        i += 1

    if not cleaned:
        return CommandPolicyDecision(category="search", action="allow")

    pattern = cleaned[0]
    path = cleaned[1] if len(cleaned) > 1 else "."
    if (
        command_name == "rg"
        and not ignore_case
        and file_type is None
        and len(cleaned) <= 2
        and not _SEARCH_REGEX_METACHARS.search(pattern)
    ):
        return CommandPolicyDecision(
            category="search",
            action="rewrite",
            reason="Use Atelier search for search-first grounding",
            rewrite_target="search",
            rewrite_payload={"query": pattern, "path": path},
        )
    payload: dict[str, Any] = {
        "file_path": path,
        "content_regex": pattern,
        "ignore_case": ignore_case,
        "output_mode": "file_paths_with_content",
    }
    if file_type:
        payload["type"] = file_type
    return CommandPolicyDecision(
        category="search",
        action="rewrite",
        reason=f"Use Atelier grep for {command_name} pattern search",
        rewrite_target="grep",
        rewrite_payload=payload,
    )


def _is_rm_family(tokens: list[str]) -> bool:
    if not tokens or tokens[0] != "rm":
        return False
    recursive = force = False
    for tok in tokens[1:]:
        if not tok.startswith("-"):
            continue
        if tok.startswith("--"):
            if tok == "--recursive":
                recursive = True
            elif tok == "--force":
                force = True
            continue
        # Short flags may be bundled (-rf) or split (-r -f).
        if "r" in tok or "R" in tok:
            recursive = True
        if "f" in tok:
            force = True
    return recursive and force


def _git_subcommand_index(tokens: list[str]) -> int:
    """Index of the git subcommand, skipping leading global options.

    ``git -C <dir> reset --hard`` and ``git --git-dir=x clean -fd`` place the
    subcommand after global options, so a hardcoded ``tokens[1]`` misses it.
    """
    _takes_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        tok = tokens[i]
        # ``--git-dir=x`` carries its value inline; bare forms consume the next token.
        if tok in _takes_value and "=" not in tok:
            i += 2
        else:
            i += 1
    return i


def _is_git_reset_hard(tokens: list[str]) -> bool:
    if not tokens or tokens[0] != "git":
        return False
    idx = _git_subcommand_index(tokens)
    return idx < len(tokens) and tokens[idx] == "reset" and "--hard" in tokens[idx + 1 :]


def _is_git_clean_fd(tokens: list[str]) -> bool:
    if not tokens or tokens[0] != "git":
        return False
    idx = _git_subcommand_index(tokens)
    if idx >= len(tokens) or tokens[idx] != "clean":
        return False
    joined_flags = "".join(tok for tok in tokens[idx + 1 :] if tok.startswith("-"))
    return "f" in joined_flags and "d" in joined_flags


def _is_shell_file_write(command: str) -> bool:
    """Return True for shell file-write patterns that should use the edit tool instead.

    Catches ``cat > file``, ``cat >> file``, and inline interpreter writes
    (``python -c "...open(f,'w').write(...)"`` or python heredocs) before
    shlex.split, which chokes on heredoc syntax.
    """
    return bool(_SHELL_FILE_WRITE_RE.search(command)) or bool(_INTERP_WRITE_RE.search(command))


def _split_command_segments(command: str) -> list[list[str]]:
    """Split a command line into segments on shell control operators.

    ``bash -c`` runs the whole line, so blocklist checks that only inspect
    ``tokens[0]`` are bypassed by chaining (``ok && rm -rf x``) or command
    substitution (``$(rm -rf x)``). Tokenizing the full line and breaking on
    ``; & | && ||``, newlines, and substitution/brace markers yields each
    segment's own leading token for the blocklist checks.
    """
    operators = {";", "&", "|", "&&", "||", "\n", "$(", ")", "`", "{", "}"}
    # Pad control operators and substitution/brace boundaries with whitespace so
    # shlex isolates them even when glued to a token (``a&&rm``, ``true;rm``) and
    # the command inside ``$(...)`` / ``\`...\``` starts a fresh segment.
    # Over-splitting inside a quoted literal only yields extra benign segments;
    # it can never mask a dangerous leading token.
    normalized = re.sub(r"(\$\(|\)|`|\{|\}|&&|\|\||;|&|\||\n)", r" \1 ", command)
    try:
        tokens = shlex.split(normalized, comments=False)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in operators:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(tok)
    if current:
        segments.append(current)
    return segments


def _is_noexec_shell(tokens: list[str]) -> bool:
    """True if a shell interpreter is invoked purely to syntax-check, not run.

    ``bash -n file`` / ``sh -n`` parse the script and exit without executing any
    command, so unlike ``bash -c '...'`` they cannot smuggle a destructive
    command past the per-segment blocklist. Detects ``-n`` standalone or bundled
    (``-nx``) and the ``-o noexec`` long form. Scans options only up to the first
    non-option token (the script path), so ``bash script.sh -n`` — where ``-n``
    belongs to the script, not the shell — is correctly NOT treated as no-exec.
    """
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("-") or tok == "--":
            break
        if tok == "-o":
            if i + 1 < len(tokens) and tokens[i + 1] == "noexec":
                return True
            i += 2
            continue
        if not tok.startswith("--") and _SHELL_NOEXEC_SHORT_RE.match(tok):
            return True
        i += 1
    return False


def _block_check_segment(tokens: list[str]) -> CommandPolicyDecision | None:
    """Return a block decision if *tokens* (one segment) is dangerous, else None."""
    if not tokens:
        return None
    head = tokens[0].lower()
    if head in {"bash", "sh", "zsh", "fish"}:
        if _is_noexec_shell(tokens):
            return None  # `bash -n` / `-o noexec`: parse-only, runs nothing
        return CommandPolicyDecision(
            category="shell-interpreter",
            action="block",
            reason=(
                f"Direct {head} execution is blocked; use Atelier tools instead "
                f"(non-executing syntax checks like `{head} -n` are allowed)"
            ),
        )
    if _is_rm_family(tokens):
        return CommandPolicyDecision(
            category="destructive",
            action="block",
            reason="Destructive rm -rf commands are blocked",
        )
    if _is_git_reset_hard(tokens):
        return CommandPolicyDecision(
            category="destructive",
            action="block",
            reason="git reset --hard is blocked",
        )
    if _is_git_clean_fd(tokens):
        return CommandPolicyDecision(
            category="destructive",
            action="block",
            reason="git clean -fd is blocked",
        )
    return None


def classify_command(command: str) -> CommandPolicyDecision:
    # Detect file-write patterns before shlex.split (heredocs break shlex parsing).
    if _is_shell_file_write(command):
        return CommandPolicyDecision(
            category="file-write",
            action="block",
            reason=(
                "Use the edit tool to create or modify files — shell redirects, "
                "heredocs, and inline interpreter writes are blocked for file content"
            ),
        )
    # Block checks run per segment: bash -c executes the whole line, so chaining
    # and command substitution must not slip a dangerous segment past tokens[0].
    for segment in _split_command_segments(command):
        blocked = _block_check_segment(segment)
        if blocked is not None:
            return blocked

    try:
        tokens = shlex.split(command)
    except ValueError:
        return CommandPolicyDecision(category="generic", action="allow")
    if not tokens:
        return CommandPolicyDecision(category="generic", action="allow")

    head = tokens[0].lower()
    if head == "cat":
        return _rewrite_cat(tokens)
    if head in {"rg", "grep"}:
        return _rewrite_search(tokens, head)
    return CommandPolicyDecision(category="generic", action="allow")


def _terminate_process_group(proc: subprocess.Popen[str]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def _compact_result(
    *,
    command: str,
    raw_stdout: str,
    raw_stderr: str,
    exit_code: int,
    duration_ms: int,
    max_lines: int,
) -> RunResult:
    if exit_code != 0:
        head = 20
        tail = max(max_lines - head, 50)
    else:
        head = max(20, max_lines // 4)
        tail = max(max_lines - head, 0)
    stdout_compact, stdout_omitted, stdout_chars = _head_tail_lines(_strip_ansi(raw_stdout).splitlines(), head, tail)
    stderr_compact, stderr_omitted, stderr_chars = _head_tail_lines(_strip_ansi(raw_stderr).splitlines(), 100, 100)
    lines_omitted = stdout_omitted + stderr_omitted
    chars_omitted = stdout_chars + stderr_chars
    # Live tool-output redaction (G8): scrub secrets from command output
    # before it reaches the model. Honors the ATELIER_OUTPUT_REDACTION
    # kill-switch and is a no-op on already-clean text.
    return RunResult(
        stdout=redact_tool_output(stdout_compact),
        stderr=redact_tool_output(stderr_compact),
        exit_code=exit_code,
        duration_ms=duration_ms,
        truncated=lines_omitted > 0,
        lines_omitted=lines_omitted,
        chars_omitted=chars_omitted,
        command=command,
    )


def _watch_managed_command(session_id: str) -> None:
    with _MANAGED_COMMANDS_LOCK:
        managed = _MANAGED_COMMANDS.get(session_id)
    if managed is None:
        return
    try:
        managed.proc.wait(timeout=managed.timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_group(managed.proc)
        with _MANAGED_COMMANDS_LOCK:
            if managed.state == "running":
                managed.state = "timed_out"
    else:
        with _MANAGED_COMMANDS_LOCK:
            if managed.state == "running":
                managed.state = "completed"

    # The process has finished. If no one polls the result, its temp files and
    # dict entry would leak forever, so reap it after a grace window. A poll that
    # arrives first reaps it under the lock and clears the entry; this then no-ops.
    time.sleep(_DETACHED_REAP_GRACE_S)
    with _MANAGED_COMMANDS_LOCK:
        if _MANAGED_COMMANDS.get(session_id) is not managed or managed.reaped:
            return
        managed.reaped = True
        _MANAGED_COMMANDS.pop(session_id, None)
    # Let the spool drains finish before closing their temp files; the process
    # has already exited, so the pipes are at EOF and the joins return at once.
    for reader in managed.readers:
        reader.join()
    with contextlib.suppress(Exception):
        managed.stdout_file.close()
    with contextlib.suppress(Exception):
        managed.stderr_file.close()


def _spool_managed_stream(stream: Any, dst_file: Any, managed: _ManagedCommand) -> None:
    """Drain *stream* into *dst_file*, capped at the on-disk spool ceiling.

    Runs for the command's lifetime in a daemon thread; `_pump_capped` stops
    appending once `_MAX_SPOOL_BYTES` is reached but keeps reading to EOF so the
    child never blocks on a full pipe. Flags the session as spool-truncated when
    either stream overflows.
    """
    with contextlib.suppress(Exception):
        truncated = _pump_capped(stream, dst_file.write, _MAX_SPOOL_BYTES)
        if truncated:
            with _MANAGED_COMMANDS_LOCK:
                managed.spool_truncated = True


def start_managed_command(
    command: str,
    *,
    cwd: str | None = None,
    timeout: int = 30,
    max_lines: int = 200,
) -> dict[str, Any]:
    """Start a command without blocking the MCP request."""
    policy = classify_command(command)
    if policy.action == "block":
        return {
            "status": "blocked",
            "stderr": policy.reason,
            "exit_code": -1,
            "blocked": True,
            "blocked_reason": policy.reason,
        }

    gate = command_discipline.pre_run_gate(command)
    if gate.action == "block":
        return {
            "status": "blocked",
            "stderr": gate.reason,
            "exit_code": -1,
            "blocked": True,
            "blocked_reason": gate.reason,
        }

    stdout_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    try:
        # Pipe the child's output through drain threads rather than handing the
        # temp-file fds straight to the kernel. A direct fd lets a runaway
        # producer (`cat /dev/zero`) fill the disk before any poll reads it; the
        # spool pump caps each temp file at `_MAX_SPOOL_BYTES` instead.
        proc = subprocess.Popen(
            ["bash", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            start_new_session=True,
        )
    except Exception:
        stdout_file.close()
        stderr_file.close()
        raise

    session_id = uuid.uuid4().hex
    managed = _ManagedCommand(
        command=command,
        proc=proc,
        stdout_file=stdout_file,
        stderr_file=stderr_file,
        started=time.perf_counter(),
        timeout=timeout,
        max_lines=max_lines,
        discipline_warning=gate.reason if gate.action == "warn" else "",
    )
    managed.readers = [
        threading.Thread(target=_spool_managed_stream, args=(proc.stdout, stdout_file, managed), daemon=True),
        threading.Thread(target=_spool_managed_stream, args=(proc.stderr, stderr_file, managed), daemon=True),
    ]
    for reader in managed.readers:
        reader.start()
    with _MANAGED_COMMANDS_LOCK:
        _MANAGED_COMMANDS[session_id] = managed
    threading.Thread(
        target=_watch_managed_command,
        args=(session_id,),
        daemon=True,
        name=f"atelier-shell-{session_id[:8]}",
    ).start()
    started_payload = {
        "status": "running",
        "session_id": session_id,
        "pid": proc.pid,
        "timeout": timeout,
    }
    if managed.discipline_warning:
        started_payload["discipline"] = managed.discipline_warning
    return started_payload


def poll_managed_command(session_id: str, *, cancel: bool = False) -> dict[str, Any]:
    """Poll or cancel a managed command."""
    with _MANAGED_COMMANDS_LOCK:
        managed = _MANAGED_COMMANDS.get(session_id)
        if managed is None:
            raise KeyError(f"unknown shell session: {session_id}")
        if cancel and managed.state == "running":
            managed.state = "cancelled"

    if cancel and managed.proc.poll() is None:
        _terminate_process_group(managed.proc)

    if managed.proc.poll() is None:
        elapsed_ms = int((time.perf_counter() - managed.started) * 1000)
        timeout_remaining_ms = max(0, managed.timeout * 1000 - elapsed_ms)
        return {
            "status": "running",
            "session_id": session_id,
            "pid": managed.proc.pid,
            "duration_ms": elapsed_ms,
            "timeout_remaining_ms": timeout_remaining_ms,
        }

    # Join the spool drains before reading -- the process is done, so the pipes
    # have EOF'd and the threads exit promptly, leaving every surviving byte on
    # disk. Join outside the lock: a drain takes the lock to flag truncation.
    for reader in managed.readers:
        reader.join()

    with _MANAGED_COMMANDS_LOCK:
        if managed.reaped:
            # The watcher already reaped this finished session; its temp files are
            # closed. Report completion without re-reading or double-closing.
            raise KeyError(f"unknown shell session: {session_id}")
        if managed.state == "running":
            managed.state = "completed"
        managed.reaped = True
        _MANAGED_COMMANDS.pop(session_id, None)
        managed.stdout_file.flush()
        managed.stderr_file.flush()
        managed.stdout_file.seek(0)
        managed.stderr_file.seek(0)
        raw_stdout, stdout_capped = _read_capped(managed.stdout_file)
        raw_stderr, stderr_capped = _read_capped(managed.stderr_file)
        managed.stdout_file.close()
        managed.stderr_file.close()
    output_byte_capped = stdout_capped or stderr_capped or managed.spool_truncated
    if stdout_capped:
        raw_stdout += _OUTPUT_CAP_NOTICE.format(cap=_MAX_OUTPUT_BYTES)
    if stderr_capped:
        raw_stderr += _OUTPUT_CAP_NOTICE.format(cap=_MAX_OUTPUT_BYTES)

    if managed.state == "timed_out":
        exit_code = -1
        raw_stderr = f"Command timed out after {managed.timeout}s"
    elif managed.state == "cancelled":
        exit_code = -1
        raw_stderr = "Command cancelled"
    else:
        exit_code = managed.proc.returncode
    if managed.state != "cancelled":
        command_discipline.note_result(
            managed.command,
            exit_code=exit_code,
            timed_out=managed.state == "timed_out",
        )
    result = _compact_result(
        command=managed.command,
        raw_stdout=raw_stdout,
        raw_stderr=raw_stderr,
        exit_code=exit_code,
        duration_ms=int((time.perf_counter() - managed.started) * 1000),
        max_lines=managed.max_lines,
    )
    payload = {
        "status": managed.state,
        "session_id": session_id,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "truncated": result.truncated or output_byte_capped,
        "lines_omitted": result.lines_omitted,
        "chars_omitted": result.chars_omitted,
    }
    if managed.discipline_warning:
        payload["discipline"] = managed.discipline_warning
    return payload


def run_command(
    command: str,
    *,
    cwd: str | None = None,
    timeout: int = 30,
    max_lines: int = 200,
) -> RunResult:
    """Execute *command* in bash, return token-compact structured output.

    Optimizations vs. raw subprocess:
    - ANSI escape codes stripped (progress bars, colors → garbage tokens).
    - stdout truncated head+tail: first 25% for context, last 75% for results/errors.
    - stderr always kept in full (usually short; errors live here).
    - Structured return: LLM checks exit_code first, reads output only if needed.
    """
    policy = classify_command(command)
    if policy.action == "block":
        return RunResult(
            stdout="",
            stderr=policy.reason,
            exit_code=-1,
            duration_ms=0,
            truncated=False,
            lines_omitted=0,
            command=command,
            policy_category=policy.category,
            policy_action=policy.action,
            policy_reason=policy.reason,
            rewrite_target=policy.rewrite_target,
            rewrite_payload=policy.rewrite_payload,
        )

    gate = command_discipline.pre_run_gate(command)
    if gate.action == "block":
        return RunResult(
            stdout="",
            stderr=gate.reason,
            exit_code=-1,
            duration_ms=0,
            truncated=False,
            lines_omitted=0,
            command=command,
            policy_category=policy.category,
            policy_action=policy.action,
            policy_reason=policy.reason,
            rewrite_target=policy.rewrite_target,
            rewrite_payload=policy.rewrite_payload,
        )

    started = time.perf_counter()
    proc: subprocess.Popen[str] | None = None
    output_byte_capped = False
    try:
        proc = subprocess.Popen(
            ["bash", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            start_new_session=True,
        )
        # Drain both pipes concurrently into bounded in-memory buffers. A plain
        # `communicate()` slurps the child's *entire* output into RAM before any
        # cap runs, so a runaway producer (`yes`, `cat /dev/zero`) OOMs the host.
        # `_pump_capped` stops accumulating at `_MAX_OUTPUT_BYTES` per stream but
        # keeps reading to EOF, and running one thread per stream avoids the
        # pipe-buffer deadlock when both stdout and stderr are large.
        stdout_buf: list[str] = []
        stderr_buf: list[str] = []
        capped = {"stdout": False, "stderr": False}

        def _drain(stream: Any, buf: list[str], key: str) -> None:
            with contextlib.suppress(Exception):
                capped[key] = _pump_capped(stream, buf.append, _MAX_OUTPUT_BYTES)

        readers = [
            threading.Thread(target=_drain, args=(proc.stdout, stdout_buf, "stdout"), daemon=True),
            threading.Thread(target=_drain, args=(proc.stderr, stderr_buf, "stderr"), daemon=True),
        ]
        for reader in readers:
            reader.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the group first so the child's pipes close; otherwise the
            # reader joins below would block forever on a still-open pipe.
            _terminate_process_group(proc)
            for reader in readers:
                reader.join()
            raise
        for reader in readers:
            reader.join()
        exit_code = proc.returncode
        raw_stdout = _strip_ansi("".join(stdout_buf))
        raw_stderr = _strip_ansi("".join(stderr_buf))
        stdout_capped = capped["stdout"]
        stderr_capped = capped["stderr"]
        output_byte_capped = stdout_capped or stderr_capped
        if stdout_capped:
            raw_stdout += _OUTPUT_CAP_NOTICE.format(cap=_MAX_OUTPUT_BYTES)
        if stderr_capped:
            raw_stderr += _OUTPUT_CAP_NOTICE.format(cap=_MAX_OUTPUT_BYTES)
    except subprocess.TimeoutExpired:
        exit_code = -1
        raw_stdout = ""
        raw_stderr = f"Command timed out after {timeout}s"
    except Exception as exc:
        logging.exception("Recovered from broad exception handler")
        exit_code = -1
        raw_stdout = ""
        raw_stderr = str(exc)

    duration_ms = int((time.perf_counter() - started) * 1000)

    command_discipline.note_result(
        command,
        exit_code=exit_code,
        timed_out=raw_stderr.startswith("Command timed out after "),
    )

    result = _compact_result(
        command=command,
        raw_stdout=raw_stdout,
        raw_stderr=raw_stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        max_lines=max_lines,
    )
    result.truncated = result.truncated or output_byte_capped
    result.policy_category = policy.category
    result.policy_action = policy.action
    result.policy_reason = policy.reason
    result.rewrite_target = policy.rewrite_target
    result.rewrite_payload = policy.rewrite_payload
    result.discipline = gate.reason if gate.action == "warn" else ""
    return result


__all__ = [
    "CommandPolicyDecision",
    "RunResult",
    "classify_command",
    "poll_managed_command",
    "run_command",
    "start_managed_command",
]
