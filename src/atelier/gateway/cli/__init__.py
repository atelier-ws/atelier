"""CLI entrypoint and commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _get_fallback_main() -> Callable[[], int]:
    """Get fallback main function when click is not available."""

    def main() -> int:
        """Fallback when click is not available."""
        import sys

        print("click not installed. Install with: pip install click", file=sys.stderr)
        return 1

    return main


def _get_fallback_cli() -> Callable[[], Any]:
    """Get fallback cli function when click is not available."""

    def cli() -> None:
        """Fallback CLI."""
        main()

    return cli


# Try importing from __main__, fall back to our own implementations
try:
    from atelier.gateway.cli.__main__ import cli as _cli
    from atelier.gateway.cli.__main__ import main as _main
except ImportError:
    _main = _get_fallback_main()
    _cli = _get_fallback_cli()

# Re-export as module-level names
cli = _cli
main = _main

__all__ = ["cli", "main"]
