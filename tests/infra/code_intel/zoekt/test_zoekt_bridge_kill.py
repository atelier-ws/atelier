"""Test for the LOW finding: a timed-out zoekt bridge must be reaped and cleared.

When the request timer fires, `_kill_bridge` kills the Popen. Before the fix it
never wait()ed the child (transient zombie + leaked pipe fds) and left
`self._bridge` non-None, so `_is_ready()` was ambiguous about a dead bridge.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

import atelier.infra.code_intel.zoekt.server as server_module
from atelier.infra.code_intel.zoekt.server import ZoektServer


class _FakeStream:
    def __init__(self) -> None:
        self.closed = False

    def write(self, _data: str) -> int:
        return 0

    def flush(self) -> None:
        return None

    def readline(self) -> str:
        # After _kill_bridge runs, the real bridge's stdout hits EOF. Return ""
        # so _bridge_request sees EOF with timed_out set and raises TimeoutError.
        return ""

    def read(self) -> str:
        return ""


class _FakeBridge:
    """Minimal Popen stand-in that records kill()/wait() calls."""

    def __init__(self) -> None:
        self.stdin = _FakeStream()
        self.stdout = _FakeStream()
        self.stderr = _FakeStream()
        self.killed = False
        self.wait_calls: list[float | None] = []

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        return 0

    def poll(self) -> int | None:
        return 0 if self.killed else None


class _ImmediateTimer:
    """Fire the callback synchronously on start() so the test is deterministic."""

    def __init__(self, _interval: float, function: Any) -> None:
        self._function = function

    def start(self) -> None:
        self._function()

    def cancel(self) -> None:
        return None


def test_kill_bridge_reaps_child_and_clears_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module.threading, "Timer", _ImmediateTimer)

    server = ZoektServer(tmp_path)
    bridge = _FakeBridge()
    server._bridge = bridge  # type: ignore[assignment]

    with pytest.raises(TimeoutError):
        server._bridge_request({"q": "needle"})

    assert bridge.killed is True
    # wait() must have been attempted to reap the child (no zombie / fd leak).
    assert bridge.wait_calls == [5]
    # The handle is cleared so _is_ready() reads False unambiguously.
    assert server._bridge is None


def test_threading_timer_is_real_by_default() -> None:
    # Guard: the production module still wires the real threading.Timer.
    assert server_module.threading.Timer is threading.Timer
