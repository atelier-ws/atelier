"""Phase 2 deferred-foreground-bash tests.

A foreground bash command frees the MCP pool worker immediately (the handler
returns a deferred marker) and lets bash_exec's watcher run the finalization
pipeline and write the JSON-RPC response when the command completes. These tests
are hermetic: they monkeypatch ``_write_jsonrpc`` to capture responses and never
touch real stdout.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import atelier.core.capabilities.tool_supervision.bash_exec as bx
from atelier.gateway.adapters import mcp_server
from tests.helpers import init_store_at


def _wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _bash_request(rid: Any, command: str, **args: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "method": "tools/call",
        "params": {"name": "bash", "arguments": {"command": command, **args}},
    }


@pytest.fixture()
def bash_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    init_store_at(str(root))
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("ATELIER_MEMORY_BACKEND", "sqlite")
    monkeypatch.delenv("ATELIER_SERVICE_URL", raising=False)
    # Default: deferral enabled (do not let an ambient value leak in).
    monkeypatch.delenv("ATELIER_MCP_DEFER_BASH", raising=False)
    mcp_server._current_ledger = None
    mcp_server._realtime_ctx = None
    return tmp_path


# --------------------------------------------------------------------------- #
# 1. register_completion (bash_exec)                                          #
# --------------------------------------------------------------------------- #


def test_register_completion_running_fires_with_terminal_result() -> None:
    started = bx.start_managed_command("sleep 0.2; echo done", timeout=10)
    sid = str(started["session_id"])

    captured: dict[str, Any] = {}
    fired = threading.Event()

    def cb() -> None:
        captured["result"] = bx.poll_managed_command(sid)
        fired.set()

    assert bx.register_completion(sid, cb) is True
    assert fired.wait(5.0)
    assert captured["result"]["exit_code"] == 0
    assert captured["result"]["stdout"] == "done"


def test_register_completion_false_for_unknown_session() -> None:
    assert bx.register_completion("does-not-exist", lambda: None) is False


def test_register_completion_false_for_finished_session() -> None:
    started = bx.start_managed_command("echo hi", timeout=10)
    sid = str(started["session_id"])

    # The watcher keeps the finished session for a 300s grace window, so it is
    # finished-but-not-reaped here. register_completion must still refuse to arm.
    def _finished() -> bool:
        with bx._MANAGED_COMMANDS_LOCK:
            m = bx._MANAGED_COMMANDS.get(sid)
        return m is None or m.proc.poll() is not None

    assert _wait_for(_finished, 5.0)
    assert bx.register_completion(sid, lambda: None) is False


# --------------------------------------------------------------------------- #
# 2. Deferred end-to-end via _handle_and_write                                #
# --------------------------------------------------------------------------- #


def test_deferred_response_written_by_watcher_continuation(bash_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    lock = threading.Lock()

    def _capture(msg: dict[str, Any]) -> None:
        with lock:
            captured.append(msg)

    monkeypatch.setattr(mcp_server, "_write_jsonrpc", _capture)

    # A still-running command at register time -> the watcher continuation (not the
    # worker) writes the response after the command finishes.
    mcp_server._handle_and_write(_bash_request(42, "sleep 0.3; echo hi", timeout=30))

    # Nothing written synchronously: the worker handed control back deferred.
    with lock:
        assert captured == []

    assert _wait_for(lambda: len(captured) >= 1, 5.0)
    time.sleep(0.1)  # guard against a spurious second write
    with lock:
        assert len(captured) == 1
        resp = captured[0]
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 42
    text = resp["result"]["content"][0]["text"]
    assert "hi" in text
    assert "exit_code" not in text  # exit 0 renders without an exit_code line


def test_deferred_already_complete_race_writes_exactly_once(bash_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the already-complete race: refuse to arm, but only after the command
    # has finished so collect() yields the terminal result.
    def _fake_register(session_id: str, callback: Callable[[], None]) -> bool:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            with bx._MANAGED_COMMANDS_LOCK:
                m = bx._MANAGED_COMMANDS.get(session_id)
            if m is None or m.proc.poll() is not None:
                break
            time.sleep(0.01)
        return False

    monkeypatch.setattr(bx, "register_completion", _fake_register)

    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp_server, "_write_jsonrpc", lambda msg: captured.append(msg))

    mcp_server._handle_and_write(_bash_request(99, "echo hi", timeout=30))

    # armed is False -> the continuation ran synchronously on the worker thread.
    assert len(captured) == 1
    assert captured[0]["id"] == 99
    assert "hi" in captured[0]["result"]["content"][0]["text"]


# --------------------------------------------------------------------------- #
# 3. Kill switch                                                              #
# --------------------------------------------------------------------------- #


def test_kill_switch_keeps_handler_synchronous(bash_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_DEFER_BASH", "0")

    # Even inside a deferral-capable context, the kill switch returns a plain dict.
    mcp_server._deferral_context.active = True
    try:
        result = mcp_server._run_bash_tool("echo hi", timeout=30)
    finally:
        mcp_server._deferral_context.active = False
    assert not isinstance(result, mcp_server._DeferredResult)
    assert isinstance(result, dict)
    assert result["exit_code"] == 0
    assert result["stdout"] == "hi"

    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp_server, "_write_jsonrpc", lambda msg: captured.append(msg))
    mcp_server._handle_and_write(_bash_request(7, "echo hi", timeout=30))
    # Written synchronously, before _handle_and_write returned.
    assert len(captured) == 1
    assert captured[0]["id"] == 7
    assert "hi" in captured[0]["result"]["content"][0]["text"]


# --------------------------------------------------------------------------- #
# 4. Parity: deferred result dict == synchronous result dict                  #
# --------------------------------------------------------------------------- #


def test_deferred_result_dict_matches_synchronous(
    bash_env: Path,
) -> None:
    command = "printf 'line1\\nline2\\n'"

    # Synchronous: no deferral context -> _run_bash_tool busy-polls to a dict.
    sync_result = mcp_server._run_bash_tool(command, timeout=30)
    assert isinstance(sync_result, dict)

    # Deferred: a deferral-capable context yields a _DeferredResult whose collect()
    # returns the terminal dict once the command finishes.
    mcp_server._deferral_context.active = True
    try:
        deferred = mcp_server._run_bash_tool(command, timeout=30)
        assert isinstance(deferred, mcp_server._DeferredResult)
        done = threading.Event()
        if deferred.register(done.set):
            assert done.wait(5.0)
        deferred_result = deferred.collect()
    finally:
        mcp_server._deferral_context.active = False
    assert isinstance(deferred_result, dict)

    # Ignore volatile timing.
    sync_result.pop("duration_ms", None)
    deferred_result.pop("duration_ms", None)
    assert sync_result == deferred_result
    assert deferred_result["exit_code"] == 0
    assert deferred_result["stdout"] == "line1\nline2"
    assert deferred_result["truncated"] is False
