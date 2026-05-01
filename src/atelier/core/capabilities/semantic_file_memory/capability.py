"""SemanticFileMemoryCapability — thin orchestrator over all sub-modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .indexer import FileIndex
from .models import SemanticSummary
from .python_ast import analyze_python, stub_function_bodies
from .search import SymbolIndex
from .typescript_ast import analyze_typescript

try:
    from git import Repo
except Exception:  # pragma: no cover - optional dependency fallback
    Repo: Any = None  # type: ignore[no-redef]


class SemanticFileMemoryCapability:
    """
    Semantic file analysis with content-addressed caching.

    Capabilities:
    - Full Python AST extraction (functions, classes, methods, variables,
      decorators, docstrings, complexity, return types)
    - Full TypeScript/JS export/interface/type/enum detection
    - SHA-256 content-addressed cache (reliable across git, Docker, rsync)
    - Cross-file symbol resolution
    - BM25-ranked full-text search over cached summaries
    - Reverse dependency graph for change impact analysis
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._index = FileIndex(self._root)
        self._symbol_index = SymbolIndex(self._index)

    # ------------------------------------------------------------------
    # Language detection
    # ------------------------------------------------------------------

    @staticmethod
    def _language_for(path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".py": "python",
            ".pyi": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".sql": "sql",
            ".md": "markdown",
        }.get(suffix, "text")

    # ------------------------------------------------------------------
    # Core summarisation
    # ------------------------------------------------------------------

    def summarize_file(self, path: str | Path, *, max_lines: int = 120) -> SemanticSummary:
        """Analyse a file and cache the result (by SHA-256 content hash)."""
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f"file not found: {file_path}")

        # Serve from cache if unchanged
        cached = self._index.get(file_path)
        if cached:
            return self._entry_to_summary(cached)

        source = file_path.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        language = self._language_for(file_path)

        symbol_details: list[dict[str, Any]] = []
        symbols: list[str] = []
        exports: list[str] = []
        imports_modules: list[str] = []
        dependency_map: list[str] = []
        ast_summary = "ast:unsupported"
        module_docstring = ""
        complexity_score = 0
        git_last_commit = ""
        git_last_author_date = ""

        if language == "python":
            sym_infos, imp_infos, ast_summary, module_docstring, complexity_score = analyze_python(
                source
            )
            symbols = [s.name for s in sym_infos]
            exports = [s.name for s in sym_infos if s.is_export and not s.is_private]
            symbol_details = [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "lineno": s.lineno,
                    "signature": s.signature,
                    "is_private": s.is_private,
                    "docstring": s.docstring,
                    "decorators": s.decorators,
                    "type_hint": s.type_hint,
                    "complexity": s.complexity,
                }
                for s in sym_infos
            ]
            imports_modules = sorted({i.module for i in imp_infos})
            # Resolve local imports to file paths
            base = file_path.parent
            for imp in imp_infos:
                parts = imp.module.split(".")
                for search_base in [base, base.parent]:
                    candidate = search_base / Path(*parts).with_suffix(".py")
                    if candidate.is_file():
                        dependency_map.append(str(candidate))
                        break
            dependency_map = list(dict.fromkeys(dependency_map))[:15]
            summary_str = stub_function_bodies(source, max_body_lines=2)
            if len(summary_str.splitlines()) > max_lines:
                summary_str = "\n".join(summary_str.splitlines()[:max_lines]) + "\n... [truncated]"

        elif language in ("typescript", "javascript"):
            sym_infos_ts, imp_infos_ts, ast_summary = analyze_typescript(source)
            symbols = [s.name for s in sym_infos_ts]
            exports = [s.name for s in sym_infos_ts if s.is_export]
            symbol_details = [
                {"name": s.name, "kind": s.kind, "lineno": s.lineno, "signature": s.signature}
                for s in sym_infos_ts
            ]
            imports_modules = sorted({i.module for i in imp_infos_ts})
            summary_str = "\n".join(lines[:max_lines])
            if len(lines) > max_lines:
                summary_str += "\n... [truncated]"

        else:
            summary_str = "\n".join(lines[:max_lines])
            if len(lines) > max_lines:
                summary_str += "\n... [truncated]"

        # Find linked test files
        test_files = self._find_test_files(file_path)
        git_last_commit, git_last_author_date = self._git_metadata(file_path)

        payload: dict[str, Any] = {
            "path": str(file_path),
            "language": language,
            "summary": summary_str,
            "symbols": symbols,
            "exports": exports,
            "lines_total": len(lines),
            "ast_summary": ast_summary,
            "symbol_details": symbol_details,
            "imports": imports_modules,
            "dependency_map": dependency_map,
            "test_files": test_files,
            "module_docstring": module_docstring,
            "complexity_score": complexity_score,
            "git_last_commit": git_last_commit,
            "git_last_author_date": git_last_author_date,
        }
        self._index.put(file_path, payload)
        return self._entry_to_summary(payload)

    @staticmethod
    def _entry_to_summary(entry: dict[str, Any]) -> SemanticSummary:
        return SemanticSummary(
            path=str(entry.get("path", "")),
            language=str(entry.get("language", "text")),
            summary=str(entry.get("summary", "")),
            symbols=list(entry.get("symbols", [])),
            exports=list(entry.get("exports", [])),
            lines_total=int(entry.get("lines_total", 0)),
            ast_summary=str(entry.get("ast_summary", "")),
            content_hash=str(entry.get("content_hash", "")),
            symbol_details=list(entry.get("symbol_details", [])),
            imports=list(entry.get("imports", [])),
            dependency_map=list(entry.get("dependency_map", [])),
            test_files=list(entry.get("test_files", [])),
            module_docstring=str(entry.get("module_docstring", "")),
            complexity_score=int(entry.get("complexity_score", 0)),
            git_last_commit=str(entry.get("git_last_commit", "")),
            git_last_author_date=str(entry.get("git_last_author_date", "")),
        )

    def get_cached(self, path: str | Path) -> SemanticSummary | None:
        """Return cached summary if still valid (hash-match), else None."""
        file_path = Path(path)
        if not file_path.is_file():
            return None
        entry = self._index.get(file_path)
        if entry is None:
            return None
        return self._entry_to_summary(entry)

    def module_summary(self, path: str | Path) -> dict[str, Any]:
        """Return a concise dict suitable for CLI display or LLM injection."""
        s = self.get_cached(path) or self.summarize_file(path)
        return {
            "path": s.path,
            "language": s.language,
            "exports": s.exports,
            "symbols": s.symbols[:50],
            "imports": s.imports,
            "dependency_map": s.dependency_map,
            "test_files": s.test_files,
            "lines_total": s.lines_total,
            "ast_summary": s.ast_summary,
            "module_docstring": s.module_docstring,
            "complexity_score": s.complexity_score,
            "content_hash": s.content_hash,
            "git_last_commit": s.git_last_commit,
            "git_last_author_date": s.git_last_author_date,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def symbol_search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Find symbols matching query across all cached files."""
        return self._symbol_index.resolve_symbol(query)[:limit]

    def semantic_search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """BM25-ranked full-text search over cached file summaries."""
        return self._symbol_index.bm25_search(query, limit=limit)

    def change_impact(self, path: str | Path) -> dict[str, Any]:
        """Estimate blast radius of modifying a file (uses reverse dep graph)."""
        # Ensure file is in cache
        fp = Path(path)
        if fp.is_file() and not self._index.get(fp):
            self.summarize_file(fp)
        return self._symbol_index.change_impact(str(path))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_test_files(self, file_path: Path) -> list[str]:
        stem = file_path.stem
        if stem.startswith("test_") or stem.endswith("_test"):
            return []
        root = file_path.parent
        for _ in range(4):
            tests_dir = root / "tests"
            if tests_dir.is_dir():
                matches = list(tests_dir.rglob(f"test_{stem}.py")) + list(
                    tests_dir.rglob(f"*{stem}*test*.py")
                )
                return [str(p) for p in matches[:5]]
            root = root.parent
        return []

    def _load(self) -> dict[str, Any]:
        """Return raw index state dict (backward-compat with engine.py)."""
        return self._index._load()

    def _git_metadata(self, file_path: Path) -> tuple[str, str]:
        """Return (last_commit_sha, authored_datetime_iso) for a file."""
        if Repo is None:
            return "", ""
        try:
            repo = Repo(file_path, search_parent_directories=True)
            wtd = repo.working_tree_dir
            assert wtd is not None
            rel_path = str(file_path.resolve().relative_to(wtd))
            commits = list(repo.iter_commits(paths=rel_path, max_count=1))
            if not commits:
                return "", ""
            commit = commits[0]
            return str(commit.hexsha), commit.authored_datetime.isoformat()
        except Exception:
            return "", ""
