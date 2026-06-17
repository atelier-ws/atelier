"""Tests for the stdio MCP single-workspace code warmer (Workstream 6 / G10)."""

from __future__ import annotations

from pathlib import Path
import json
import os

import pytest

from atelier.core.service import code_warm


@pytest.fixture(autouse=True)
def _reset_stdio_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level stdio warmer state and enable warming."""
    monkeypatch.delenv("ATELIER_SERVICE_CODE_WARM", raising=False)
    monkeypatch.setattr(code_warm, "_stdio_engine", None, raising=False)
    monkeypatch.setattr(code_warm, "_stdio_warmed", None, raising=False)


class _FakeEngine:
    instances = 0

    def __init__(self, workspace: Path) -> None:
        type(self).instances += 1
        self.workspace = workspace


def _patch_engine(monkeypatch: pytest.MonkeyPatch) -> type[_FakeEngine]:
    _FakeEngine.instances = 0
    import atelier.core.capabilities.code_context.engine as engine_mod

    monkeypatch.setattr(engine_mod, "CodeContextEngine", _FakeEngine, raising=True)
    return _FakeEngine


def test_warm_invoked_once_per_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _patch_engine(monkeypatch)

    assert code_warm.warm_stdio_workspace(tmp_path) is True
    assert fake.instances == 1

    # Second call for the same workspace is a no-op: warmed exactly once.
    assert code_warm.warm_stdio_workspace(tmp_path) is False
    assert fake.instances == 1


def test_warm_failure_is_non_fatal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import atelier.core.capabilities.code_context.engine as engine_mod

    def _boom(workspace: Path) -> None:
        raise RuntimeError("cold-start exploded")

    monkeypatch.setattr(engine_mod, "CodeContextEngine", _boom, raising=True)

    # Must NOT raise -- stdio startup must survive a warming failure.
    assert code_warm.warm_stdio_workspace(tmp_path) is False
    assert code_warm._stdio_warmed is None


def test_warm_disabled_via_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _patch_engine(monkeypatch)
    monkeypatch.setenv("ATELIER_SERVICE_CODE_WARM", "0")

    assert code_warm.warm_stdio_workspace(tmp_path) is False
    assert fake.instances == 0


def test_warm_skips_missing_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _patch_engine(monkeypatch)
    missing = tmp_path / "does-not-exist"

    assert code_warm.warm_stdio_workspace(missing) is False
    assert fake.instances == 0


def test_discover_workspaces_prunes_dead_mcp_sessions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    sessions_dir = store_root / "mcp_sessions"
    sessions_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    dead_workspace = tmp_path / "dead-workspace"
    dead_workspace.mkdir()
    live_file = sessions_dir / "live.json"
    dead_file = sessions_dir / "dead.json"
    duplicate_file = sessions_dir / "duplicate.json"
    live_payload = {
        "pid": os.getpid(),
        "workspace": str(workspace),
    }
    live_file.write_text(json.dumps(live_payload), encoding="utf-8")
    duplicate_file.write_text(json.dumps(live_payload), encoding="utf-8")
    dead_file.write_text(
        json.dumps(
            {
                "pid": os.getpid() + 1,
                "workspace": str(dead_workspace),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(code_warm, "default_store_root", lambda: store_root)
    monkeypatch.setattr(code_warm, "_registered_mcp_pid_is_live", lambda pid: pid == os.getpid())

    assert code_warm.discover_workspaces() == [workspace.resolve()]
    assert live_file.exists()
    assert duplicate_file.exists()
    assert not dead_file.exists()


def test_discover_workspaces_prunes_reused_non_mcp_pid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    sessions_dir = store_root / "mcp_sessions"
    sessions_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    stale_file = sessions_dir / "stale.json"
    stale_file.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "workspace": str(workspace),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(code_warm, "default_store_root", lambda: store_root)
    monkeypatch.setattr(code_warm, "_registered_mcp_pid_is_live", lambda pid: False)

    assert code_warm.discover_workspaces() == []
    assert not stale_file.exists()


def test_stdio_warm_hook_is_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mcp_server startup hook swallows warming errors."""
    from atelier.gateway.adapters import mcp_server

    def _boom(workspace: object) -> bool:
        raise RuntimeError("warm exploded")

    monkeypatch.setattr(code_warm, "warm_stdio_workspace", _boom, raising=True)
    # Must not raise.
    mcp_server._warm_stdio_code_index()
