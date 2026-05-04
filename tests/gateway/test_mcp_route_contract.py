"""Tests for atelier_route_contract MCP tool and CLI route contract command (WP-31)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from atelier.gateway.adapters.mcp_server import TOOLS, _handle

# --------------------------------------------------------------------------- #
# MCP helpers (shared pattern from test_mcp_route_decide.py)                  #
# --------------------------------------------------------------------------- #


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    req: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    resp = _handle(req)
    assert isinstance(resp, dict)
    return resp


def _result(resp: dict[str, Any]) -> dict[str, Any]:
    assert "result" in resp, resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert isinstance(payload, dict)
    return payload


@pytest.fixture()
def mcp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    monkeypatch.setenv("ATELIER_ROOT", str(root))

    import atelier.gateway.adapters.mcp_server as m

    m._current_ledger = None
    return root


# --------------------------------------------------------------------------- #
# Tool registration                                                           #
# --------------------------------------------------------------------------- #


def test_mcp_route_contract_tool_registered() -> None:
    assert "atelier_route_contract" in TOOLS


# --------------------------------------------------------------------------- #
# MCP: all known hosts return a valid contract                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("host", ["claude", "codex", "copilot", "opencode", "gemini"])
def test_mcp_route_contract_returns_contract_for_host(mcp_env: Path, host: str) -> None:
    resp = _call("atelier_route_contract", {"host": host})
    payload = _result(resp)

    assert payload["host"] == host
    assert "mode" in payload
    assert payload["mode"] in ("advisory", "wrapper_enforced")
    assert "provider_enforced_disabled" in payload
    assert payload["provider_enforced_disabled"] is True


def test_mcp_route_contract_mode_field_present(mcp_env: Path) -> None:
    """Acceptance test: atelier_route_contract returns a payload containing 'mode'."""
    resp = _call("atelier_route_contract", {"host": "codex"})
    payload = _result(resp)
    assert "mode" in payload


# --------------------------------------------------------------------------- #
# MCP: provider_enforced mode is never active                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("host", ["claude", "codex", "copilot", "opencode", "gemini"])
def test_mcp_route_contract_provider_enforced_disabled_by_default(mcp_env: Path, host: str) -> None:
    resp = _call("atelier_route_contract", {"host": host})
    payload = _result(resp)
    assert (
        payload["mode"] != "provider_enforced"
    ), f"host={host!r}: provider_enforced must never be the active mode"
    assert payload["provider_enforced_disabled"] is True


# --------------------------------------------------------------------------- #
# MCP: Claude hook enforcement facts                                          #
# --------------------------------------------------------------------------- #


def test_mcp_claude_wrapper_enforced(mcp_env: Path) -> None:
    resp = _call("atelier_route_contract", {"host": "claude"})
    payload = _result(resp)
    assert payload["mode"] == "wrapper_enforced"
    assert payload["can_block_start"] is True
    assert payload["can_require_verification"] is True
    assert payload["fallback_mode"] == "advisory"


# --------------------------------------------------------------------------- #
# MCP: Codex wrapper enforcement facts                                        #
# --------------------------------------------------------------------------- #


def test_mcp_codex_wrapper_enforced(mcp_env: Path) -> None:
    resp = _call("atelier_route_contract", {"host": "codex"})
    payload = _result(resp)
    assert payload["mode"] == "wrapper_enforced"
    assert payload["can_block_start"] is True


# --------------------------------------------------------------------------- #
# MCP: Copilot advisory mode                                                  #
# --------------------------------------------------------------------------- #


def test_mcp_copilot_advisory_mode(mcp_env: Path) -> None:
    resp = _call("atelier_route_contract", {"host": "copilot"})
    payload = _result(resp)
    assert payload["mode"] == "advisory"
    assert payload["can_block_start"] is False
    assert payload["can_force_model"] is False


# --------------------------------------------------------------------------- #
# CLI: route contract command                                                 #
# --------------------------------------------------------------------------- #


def test_cli_route_contract_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI route contract --host codex --json must include 'mode' key."""
    from click.testing import CliRunner

    from atelier.gateway.adapters.cli import cli

    root = tmp_path / ".atelier"
    root.mkdir(parents=True)

    # Initialise store so _load_store doesn't fail for other commands;
    # route contract does not need the store.
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--root", str(root), "route", "contract", "--host", "codex", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "mode" in payload
    assert payload["host"] == "codex"
    assert payload["provider_enforced_disabled"] is True


def test_cli_route_contract_text_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from click.testing import CliRunner

    from atelier.gateway.adapters.cli import cli

    root = tmp_path / ".atelier"
    root.mkdir(parents=True)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--root", str(root), "route", "contract", "--host", "copilot"],
    )
    assert result.exit_code == 0, result.output
    assert "advisory" in result.output
