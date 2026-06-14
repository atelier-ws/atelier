"""Tests for per-request project isolation in the stdio MCP server (N10)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from atelier.gateway.adapters import mcp_server


@pytest.fixture(autouse=True)
def _reset_request_project() -> Iterator[None]:
    mcp_server._request_project.value = None
    yield
    mcp_server._request_project.value = None


def test_default_workspace_when_no_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    mcp_server._request_project.value = None
    assert mcp_server._workspace_root() == Path(str(tmp_path))


def test_override_wins_over_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_ws = tmp_path / "env_ws"
    other = tmp_path / "other_repo"
    env_ws.mkdir()
    other.mkdir()
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(env_ws))

    prior = mcp_server._set_request_project(str(other))
    try:
        assert mcp_server._workspace_root().resolve() == other.resolve()
    finally:
        mcp_server._clear_request_project(prior)

    # Cleared -> back to the env workspace.
    assert mcp_server._workspace_root() == Path(str(env_ws))


def test_extract_from_meta_header(tmp_path: Path) -> None:
    params = {"_meta": {"mcp-project-path": str(tmp_path)}}
    assert mcp_server._extract_request_project(params, {}) == str(tmp_path)


def test_extract_from_arg_and_pops_it(tmp_path: Path) -> None:
    args = {"project_path": str(tmp_path), "query": "x"}
    assert mcp_server._extract_request_project({}, args) == str(tmp_path)
    # The reserved arg must be removed so it never reaches the tool handler.
    assert "project_path" not in args
    assert args == {"query": "x"}


def test_extract_absent_returns_none() -> None:
    assert mcp_server._extract_request_project({}, {"query": "x"}) is None
    assert mcp_server._extract_request_project({"_meta": {}}, {}) is None


def test_set_rejects_nonexistent_path(tmp_path: Path) -> None:
    mcp_server._set_request_project(str(tmp_path / "missing"))
    assert mcp_server._request_project.value is None


def test_set_rejects_empty_string() -> None:
    mcp_server._set_request_project("   ")
    assert mcp_server._request_project.value is None


def test_set_returns_prior_for_nesting(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    p0 = mcp_server._set_request_project(str(a))
    assert p0 is None
    p1 = mcp_server._set_request_project(str(b))
    assert p1 == str(a.resolve())
    mcp_server._clear_request_project(p1)
    assert mcp_server._request_project.value == str(a.resolve())
    mcp_server._clear_request_project(p0)
    assert mcp_server._request_project.value is None
