"""Tests for MCP server config discovery and process lifecycle."""

from __future__ import annotations

import json

from atelier.core.capabilities.mcp_integration import loader
from atelier.core.capabilities.mcp_integration.loader import (
    MCPServerConfig,
    MCPServerProcess,
    discover_mcp_configs,
)


def test_discover_returns_empty_when_no_configs(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "_MCP_CONFIG_PATHS", [tmp_path / "missing.json"])
    assert discover_mcp_configs() == []


def test_discover_parses_mcp_json(monkeypatch, tmp_path):
    cfg_path = tmp_path / ".mcp.json"
    cfg_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "weather": {
                        "command": "weather-server",
                        "args": ["--port", "8080"],
                        "env": {"API_KEY": "abc"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(loader, "_MCP_CONFIG_PATHS", [cfg_path])
    # A config outside a trusted root is only auto-spawned with explicit opt-in.
    monkeypatch.setenv("ATELIER_MCP_ALLOW_UNTRUSTED", "1")
    configs = discover_mcp_configs()
    assert len(configs) == 1
    assert configs[0].name == "weather"
    assert configs[0].command == "weather-server"
    assert configs[0].args == ["--port", "8080"]
    assert configs[0].env == {"API_KEY": "abc"}


def test_stop_safe_when_not_started():
    proc = MCPServerProcess(MCPServerConfig(name="x", command="noop"))
    # Should not raise when stopping an unstarted process.
    proc.stop()
