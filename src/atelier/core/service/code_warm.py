"""Daemon-owned code-index warmer.

Keeps the shared code-context SQLite index warm for every active MCP
workspace so the per-request MCP path never has to trigger a synchronous
cold build. The service daemon owns this; it scans the ``mcp_sessions``
registry, constructs (and retains) a :class:`CodeContextEngine` per active
workspace, and lets each engine's own autosync thread do the warming.

Gated by ``ATELIER_SERVICE_CODE_WARM`` (default on). Set to one of
``0``/``false``/``no``/``off`` to disable.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from atelier.core.foundation.paths import default_store_root

logger = logging.getLogger(__name__)

_POLL_SECONDS = 15.0
_DISABLED_VALUES = {"0", "false", "no", "off"}


def _warm_enabled() -> bool:
    raw = os.getenv("ATELIER_SERVICE_CODE_WARM", "1").strip().lower()
    return raw not in _DISABLED_VALUES


def _mcp_sessions_dir() -> Path:
    return default_store_root() / "mcp_sessions"


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _registered_mcp_pid_is_live(pid: int) -> bool:
    if not _pid_is_running(pid):
        return False
    cmdline = Path(f"/proc/{pid}/cmdline")
    if not cmdline.exists():
        return True
    try:
        parts = [part for part in cmdline.read_bytes().split(b"\0") if part]
    except OSError:
        return False
    text = " ".join(part.decode("utf-8", errors="ignore") for part in parts)
    return "atelier" in text and "mcp" in text


def discover_workspaces() -> list[Path]:
    """Return resolved workspace dirs from the mcp_sessions registry.

    Only existing directories from live MCP processes are returned. Discovery is
    limited to the registry -- the service cwd is intentionally never auto-added
    so that a daemon with no active MCP sessions warms nothing.
    """
    sessions_dir = _mcp_sessions_dir()
    if not sessions_dir.is_dir():
        return []
    seen: set[Path] = set()
    workspaces: list[Path] = []
    for entry in sorted(sessions_dir.glob("*.json")):
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.debug("skipping unreadable mcp session file: %s", entry, exc_info=True)
            continue
        pid = data.get("pid") if isinstance(data, dict) else None
        if not isinstance(pid, int) or not _registered_mcp_pid_is_live(pid):
            try:
                entry.unlink()
            except OSError:
                logger.debug("failed to prune dead mcp session file: %s", entry, exc_info=True)
            continue
        ws = data.get("workspace") if isinstance(data, dict) else None
        if not isinstance(ws, str) or not ws.strip():
            continue
        try:
            resolved = Path(ws).expanduser().resolve()
        except OSError:
            continue
        if not resolved.is_dir():
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        workspaces.append(resolved)
    return workspaces


class _CodeWarmer:
    """Background loop that retains a warm engine per active workspace."""

    def __init__(self, *, poll_seconds: float = _POLL_SECONDS) -> None:
        self._poll_seconds = poll_seconds
        self._engines: dict[Path, object] = {}
        self._stop = threading.Event()
        # NB: not named ``_thread`` -- mypyc emits that as a C struct field
        # ``__thread``, which clang rejects as the reserved TLS keyword.
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(
            target=self._loop,
            name="atelier-code-warmer",
            daemon=True,
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()

    def _warm_once(self) -> None:
        from atelier.core.capabilities import licensing

        workspaces = discover_workspaces()
        if not licensing.feature_active("unlimited_repos"):
            # Free warms a single repository; Pro warms all active workspaces.
            workspaces = workspaces[:1]
        for workspace in workspaces:
            if workspace in self._engines:
                continue
            try:
                # Imported lazily to keep service startup cheap and avoid a
                # hard import cycle on the heavy code-intel engine.
                from atelier.core.capabilities.code_context.engine import CodeContextEngine

                engine = CodeContextEngine(workspace)
                # Retain the ref so the engine's autosync thread keeps warming
                # the shared SQLite index for the lifetime of the daemon.
                self._engines[workspace] = engine
                logger.info("code warmer: warming workspace %s", workspace)
            except Exception:
                logger.exception("code warmer: failed to warm workspace %s", workspace)

    def _loop(self) -> None:
        # First pass immediately, then poll for newly registered sessions.
        try:
            self._warm_once()
        except Exception:
            logger.exception("code warmer: warm pass failed")
        while not self._stop.wait(self._poll_seconds):
            try:
                self._warm_once()
            except Exception:
                logger.exception("code warmer: warm pass failed")


# --- stdio MCP single-workspace warmer (Workstream 6 / G10) ----------------
#
# The SERVICE path warms every active workspace via ``_CodeWarmer`` above. The
# stdio MCP server (``mcp_server.serve``) instead owns exactly one workspace and
# is not warmed, so it pays cold-start on Zoekt/ast-grep subprocesses at
# the first code-context tool call. ``warm_stdio_workspace`` warms that single
# workspace once on startup, reusing the same lazy-engine-construct + retain
# pattern as ``_CodeWarmer._warm_once``. It is idempotent and fail-open.

_stdio_engine: object | None = None
_stdio_warmed: Path | None = None
_stdio_lock = threading.Lock()


def warm_stdio_workspace(workspace: str | Path) -> bool:
    """Warm the code-context engine for a single stdio workspace (idempotent).

    Returns ``True`` when an engine was constructed and retained, ``False`` when
    warming was skipped (disabled, missing dir, already warm) or failed. Never
    raises -- stdio server startup must not break if warming fails.
    """
    global _stdio_engine, _stdio_warmed
    if not _warm_enabled():
        logger.info("stdio code warmer disabled via ATELIER_SERVICE_CODE_WARM")
        return False
    try:
        resolved = Path(workspace).expanduser().resolve()
    except OSError:
        logger.exception("stdio code warmer: cannot resolve workspace %s", workspace)
        return False
    if not resolved.is_dir():
        logger.debug("stdio code warmer: workspace is not a directory: %s", resolved)
        return False
    with _stdio_lock:
        if _stdio_warmed == resolved:
            return False
        try:
            # Lazy import keeps stdio startup cheap and avoids a hard import
            # cycle on the heavy code-intel engine.
            from atelier.core.capabilities.code_context.engine import CodeContextEngine

            engine = CodeContextEngine(resolved)
            # Retain the ref so the engine's autosync thread keeps the shared
            # SQLite index warm for the lifetime of the stdio process.
            _stdio_engine = engine
            _stdio_warmed = resolved
            logger.info("stdio code warmer: warmed workspace %s", resolved)
            return True
        except Exception:
            logger.exception("stdio code warmer: failed to warm workspace %s", resolved)
            return False


_warmer: _CodeWarmer | None = None
_warmer_lock = threading.Lock()


def start_code_warmer() -> _CodeWarmer | None:
    """Start the daemon code-index warmer (idempotent).

    Returns ``None`` when disabled via ``ATELIER_SERVICE_CODE_WARM``; otherwise
    returns the singleton warmer (already started).
    """
    global _warmer
    if not _warm_enabled():
        logger.info("code warmer disabled via ATELIER_SERVICE_CODE_WARM")
        return None
    with _warmer_lock:
        if _warmer is None:
            _warmer = _CodeWarmer()
            _warmer.start()
            logger.info("code warmer started")
        return _warmer
