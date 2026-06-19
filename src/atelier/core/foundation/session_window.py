"""Window-anchored session-id resolution.

A long-lived MCP server (one per Claude window) must learn the *live* session
id even after ``/clear`` or ``--resume`` mints a new id under it, and must not
be confused by sibling sessions that share the same workspace directory.

Neither of the two obvious signals is sufficient on its own:

* ``CLAUDE_CODE_SESSION_ID`` is set per MCP process at launch, so it is correct
  for concurrent windows -- but it is *frozen at launch* and goes stale the
  moment the user runs ``/clear`` (the MCP server outlives the session id).
* ``workspaces/<hash>/session_state.json`` is rewritten by SessionStart on every
  ``/clear`` so it always names the live session -- but it is a single shared
  slot, so concurrent windows in one workspace clobber each other's value.

This module anchors resolution to the **window process**: the ``claude``
process that is the common ancestor of both the MCP server and the hook
processes. That pid is stable across ``/clear`` (the window is the same) and
unique per window (siblings have different ``claude`` pids). SessionStart
appends a row keyed by ``(window_pid, window_btime)``; the MCP server resolves
its live id by matching its own window. Both sides run on atelier's venv python
(hooks via ``_run_hook.sh``), so this one module serves both.

Linux/proc only. On platforms without ``/proc`` (or when no ``claude`` ancestor
is found) :func:`host_window_id` returns ``None`` and callers fall back to the
env var, preserving today's behavior.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Process names that own a long-lived MCP server + the session lifecycle. Only
# Claude exhibits the launch-env-goes-stale-on-/clear problem today; other hosts
# set a per-session env var the callers read directly.
_HOST_PROCESS_NAMES = frozenset({"claude"})

# Keep the append-only registry bounded: SessionStart fires a handful of times
# per session (startup/resume/clear/compact), but a workspace accumulates rows
# across days. Trim to the most recent N on write so resolution stays O(N).
_MAX_REGISTRY_ROWS = 200


def _read_proc_stat(pid: int) -> tuple[int, int, str] | None:
    """Return ``(ppid, starttime_ticks, comm)`` for *pid*, or ``None``.

    Parses ``/proc/<pid>/stat``. ``comm`` (field 2) can contain spaces and
    parentheses, so split on the last ``)`` before reading the numeric fields.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    rparen = data.rfind(b")")
    lparen = data.find(b"(")
    if rparen < 0 or lparen < 0 or rparen < lparen:
        return None
    comm = data[lparen + 1 : rparen].decode("utf-8", "replace")
    fields = data[rparen + 2 :].split()
    # After '(comm)' the fields are 1-indexed in proc(5); fields[0] is 'state'
    # (field 3), so ppid (field 4) is fields[1] and starttime (field 22) is
    # fields[19].
    try:
        ppid = int(fields[1])
        starttime = int(fields[19])
    except (IndexError, ValueError):
        return None
    return ppid, starttime, comm


def _argv0_basename(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            first = fh.read().split(b"\x00", 1)[0]
    except OSError:
        return ""
    return os.path.basename(first.decode("utf-8", "replace"))


def host_window_id(start_pid: int | None = None) -> tuple[int, int] | None:
    """Return ``(pid, starttime)`` of the nearest ``claude`` ancestor, or ``None``.

    Walks the process-parent chain from *start_pid* (default: this process).
    ``starttime`` (proc start ticks) is included so callers can guard against
    PID reuse: a recycled pid will have a different start time. Returns ``None``
    on non-Linux, on any ``/proc`` read error, or when no ``claude`` ancestor
    exists -- callers then fall back to env-based resolution.
    """
    pid = start_pid if start_pid is not None else os.getpid()
    seen: set[int] = set()
    while pid and pid > 1 and pid not in seen:
        seen.add(pid)
        st = _read_proc_stat(pid)
        if st is None:
            return None
        ppid, starttime, comm = st
        if comm in _HOST_PROCESS_NAMES or _argv0_basename(pid) in _HOST_PROCESS_NAMES:
            return pid, starttime
        pid = ppid
    return None


def workspace_hash(workspace: str | os.PathLike[str]) -> str:
    """12-hex workspace key, matching the SessionStart hook + MCP server."""
    return hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]


def registry_path(root: str | os.PathLike[str], ws_hash: str) -> Path:
    return Path(root) / "workspaces" / ws_hash / "sessions.jsonl"


def _read_registry(root: str | os.PathLike[str], ws_hash: str) -> list[dict[str, Any]]:
    path = registry_path(root, ws_hash)
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return []
    return rows


def register_window_session(
    root: str | os.PathLike[str],
    ws_hash: str,
    *,
    session_id: str,
    source: str = "",
    transcript_path: str = "",
    model: str = "",
) -> None:
    """Append a window-keyed session row. Called by the SessionStart hook.

    The row records the live ``session_id`` together with this window's
    ``(window_pid, window_btime)`` so the MCP server -- whose launch env id may
    be stale -- can recover the live id by matching its own window. Best-effort:
    failures never raise (the hook is fail-open).
    """
    session_id = (session_id or "").strip()
    if not session_id:
        return
    win = host_window_id()
    row = {
        "session_id": session_id,
        "source": source,
        "transcript_path": transcript_path,
        "model": model,
        "ts": time.time(),
        "window_pid": win[0] if win else 0,
        "window_btime": win[1] if win else 0,
    }
    path = registry_path(root, ws_hash)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = _read_registry(root, ws_hash)
        rows.append(row)
        if len(rows) > _MAX_REGISTRY_ROWS:
            rows = rows[-_MAX_REGISTRY_ROWS:]
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        tmp.replace(path)
    except OSError:
        _log.debug("window-session registry write failed", exc_info=True)


def resolve_window_session_id(
    root: str | os.PathLike[str],
    ws_hash: str,
    *,
    env_session_id: str = "",
) -> str:
    """Resolve the live session id for *this* process's window.

    Priority:
      1. Newest registry row whose ``(window_pid, window_btime)`` matches this
         process's ``claude`` ancestor -- correct across ``/clear`` and immune
         to sibling windows sharing the workspace.
      2. ``env_session_id`` (the launch env var) -- correct before SessionStart
         has written a row, and the only signal on non-Linux hosts.
      3. Newest registry row of any window (MRU) -- last-ditch for hostless
         callers.
      4. ``""`` when nothing is known.
    """
    rows = _read_registry(root, ws_hash)
    win = host_window_id()
    if win is not None:
        pid, btime = win
        match: str = ""
        for r in rows:  # append order; last match wins (newest for this window)
            if int(r.get("window_pid") or 0) == pid and int(r.get("window_btime") or 0) == btime:
                sid = str(r.get("session_id") or "").strip()
                if sid:
                    match = sid
        if match:
            return match
    env = (env_session_id or "").strip()
    if env:
        return env
    for r in reversed(rows):
        sid = str(r.get("session_id") or "").strip()
        if sid:
            return sid
    return ""
