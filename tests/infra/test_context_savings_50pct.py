"""CI gate: context savings must be >= 50% on the 11-prompt suite (WP-19).

This test is the hard CI gate that proves the >50% context-savings claim
is deterministic and not marketing.  It runs entirely in-process — no
network, no API key, no external services required.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.swe.savings_bench import (
    _SUITE_YAML,
    _load_suite,
    run_savings_bench,
)

# ---------------------------------------------------------------------------
# Primary CI gate
# ---------------------------------------------------------------------------


def test_context_savings_at_least_50_percent_on_11_prompt_suite(tmp_path: Path) -> None:
    """Aggregate input-token reduction must be >= 50% across all 11 prompts."""
    result = run_savings_bench(tmp_path)
    assert result.reduction_pct >= 50.0, (
        f"context savings regressed: {result.reduction_pct:.1f}% < 50%\n"
        f"naive_input={result.total_naive_input}, "
        f"optimized_input={result.total_optimized_input}, "
        f"saved={result.total_tokens_saved}"
    )


# ---------------------------------------------------------------------------
# Suite structure sanity checks
# ---------------------------------------------------------------------------


def test_suite_has_exactly_11_prompts() -> None:
    """The YAML suite must define exactly 11 prompts."""
    entries = _load_suite(_SUITE_YAML)
    assert len(entries) == 11, f"expected 11 prompts, got {len(entries)}"


def test_suite_prompt_ids_are_unique() -> None:
    """Every prompt id must be unique."""
    entries = _load_suite(_SUITE_YAML)
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), f"duplicate prompt ids: {ids}"


def test_suite_all_prompts_have_required_fields() -> None:
    """Every entry must have id, task_type, naive_input_tokens, naive_output_tokens, levers."""
    required = {"id", "task_type", "naive_input_tokens", "naive_output_tokens", "levers"}
    entries = _load_suite(_SUITE_YAML)
    for entry in entries:
        missing = required - set(entry.keys())
        assert not missing, f"prompt {entry.get('id', '?')} missing fields: {missing}"


def test_suite_token_values_are_positive() -> None:
    """All token counts must be positive integers."""
    entries = _load_suite(_SUITE_YAML)
    for entry in entries:
        pid = entry.get("id", "?")
        assert entry["naive_input_tokens"] > 0, f"{pid}: naive_input_tokens must be > 0"
        assert entry["naive_output_tokens"] > 0, f"{pid}: naive_output_tokens must be > 0"
        for lever, saved in entry.get("levers", {}).items():
            assert saved > 0, f"{pid}.{lever}: lever saving must be > 0"


def test_optimized_tokens_never_exceed_naive(tmp_path: Path) -> None:
    """The benchmark must never produce negative token savings (clamped)."""
    result = run_savings_bench(tmp_path)
    for pr in result.prompt_results:
        assert (
            pr.optimized_input_tokens >= 0
        ), f"{pr.id}: optimized_input_tokens is negative ({pr.optimized_input_tokens})"
        assert pr.optimized_input_tokens <= pr.naive_input_tokens, (
            f"{pr.id}: optimized ({pr.optimized_input_tokens}) "
            f"> naive ({pr.naive_input_tokens})"
        )


# ---------------------------------------------------------------------------
# Per-lever attribution
# ---------------------------------------------------------------------------


def test_lever_totals_are_present_and_positive(tmp_path: Path) -> None:
    """All levers that appear in the YAML must surface in lever_totals."""
    result = run_savings_bench(tmp_path)
    assert result.lever_totals, "lever_totals must not be empty"
    for lever, total in result.lever_totals.items():
        assert total > 0, f"lever {lever!r} total must be > 0"


def test_lever_totals_sum_matches_tokens_saved(tmp_path: Path) -> None:
    """Sum of per-lever totals must equal total tokens saved."""
    result = run_savings_bench(tmp_path)
    lever_sum = sum(result.lever_totals.values())
    assert (
        lever_sum == result.total_tokens_saved
    ), f"lever_totals sum ({lever_sum}) != total_tokens_saved ({result.total_tokens_saved})"


# ---------------------------------------------------------------------------
# Result serialisation
# ---------------------------------------------------------------------------


def test_savings_result_to_dict_is_json_serialisable(tmp_path: Path) -> None:
    """SavingsResult.to_dict() must be JSON-serialisable."""
    import json

    result = run_savings_bench(tmp_path)
    payload = result.to_dict()
    dumped = json.dumps(payload)
    reloaded = json.loads(dumped)
    assert reloaded["reduction_pct"] >= 50.0
    assert len(reloaded["prompts"]) == 11


def test_savings_result_reduction_pct_field(tmp_path: Path) -> None:
    """reduction_pct in to_dict must match the property value."""
    result = run_savings_bench(tmp_path)
    d = result.to_dict()
    assert abs(d["reduction_pct"] - result.reduction_pct) < 0.01
