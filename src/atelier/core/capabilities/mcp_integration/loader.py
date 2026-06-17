"""Load and spawn MCP servers from .mcp.json configuration files."""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MCP_CONFIG_PATHS = [
    Path(".mcp.json"),
    Path(".claude") / "mcp.json",
    Path.home() / ".atelier" / "tui" / ".mcp.json",
]

# Seconds to wait for a JSON-RPC response before treating the server as hung.
_RPC_TIMEOUT_SECONDS = 10.0
# Cap on the textual result returned from a tool call.
_MAX_TOOL_RESULT_CHARS = 64_000
_TRUST_OPT_IN_ENV = "ATELIER_MCP_ALLOW_UNTRUSTED"


def _trusted_roots() -> list[Path]:
    """Directories an MCP config may live under to be auto-spawned without opt-in."""
    roots = [Path.home() / ".atelier"]
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT")
    if workspace:
        roots.append(Path(workspace))
    return roots


def _is_trusted_config_path(config_path: Path) -> bool:
    """True if the config may be auto-spawned without explicit opt-in.

    Auto-spawning servers declared by a `.mcp.json` in an untrusted working
    directory is arbitrary command execution. Only configs resolved under a
    trusted root (the Atelier home or the explicit workspace root) are spawned
    automatically; everything else requires the operator to set
    ``ATELIER_MCP_ALLOW_UNTRUSTED``.
    """
    if os.environ.get(_TRUST_OPT_IN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        resolved = config_path.resolve()
    except OSError:
        return False
    for root in _trusted_roots():
        try:
            resolved.relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


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
        if not _is_trusted_config_path(config_path):
            logger.info(
                "Skipping untrusted MCP config %s; set %s to auto-spawn its servers",
                config_path,
                _TRUST_OPT_IN_ENV,
            )
            continue
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") or data.get("servers") or {}
            for name, cfg in servers.items():
                if name in seen_names:
                    logger.debug("Skipping duplicate MCP server %s from %s", name, config_path)
                    continue
                if isinstance(cfg, dict) and cfg.get("command"):
                    seen_names.add(name)
                    configs.append(
                        MCPServerConfig(
                            name=name,
                            command=str(cfg["command"]),
                            args=[str(a) for a in cfg.get("args", [])],
                            env={str(k): str(v) for k, v in cfg.get("env", {}).items()},
                        )
                    )
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
        self._rpc_lock = threading.Lock()

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
        with self._rpc_lock:
            if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
                return None
            self._request_id += 1
            request = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params or {}}
            try:
                line = json.dumps(request) + "\n"
                self._proc.stdin.write(line.encode())
                self._proc.stdin.flush()
                response_line = self._read_response_line()
                if response_line:
                    resp = json.loads(response_line)
                    return resp.get("result")
            except Exception as exc:  # noqa: BLE001 - rpc is best-effort
                logger.debug("MCP RPC error for %s: %s", self.config.name, exc)
        return None

    def _read_response_line(self) -> bytes | None:
        """Read one response line with a timeout; terminate a hung server.

        A bare ``readline()`` blocks forever if the child never replies, which
        wedges session startup. Read on a background thread and bound the wait
        with ``queue.get``; on timeout the child is terminated and ``None`` is
        returned so the caller falls back to the no-result path.
        """
        stdout = self._proc.stdout if self._proc is not None else None
        if stdout is None:
            return None
        result: queue.Queue[bytes | None] = queue.Queue(maxsize=1)

        def _read() -> None:
            try:
                result.put(stdout.readline())
            except Exception:  # noqa: BLE001 - reader thread is best-effort
                result.put(None)

        threading.Thread(target=_read, daemon=True).start()
        try:
            return result.get(timeout=_RPC_TIMEOUT_SECONDS)
        except queue.Empty:
            logger.debug("MCP server %s timed out; terminating", self.config.name)
            self.stop()
            return None

    def _initialize(self) -> None:
        """Send initialize + notifications/initialized to complete handshake."""
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "atelier", "version": "0.1.0"},
            },
        )
        if result:
            self._rpc("notifications/initialized")

    def list_tools(self) -> list[MCPTool]:
        """Fetch tool definitions from the server."""
        result = self._rpc("tools/list")
        tools = []
        if result and isinstance(result, dict):
            for t in result.get("tools", []):
                tools.append(
                    MCPTool(
                        server_name=self.config.name,
                        name=str(t.get("name", "")),
                        description=str(t.get("description", "")),
                        input_schema=dict(t.get("inputSchema", {})),
                    )
                )
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
                rendered = self._render_content_blocks(content)
            else:
                rendered = str(content)
            if result.get("isError"):
                rendered = f"Error: MCP tool {tool_name} reported failure: {rendered}"
            return rendered[:_MAX_TOOL_RESULT_CHARS]
        return str(result)[:_MAX_TOOL_RESULT_CHARS]

    @staticmethod
    def _render_content_blocks(content: list[Any]) -> str:
        """Flatten MCP content blocks, keeping non-text blocks instead of dropping them."""
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            block_type = item.get("type")
            if block_type == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(f"[{block_type or 'non-text'} block]")
        return "\n".join(parts)

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
