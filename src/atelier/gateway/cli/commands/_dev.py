"""Dev-mode / MCP-tool-only gating primitives for the Atelier CLI.

These symbols are moved verbatim from ``app.py`` so command modules can import
them *downward* (``commands/* -> commands/_dev``) without depending on the
global ``cli`` object defined in ``app.py``. Keeping them here breaks the
future ``app.py`` <-> ``commands/*`` circular-import risk (RESEARCH Pitfall 1).

``_dev_command`` / ``_dev_group`` themselves stay in ``app.py`` because they
register on the global ``cli`` object; they import the sets, ``_DummyGroup``,
and ``_check_dev_mode`` from this module.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import click

from atelier.core.environment import cli_dev_disabled_message, is_dev_mode


class _DummyGroup:
    """A placeholder for a Click group that does nothing."""

    def command(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return lambda f: f

    def group(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Any]:
        return lambda f: _DummyGroup()  # type: ignore


MCP_TOOL_ONLY_COMMANDS = frozenset({"context", "rescue", "verify", "read", "edit", "search"})
MCP_TOOL_ONLY_GROUPS = frozenset({"memory", "route"})


def _check_dev_mode(command_name: str, status: int = 1) -> None:
    if not is_dev_mode():
        click.echo(cli_dev_disabled_message(command_name))
        sys.exit(status)
