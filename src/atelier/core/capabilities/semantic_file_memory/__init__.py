"""Semantic file memory capability — public API."""

from .capability import SemanticFileMemoryCapability
from .models import ChangeImpact, ImportInfo, SemanticSummary, SymbolInfo
from .python_ast import (
    _ast_truncated_source,
    _python_full_ast,
    analyze_python,
    stub_function_bodies,
)
from .search import SymbolIndex
from .typescript_ast import analyze_typescript

__all__ = [
    "ChangeImpact",
    "ImportInfo",
    "SemanticFileMemoryCapability",
    "SemanticSummary",
    "SymbolIndex",
    "SymbolInfo",
    "_ast_truncated_source",
    # Backward-compatible aliases (used by tests and engine.py)
    "_python_full_ast",
    "analyze_python",
    "analyze_typescript",
    "stub_function_bodies",
]
