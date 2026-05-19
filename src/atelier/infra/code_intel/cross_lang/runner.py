"""Literal-only resolver orchestration for Phase 5 cross-language edges."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sqlite3

from .edges import CrossLangEdgeStore


class CrossLangRunner:
    """Phase 5 cross-language resolver contract."""

    resolver_names = ("ctypes", "dynamic_import", "subprocess")
    scope_ceiling = "literal_only_static_edges"
    scope_exclusions = ("runtime_tracing", "phase6_external_scope", "phase6_multi_repo_routing", "workspace_routing")

    def __init__(
        self,
        *,
        repo_root: Path,
        repo_id: str,
        connection_factory: Callable[[], sqlite3.Connection],
    ) -> None:
        self.repo_root = Path(repo_root)
        self.repo_id = repo_id
        self.connection_factory = connection_factory
        self.edge_store = CrossLangEdgeStore(connection_factory)


__all__ = ["CrossLangRunner"]
