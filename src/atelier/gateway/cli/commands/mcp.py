"""``atelier mcp`` — start the stdio MCP server.

This replaces the legacy standalone ``atelier mcp`` binary.
"""

from __future__ import annotations

import os
from pathlib import Path

import click


@click.command("mcp")
@click.option(
    "--root",
    envvar="ATELIER_ROOT",
    type=click.Path(file_okay=False, path_type=Path),
    help="Atelier data root (default: ~/.atelier)",
)
@click.option("--host", envvar="ATELIER_AGENT", help="Agent host identifier (e.g. claude-code)")
@click.version_option(version="0.3.1", prog_name="atelier mcp", message="%(prog_name)s %(version)s")
def mcp_cmd(root: Path | None, host: str | None) -> None:
    """Start the Atelier MCP server on stdio.

    Runs the Model Context Protocol stdio transport, used by Claude Code,
    Codex, and other MCP-compatible hosts.
    """
    if root is not None:
        os.environ["ATELIER_ROOT"] = str(root)
    if host is not None:
        os.environ["ATELIER_AGENT"] = host

    from atelier.gateway.adapters.mcp_server import main as _mcp_main

    _mcp_main()
