"""Tests for V2 monitors (SecondGuessing, BudgetExhaustion)."""

from __future__ import annotations

from atelier.core.foundation.monitors import (
    BudgetExhaustion,
    SecondGuessing,
    SessionState,
    default_monitors,
)


def test_second_guessing_detects_edit_revert_edit_cycle() -> None:
    state = SessionState(
        file_events=[
            ("a.py", "edit"),
            ("a.py", "revert"),
            ("a.py", "edit"),
        ]
    )
    alert = SecondGuessing().check(state, [])
    assert alert is not None
    assert alert.severity == "medium"
    assert "a.py" in alert.message


def test_second_guessing_no_alert_without_revert() -> None:
    state = SessionState(file_events=[("a.py", "edit"), ("a.py", "edit")])
    assert SecondGuessing().check(state, []) is None


def test_budget_exhaustion_fires_on_tool_calls() -> None:
    state = SessionState(tool_calls=[("t", "s")] * 6, budget_max_tool_calls=5)
    alert = BudgetExhaustion().check(state, [])
    assert alert is not None
    assert "exceeds budget" in alert.message


def test_budget_exhaustion_fires_on_repeated_command() -> None:
    state = SessionState(
        command_results=[("ls", True, "")] * 4,
        budget_max_repeated_commands=3,
    )
    alert = BudgetExhaustion().check(state, [])
    assert alert is not None


def test_budget_exhaustion_fires_on_estimated_tokens() -> None:
    state = SessionState(estimated_tokens=200_000, budget_max_estimated_tokens=100_000)
    alert = BudgetExhaustion().check(state, [])
    assert alert is not None


def test_default_monitors_list_includes_v2() -> None:
    names = {type(m).__name__ for m in default_monitors()}
    assert "SecondGuessing" in names
    assert "BudgetExhaustion" in names
