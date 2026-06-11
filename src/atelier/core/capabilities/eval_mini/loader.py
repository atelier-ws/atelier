"""Load and validate mini eval cases from YAML."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from atelier.core.capabilities.eval_mini.schema import MiniEvalCase


def repo_root() -> Path:
    """Resolve the repository root.

    Prefers ``git rev-parse --show-toplevel`` and falls back to walking up
    from this file until a ``benchmarks/mini/cases.yaml`` or ``pyproject.toml``
    marker is found.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path.cwd(),
        )
        candidate = out.stdout.strip()
        if candidate:
            return Path(candidate).resolve()
    except (OSError, subprocess.SubprocessError):
        pass

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "benchmarks" / "mini" / "cases.yaml").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd().resolve()


def default_cases_path() -> Path:
    """Return the default ``benchmarks/mini/cases.yaml`` path under the repo root."""
    return repo_root() / "benchmarks" / "mini" / "cases.yaml"


def load_cases(path: Path | str | None = None) -> list[MiniEvalCase]:
    """Load and validate mini eval cases from YAML.

    Parameters
    ----------
    path:
        Path to the cases YAML file. Defaults to ``benchmarks/mini/cases.yaml``
        resolved relative to the repository root.
    """
    cases_path = Path(path) if path is not None else default_cases_path()
    if not cases_path.exists():
        raise FileNotFoundError(f"mini eval cases file not found: {cases_path}")

    data = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or {}
    raw_cases = data.get("cases", []) if isinstance(data, dict) else []
    return [MiniEvalCase.model_validate(case) for case in raw_cases]


__all__ = ["default_cases_path", "load_cases", "repo_root"]
