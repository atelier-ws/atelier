"""Atelier mini eval suite — a cheap, deterministic cost-quality benchmark.

Public API
----------
- :class:`MiniEvalCase`, :class:`MiniEvalCaseResult`, :class:`MiniEvalReport`
- :func:`load_cases` — load case definitions from YAML
- :func:`run_suite`, :func:`run_case`, :func:`run_case_dry`, :func:`aggregate_report`
- :func:`save_report`, :func:`render_markdown`
"""

from __future__ import annotations

from atelier.core.capabilities.eval_mini.loader import (
    default_cases_path,
    load_cases,
    repo_root,
)
from atelier.core.capabilities.eval_mini.report import render_markdown, save_report
from atelier.core.capabilities.eval_mini.runner import (
    aggregate_report,
    run_case,
    run_case_dry,
    run_suite,
)
from atelier.core.capabilities.eval_mini.schema import (
    MiniEvalCase,
    MiniEvalCaseResult,
    MiniEvalReport,
)

__all__ = [
    "MiniEvalCase",
    "MiniEvalCaseResult",
    "MiniEvalReport",
    "aggregate_report",
    "default_cases_path",
    "load_cases",
    "render_markdown",
    "repo_root",
    "run_case",
    "run_case_dry",
    "run_suite",
    "save_report",
]
