"""Tests for the explore/explore_skeleton families added to the external benchmark matrix."""

from __future__ import annotations

from benchmarks.mcp_tools.external_matrix_cases import (
    DEFAULT_CASE_QUOTAS,
    SymbolFact,
    _affix_tokens,
    _sibling_family_facts,
)


def test_new_explore_families_registered() -> None:
    assert "explore" in DEFAULT_CASE_QUOTAS
    assert "explore_skeleton" in DEFAULT_CASE_QUOTAS


def test_affix_tokens_match_engine_heuristic() -> None:
    assert _affix_tokens("AlphaEmbedder") == ["embedder", "alpha"]
    assert _affix_tokens("calculate_total") == ["total", "calculate"]
    assert _affix_tokens("get") == []


def test_sibling_family_facts_mines_three_member_family() -> None:
    symbols = [
        SymbolFact(
            name=f"{prefix}Embedder",
            qualified_name=f"{prefix}Embedder",
            path=f"src/{prefix.lower()}.py",
            line=1,
            kind="class",
        )
        for prefix in ("Alpha", "Beta", "Gamma")
    ]
    families = _sibling_family_facts(symbols)
    assert ("embedder", ("src/alpha.py", "src/beta.py", "src/gamma.py")) in families


def test_sibling_family_facts_ignores_under_three() -> None:
    symbols = [
        SymbolFact(
            name=f"{prefix}Resolver",
            qualified_name=f"{prefix}Resolver",
            path=f"src/{prefix.lower()}.py",
            line=1,
            kind="class",
        )
        for prefix in ("Alpha", "Beta")
    ]
    assert _sibling_family_facts(symbols) == []
