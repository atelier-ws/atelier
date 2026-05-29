"""M3 — Counterexample loop benchmark: deterministic error-detection rate.

The full self-correction metric (agent retries until green) requires a live
model and is deferred. This benchmark measures the deterministic *lower half*
that the whole loop depends on: given edits that contain known lint/type errors,
does :class:`VerifierCapability` reliably surface a counterexample for each?

Target: >=0.9 detection rate over seeded errors (real ruff + mypy).

Run explicitly (slow):
    uv run pytest tests/benchmarks/context_quality/M3_verification.py -v -m slow
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier.core.capabilities.verification import VerifierCapability

# Each case: (filename, source, expected_check). Every file contains exactly one
# deliberate defect a deterministic checker must catch.
_CASES: list[tuple[str, str, str]] = [
    ("lint_unused_os.py", "import os\n\n\ndef f() -> int:\n    return 1\n", "lint"),
    ("lint_unused_sys.py", "import sys\n\n\ndef g() -> int:\n    return 2\n", "lint"),
    (
        "lint_unused_imports.py",
        "import json\nimport re\n\n\ndef k() -> int:\n    return 3\n",
        "lint",
    ),
    ("type_assign.py", 'x: int = "not an int"\n', "typecheck"),
    ("type_return.py", 'def h() -> int:\n    return "nope"\n', "typecheck"),
    (
        "type_propagate.py",
        "def j(n: int) -> int:\n    return n\n\n\nresult: str = j(1)\n",
        "typecheck",
    ),
]


@pytest.mark.slow
def test_m3_detection_rate(tmp_path: Path) -> None:
    files: list[str] = []
    for name, source, _ in _CASES:
        p = tmp_path / name
        p.write_text(source, encoding="utf-8")
        files.append(str(p))

    counterexamples = VerifierCapability(cwd=tmp_path).run(scope_files=files, checks=("lint", "typecheck"))
    flagged = {Path(str(ce.file_path)).name for ce in counterexamples if ce.file_path}
    detected = 0
    for name, _, _expected_check in _CASES:
        hit = name in flagged
        detected += int(hit)
    rate = detected / len(_CASES)

    assert rate >= 0.9, f"detection rate {rate:.2f} below 0.90 target"
