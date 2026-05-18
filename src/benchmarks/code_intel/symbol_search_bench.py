"""Deterministic smoke benchmark for Phase 1 symbol-search retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atelier.core.capabilities.code_context import CodeContextEngine


@dataclass
class SymbolSearchBenchResult:
    """Deterministic summary for the M0 symbol-search smoke harness."""

    query: str
    budget_tokens: int
    result_count: int
    uncached_total_tokens: int
    cached_total_tokens: int
    uncached_tokens_saved: int
    cached_tokens_saved: int
    uncached_cache_hit: bool
    cached_cache_hit: bool
    uncached_provenance: str
    cached_provenance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "budget_tokens": self.budget_tokens,
            "result_count": self.result_count,
            "uncached_total_tokens": self.uncached_total_tokens,
            "cached_total_tokens": self.cached_total_tokens,
            "uncached_tokens_saved": self.uncached_tokens_saved,
            "cached_tokens_saved": self.cached_tokens_saved,
            "uncached_cache_hit": self.uncached_cache_hit,
            "cached_cache_hit": self.cached_cache_hit,
            "uncached_provenance": self.uncached_provenance,
            "cached_provenance": self.cached_provenance,
        }


def _write_fixture_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "orders.py").write_text(
        "class OrderService:\n"
        "    def calculate_total(self, items: list[int]) -> int:\n"
        "        return sum(items)\n"
        "\n"
        "def helper() -> OrderService:\n"
        "    return OrderService()\n",
        encoding="utf-8",
    )
    (root / "src" / "checkout.py").write_text(
        "from src.orders import OrderService\n\n"
        "def checkout(items: list[int]) -> int:\n"
        "    return OrderService().calculate_total(items)\n",
        encoding="utf-8",
    )


def run_symbol_search_bench(
    work_dir: Path | None = None,
    *,
    query: str = "OrderService",
    budget_tokens: int = 255,
) -> SymbolSearchBenchResult:
    """Run a deterministic two-call code-search smoke benchmark."""

    bench_root = (work_dir or Path.cwd()) / "code_intel_symbol_search"
    repo_root = bench_root / "fixture_repo"
    db_path = bench_root / "code_context.sqlite"
    _write_fixture_repo(repo_root)

    engine = CodeContextEngine(repo_root, db_path=db_path)
    first = engine.tool_search(query, limit=5, budget_tokens=budget_tokens)
    second = engine.tool_search(query, limit=5, budget_tokens=budget_tokens)

    return SymbolSearchBenchResult(
        query=query,
        budget_tokens=budget_tokens,
        result_count=len(first.get("items", [])),
        uncached_total_tokens=int(first.get("total_tokens", 0) or 0),
        cached_total_tokens=int(second.get("total_tokens", 0) or 0),
        uncached_tokens_saved=int(first.get("tokens_saved", 0) or 0),
        cached_tokens_saved=int(second.get("tokens_saved", 0) or 0),
        uncached_cache_hit=bool(first.get("cache_hit")),
        cached_cache_hit=bool(second.get("cache_hit")),
        uncached_provenance=str(first.get("provenance") or ""),
        cached_provenance=str(second.get("provenance") or ""),
    )


__all__ = ["SymbolSearchBenchResult", "run_symbol_search_bench"]
