"""Load and spawn MCP servers from .mcp.json configuration files."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MCP_CONFIG_PATHS = [
    Path(".mcp.json"),
    Path(".claude") / "mcp.json",
    Path.home() / ".atelier" / "tui" / ".mcp.json",
]


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPTool:
    server_name: str
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


def discover_mcp_configs() -> list[MCPServerConfig]:
    """Read all .mcp.json files and return server configs."""
    configs = []
    seen_names: set[str] = set()
    for config_path in _MCP_CONFIG_PATHS:
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") or data.get("servers") or {}
            for name, cfg in servers.items():
                if name in seen_names:
                    continue
                seen_names.add(name)
                if isinstance(cfg, dict) and cfg.get("command"):
                    configs.append(MCPServerConfig(
                        name=name,
                        command=str(cfg["command"]),
                        args=[str(a) for a in cfg.get("args", [])],
                        env={str(k): str(v) for k, v in cfg.get("env", {}).items()},
                    ))
        except Exception as exc:  # noqa: BLE001 - config load is best-effort
            logger.debug("Failed to load MCP config %s: %s", config_path, exc)
    return configs


class MCPServerProcess:
    """Manages a spawned MCP server process communicating over stdio JSON-RPC."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._proc: subprocess.Popen[bytes] | None = None
        self._tools: list[MCPTool] = []
        self._request_id = 0

    def start(self) -> bool:
        """Start the server subprocess. Returns True if successful."""
        try:
            env = os.environ.copy()
            env.update(self.config.env)
            self._proc = subprocess.Popen(
                [self.config.command, *self.config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            # Initialize with JSON-RPC handshake
            self._initialize()
            return True
        except Exception as exc:  # noqa: BLE001 - spawn is best-effort
            logger.debug("Failed to start MCP server %s: %s", self.config.name, exc)
            return False

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and return the result."""
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            return None
        self._request_id += 1
        request = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params or {}}
        try:
            line = json.dumps(request) + "\n"
            self._proc.stdin.write(line.encode())
            self._proc.stdin.flush()
            response_line = self._proc.stdout.readline()
            if response_line:
                resp = json.loads(response_line)
                return resp.get("result")
        except Exception as exc:  # noqa: BLE001 - rpc is best-effort
            logger.debug("MCP RPC error for %s: %s", self.config.name, exc)
        return None

    def _initialize(self) -> None:
        """Send initialize + notifications/initialized to complete handshake."""
        result = self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "atelier-tui", "version": "0.1.0"},
        })
        if result:
            self._rpc("notifications/initialized")

    def list_tools(self) -> list[MCPTool]:
        """Fetch tool definitions from the server."""
        result = self._rpc("tools/list")
        tools = []
        if result and isinstance(result, dict):
            for t in result.get("tools", []):
                tools.append(MCPTool(
                    server_name=self.config.name,
                    name=str(t.get("name", "")),
                    description=str(t.get("description", "")),
                    input_schema=dict(t.get("inputSchema", {})),
                ))
        self._tools = tools
        return tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool and return the result as a string."""
        result = self._rpc("tools/call", {"name": tool_name, "arguments": arguments})
        if result is None:
            return f"Error: MCP tool call failed for {tool_name}"
        # MCP tools return content blocks
        if isinstance(result, dict):
            content = result.get("content", [])
            if isinstance(content, list):
                return "\n".join(
                    item.get("text", "") for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            return str(content)
        return str(result)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    @property
    def tools(self) -> list[MCPTool]:
        return self._tools


__all__ = ["MCPServerConfig", "MCPServerProcess", "MCPTool", "discover_mcp_configs"]
