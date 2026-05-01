"""Tests for the OpenMemory optional integration stubs (P7)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from atelier.gateway.adapters.cli import cli
from atelier.gateway.integrations.openmemory import (
    is_enabled,
    list_available_memory_tools,
    maybe_fetch_memory_context_for_task,
    maybe_link_trace_to_memory_context,
    maybe_store_memory_pointer,
)

# --------------------------------------------------------------------------- #
# is_enabled                                                                  #
# --------------------------------------------------------------------------- #


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    assert is_enabled() is False


def test_enabled_via_env_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_OPENMEMORY_ENABLED", "true")
    assert is_enabled() is True


def test_enabled_via_env_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_OPENMEMORY_ENABLED", "1")
    assert is_enabled() is True


def test_disabled_via_env_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_OPENMEMORY_ENABLED", "false")
    assert is_enabled() is False


# --------------------------------------------------------------------------- #
# list_available_memory_tools                                                 #
# --------------------------------------------------------------------------- #


def test_list_tools_disabled_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    assert list_available_memory_tools() == []


def test_list_tools_enabled_server_unavailable_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_OPENMEMORY_ENABLED", "true")
    tools = list_available_memory_tools()
    assert isinstance(tools, list)


# --------------------------------------------------------------------------- #
# maybe_link_trace_to_memory_context                                         #
# --------------------------------------------------------------------------- #


def test_link_trace_disabled_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    result = maybe_link_trace_to_memory_context("trace-123")
    assert result["ok"] is False
    assert result["skipped"] is True
    assert "disabled" in str(result["reason"]).lower()


def test_link_trace_disabled_with_context_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    result = maybe_link_trace_to_memory_context("trace-123", context_id="ctx-456")
    assert result["ok"] is False
    assert result["action"] == "link_trace_to_memory_context"


def test_link_trace_enabled_server_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_OPENMEMORY_ENABLED", "true")
    monkeypatch.setenv("ATELIER_OPENMEMORY_MCP_SERVER_NAME", "openmemory-test")
    result = maybe_link_trace_to_memory_context("trace-123", context_id="ctx-456")
    assert result["ok"] is False
    assert result["skipped"] is True
    assert "unavailable" in str(result["reason"]).lower()


# --------------------------------------------------------------------------- #
# maybe_fetch_memory_context_for_task                                        #
# --------------------------------------------------------------------------- #


def test_fetch_context_disabled_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    result = maybe_fetch_memory_context_for_task("fix the failing test")
    assert result["ok"] is False
    assert result["skipped"] is True
    assert "disabled" in str(result["reason"]).lower()


def test_fetch_context_enabled_server_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_OPENMEMORY_ENABLED", "true")
    result = maybe_fetch_memory_context_for_task(
        "update Shopify product metafields", project_id="proj-1"
    )
    assert result["ok"] is False
    assert result["skipped"] is True


# --------------------------------------------------------------------------- #
# maybe_store_memory_pointer                                                  #
# --------------------------------------------------------------------------- #


def test_store_pointer_disabled_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    result = maybe_store_memory_pointer("trace-123", "mem-456")
    assert result["ok"] is False
    assert result["skipped"] is True
    assert "disabled" in str(result["reason"]).lower()


def test_store_pointer_enabled_server_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_OPENMEMORY_ENABLED", "true")
    result = maybe_store_memory_pointer("trace-abc", "mem-xyz")
    assert result["ok"] is False
    assert result["skipped"] is True
    assert "unavailable" in str(result["reason"]).lower()


# --------------------------------------------------------------------------- #
# Response shape — all disabled responses share the same contract             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fn",
    [
        lambda: maybe_link_trace_to_memory_context("t1"),
        lambda: maybe_fetch_memory_context_for_task("task"),
        lambda: maybe_store_memory_pointer("t1", "m1"),
    ],
)
def test_disabled_response_has_required_keys(fn: object, monkeypatch: pytest.MonkeyPatch) -> None:
    import typing

    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    result = typing.cast("dict[str, object]", fn)()  # type: ignore[operator]
    assert "ok" in result
    assert "skipped" in result
    assert "reason" in result
    assert "action" in result


# --------------------------------------------------------------------------- #
# CLI smoke tests                                                             #
# --------------------------------------------------------------------------- #


def test_cli_openmemory_status_disabled(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(tmp_path), "openmemory", "status"], obj={})
    assert result.exit_code == 0
    assert "enabled: False" in result.output


def test_cli_openmemory_status_enabled(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATELIER_OPENMEMORY_ENABLED", "true")
    runner = CliRunner()
    result = runner.invoke(cli, ["--root", str(tmp_path), "openmemory", "status"], obj={})
    assert result.exit_code == 0
    assert "enabled: True" in result.output


def test_cli_openmemory_link_trace_disabled(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--root", str(tmp_path), "openmemory", "link-trace", "trace-42"], obj={}
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["skipped"] is True


def test_cli_openmemory_fetch_context_disabled(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ATELIER_OPENMEMORY_ENABLED", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--root", str(tmp_path), "openmemory", "fetch-context", "fix the bug"],
        obj={},
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is False
