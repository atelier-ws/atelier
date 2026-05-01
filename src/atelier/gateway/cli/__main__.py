"""Atelier CLI main entry point."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

try:
    import click
except ImportError:
    click = None  # type: ignore[assignment]


def _get_cli() -> Callable[[], Any]:
    """Get the CLI function, either from click or fallback."""
    if click is None:
        # Fallback if dependencies not available
        def fallback_cli() -> None:
            print("Required dependencies not installed (click)", file=sys.stderr)
            sys.exit(1)

        return fallback_cli

    @click.group()
    def cli() -> None:
        """Atelier CLI - reasoning blocks, rubrics, and pack management."""
        pass

    # TODO: Add pack commands once they're refactored
    # from atelier.gateway.cli.pack import pack as pack_group
    # cli.add_command(pack_group, name="pack")
    return cli


cli = _get_cli()


def main() -> int:
    """Main entry point."""
    try:
        cli()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
