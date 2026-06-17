"""Run the pytest-backed MCP tool benchmark suite with one command.

Usage:
    uv run python benchmarks/mcp_tools/run_all.py
    uv run python benchmarks/mcp_tools/run_all.py --list
    uv run python benchmarks/mcp_tools/run_all.py -- -x
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

EXCLUDED = {"bench_external_indexers.py"}


def _suite_files() -> list[str]:
    root = Path(__file__).resolve().parent
    return sorted(str(path) for path in root.glob("bench_*.py") if path.name not in EXCLUDED)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all pytest-backed MCP tool benchmarks.")
    parser.add_argument("--list", action="store_true", help="List benchmark files without running them.")
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra pytest args to append after the benchmark file list (prefix with `--`).",
    )
    args = parser.parse_args()

    files = _suite_files()
    if args.list:
        for path in files:
            print(path)
        return 0

    extra_args = list(args.pytest_args)
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]

    cmd = [sys.executable, "-m", "pytest", *files, "-v", "-s", *extra_args]
    print("Running:", " ".join(cmd))
    completed = subprocess.run(cmd, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
