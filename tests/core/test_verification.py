"""Tests for the M3 verification / counterexample capability."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from atelier.core.capabilities.verification import Counterexample, RetryBudget, VerifierCapability


def _proc(stdout: str = "", stderr: str = "", returncode: int = 1) -> Any:
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def test_lint_failure_becomes_counterexample() -> None:
    payload = json.dumps(
        [
            {
                "code": "F401",
                "message": "imported but unused",
                "filename": "src/x.py",
                "location": {"row": 3, "column": 1},
            }
        ]
    )

    def fake_run(args: Any, cwd: Path) -> Any:
        return _proc(stdout=payload)

    ces = VerifierCapability(run=fake_run).run(scope_files=["src/x.py"], checks=["lint"])
    assert len(ces) == 1
    ce = ces[0]
    assert ce.check == "lint" and ce.file_path == "src/x.py" and ce.line == 3
    assert "F401" in ce.diagnostic


def test_typecheck_parsing() -> None:
    def fake_run(args: Any, cwd: Path) -> Any:
        return _proc(stdout="src/x.py:42: error: Incompatible types in assignment\n")

    ces = VerifierCapability(run=fake_run).run(scope_files=["src/x.py"], checks=["typecheck"])
    assert len(ces) == 1
    assert ces[0].check == "typecheck" and ces[0].line == 42 and ces[0].severity == "error"


def test_tests_parsing() -> None:
    def fake_run(args: Any, cwd: Path) -> Any:
        return _proc(stdout="FAILED tests/test_x.py::test_a - AssertionError: nope\n")

    ces = VerifierCapability(run=fake_run).run(scope_files=["tests/test_x.py"], checks=["tests"])
    assert len(ces) == 1
    assert ces[0].check == "tests" and ces[0].file_path == "tests/test_x.py"
    assert ces[0].repro_command == "pytest -q tests/test_x.py::test_a"


def test_budget_exhaustion() -> None:
    budget = RetryBudget(max_attempts=3)
    for _ in range(3):
        assert not budget.exhausted()
        budget.consume()
    assert budget.exhausted() and budget.remaining() == 0


def test_to_prompt_block_is_structured() -> None:
    block = Counterexample(
        check="typecheck",
        severity="error",
        file_path="foo.py",
        line=42,
        diagnostic="Incompatible types",
        expected="x is int",
        actual="x is str | None",
        repro_command="mypy src/foo.py",
    ).to_prompt_block()
    assert 'check="typecheck"' in block and "repro:    mypy src/foo.py" in block


def test_fail_open_on_runner_error() -> None:
    def boom(args: Any, cwd: Path) -> Any:
        raise RuntimeError("tool missing")

    ces = VerifierCapability(run=boom).run(scope_files=["src/x.py"], checks=["lint", "typecheck", "tests"])
    assert ces == []
