"""Thin ``atelier benchmark`` and ``atelier bench`` command groups.

Suite-execution logic lives in specialized benchmark modules. The optional
SWE benchmark group is attached via ``_register_swe_benchmark_group``.
"""

from __future__ import annotations

import click


@click.group("benchmark")
def benchmark_group() -> None:
    """Run Atelier benchmark suites and reports."""


def _register_swe_benchmark_group() -> None:
    try:
        from benchmarks.swe.run_swe_bench import swe as swe_benchmark_group
    except (ImportError, ModuleNotFoundError):
        # Keep CLI startup resilient when benchmark modules are not present
        return

    benchmark_group.add_command(swe_benchmark_group)


_register_swe_benchmark_group()
