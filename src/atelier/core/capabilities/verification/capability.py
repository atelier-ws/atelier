"""Verifier capability orchestrator (M3).

Runs the deterministic checks over the files an agent touched and returns
structured counterexamples. Host-agnostic: it does not drive a retry loop — it
produces the signal the host (or M5's PostToolUse choreography) feeds back.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from .checks import CommandRunner, run_lint, run_tests, run_typecheck
from .counterexample import Counterexample

_DEFAULT_CHECKS = ("lint", "typecheck", "tests")


def _default_run(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=str(cwd), capture_output=True, text=True, check=False, timeout=120)


def _typecheck_targets(files: list[str]) -> list[str]:
    """Distinct parent dirs of touched python source files (excludes tests)."""
    dirs: list[str] = []
    for f in files:
        if not f.endswith(".py") or "test" in Path(f).name:
            continue
        parent = str(Path(f).parent)
        if parent and parent not in dirs:
            dirs.append(parent)
    return dirs


class VerifierCapability:
    """Run scoped deterministic checks and surface structured counterexamples."""

    def __init__(self, *, cwd: str | Path | None = None, run: CommandRunner | None = None) -> None:
        self._cwd = Path(cwd or ".")
        self._run: CommandRunner = run or _default_run

    def run(
        self,
        *,
        scope_files: list[str],
        checks: Sequence[str] = _DEFAULT_CHECKS,
    ) -> list[Counterexample]:
        results: list[Counterexample] = []
        if "lint" in checks:
            results.extend(run_lint(scope_files, cwd=self._cwd, run=self._run))
        if "typecheck" in checks:
            results.extend(run_typecheck(_typecheck_targets(scope_files), cwd=self._cwd, run=self._run))
        if "tests" in checks:
            results.extend(run_tests(scope_files, cwd=self._cwd, run=self._run))
        return results

    @staticmethod
    def format_counterexamples(counterexamples: Sequence[Counterexample]) -> str:
        """Render counterexamples as a single TURN-channel feedback block."""
        return "\n".join(c.to_prompt_block() for c in counterexamples)
