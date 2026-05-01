"""Convenience entry-point shims.

These wrap subcommands of the main `atelier` CLI so users can type
``atelier-task ...`` instead of ``atelier task ...``. Each script forwards
``sys.argv[1:]`` to the corresponding Click subcommand.
"""

from __future__ import annotations

import sys

from atelier.gateway.adapters.cli import cli


def _invoke(subcommand: str) -> None:
    sys.argv = [f"atelier-{subcommand}", subcommand, *sys.argv[1:]]
    cli(obj={})


def task_main() -> None:
    _invoke("task")


def context_main() -> None:
    _invoke("context")


def check_plan_main() -> None:
    _invoke("check-plan")


def rescue_main() -> None:
    _invoke("rescue")
