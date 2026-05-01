"""Rescue strategy catalogue and matching logic."""

from __future__ import annotations

# Ordered rescue strategies per loop type.  Earlier entries are preferred.
_RESCUE_MAP: dict[str, list[str]] = {
    "patch_revert_cycle": [
        "abandon_current_approach_and_redesign",
        "read_full_file_before_next_edit",
        "ask_user_for_clarification",
    ],
    "search_read_loop": [
        "switch_to_semantic_symbol_search",
        "use_cached_module_summary",
        "escalate_to_broader_context_scan",
    ],
    "hypothesis_loop": [
        "enumerate_and_track_tried_approaches",
        "switch_to_different_tool_or_strategy",
        "ask_user_for_targeted_hint",
    ],
    "cascade_failure": [
        "fix_root_cause_error_first",
        "isolate_minimal_reproduction",
        "rollback_to_last_known_good_state",
    ],
    "budget_burn": [
        "emit_partial_result_and_request_continuation",
        "reduce_granularity_of_approach",
        "stop_and_summarise_progress",
    ],
    "stall": [
        "commit_to_one_approach_and_write_output",
        "reduce_scope_to_smallest_shippable_unit",
        "ask_user_to_confirm_direction",
    ],
    "second_guess_loop": [
        "commit_to_current_best_hypothesis",
        "set_a_decision_deadline_and_proceed",
        "enumerate_options_once_then_pick_top",
    ],
}

# Static base confidence per strategy category (higher = more likely to break the loop).
# Used when no runtime tracking data is available.
_STRATEGY_BASE_CONFIDENCE: dict[str, float] = {
    "abandon_current_approach_and_redesign": 0.85,
    "read_full_file_before_next_edit": 0.70,
    "ask_user_for_clarification": 0.60,
    "switch_to_semantic_symbol_search": 0.75,
    "use_cached_module_summary": 0.65,
    "escalate_to_broader_context_scan": 0.55,
    "enumerate_and_track_tried_approaches": 0.80,
    "switch_to_different_tool_or_strategy": 0.75,
    "ask_user_for_targeted_hint": 0.65,
    "fix_root_cause_error_first": 0.90,
    "isolate_minimal_reproduction": 0.80,
    "rollback_to_last_known_good_state": 0.70,
    "emit_partial_result_and_request_continuation": 0.75,
    "reduce_granularity_of_approach": 0.70,
    "stop_and_summarise_progress": 0.60,
    "commit_to_one_approach_and_write_output": 0.85,
    "reduce_scope_to_smallest_shippable_unit": 0.80,
    "ask_user_to_confirm_direction": 0.65,
    "commit_to_current_best_hypothesis": 0.80,
    "set_a_decision_deadline_and_proceed": 0.70,
    "enumerate_options_once_then_pick_top": 0.75,
}

_DEFAULT_STRATEGIES = [
    "step_back_and_re_read_task",
    "ask_user_for_more_context",
]


def match_rescue(loop_types: list[str]) -> list[str]:
    """Return a deduplicated, ordered list of rescue strategies for the detected loop types."""
    seen: set[str] = set()
    strategies: list[str] = []
    for lt in loop_types:
        for s in _RESCUE_MAP.get(lt, _DEFAULT_STRATEGIES):
            if s not in seen:
                seen.add(s)
                strategies.append(s)
    if not strategies:
        strategies = list(_DEFAULT_STRATEGIES)
    return strategies


def scored_rescue(
    loop_types: list[str],
    *,
    adaptive_scores: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    Return rescue strategy -> confidence score mappings.

    If *adaptive_scores* are provided (e.g., from a river EWMean tracker),
    they are blended with the static base confidence (50/50 blend).
    """
    strategies = match_rescue(loop_types)
    result: dict[str, float] = {}
    for s in strategies:
        base = _STRATEGY_BASE_CONFIDENCE.get(s, 0.5)
        if adaptive_scores and s in adaptive_scores:
            score = 0.5 * base + 0.5 * adaptive_scores[s]
        else:
            score = base
        result[s] = round(score, 3)
    return result
