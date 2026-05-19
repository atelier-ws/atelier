"""Deterministic tests for the Phase 5 M18 scale-decision rubric."""

from __future__ import annotations

import atelier.core.service.usage_sync  # noqa: F401

from benchmarks.code_intel.scale_decision_eval import (
    evaluate_default_candidates,
    select_recommended_candidate,
)


def test_scale_decision_eval_scores_candidates_and_verdicts_deterministically() -> None:
    report = evaluate_default_candidates()

    zoekt = report.rows_by_key["zoekt-standalone"]
    src_cli = report.rows_by_key["src-cli"]
    sourcegraph = report.rows_by_key["sourcegraph-self-hosted"]
    scip_mcp = report.rows_by_key["scip-mcp"]

    assert zoekt.score == 9
    assert zoekt.passes is True
    assert src_cli.score == 3
    assert src_cli.passes is False
    assert sourcegraph.score == 6
    assert sourcegraph.passes is False
    assert scip_mcp.score == 2
    assert scip_mcp.passes is False


def test_scale_decision_eval_emits_repo_specific_phase5_answers() -> None:
    report = evaluate_default_candidates()
    decision = report.decision

    assert decision.search_scope == "search"
    assert decision.result_shape == "text"
    assert (
        decision.lifecycle_owner
        == "session-scoped search backend supervisor owned by the MCP/runtime layer"
    )
    assert decision.selected_option_id == "option-a"


def test_scale_decision_eval_defaults_to_search_first_without_symbol_shape_parity() -> None:
    report = evaluate_default_candidates()
    recommendation = select_recommended_candidate(report)

    assert recommendation.key == "zoekt-standalone"
    assert recommendation.repo_answers.search_scope == "search"
    assert recommendation.repo_answers.result_shape == "text"
    assert recommendation.repo_answers.proves_symbol_shape_parity is False
