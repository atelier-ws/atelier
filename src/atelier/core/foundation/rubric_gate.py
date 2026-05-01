"""Rubric gate — verify agent output against domain-specific required checks."""

from __future__ import annotations

from collections.abc import Mapping

from atelier.core.foundation.models import (
    Rubric,
    RubricCheckOutcome,
    RubricResult,
)


def run_rubric(
    rubric: Rubric,
    checks: Mapping[str, bool | None],
) -> RubricResult:
    """Evaluate a result against a rubric.

    Args:
        rubric: The rubric to enforce.
        checks: Mapping of check_name -> outcome.
            - True  → pass
            - False → fail
            - None or missing key → missing
    """
    outcomes: list[RubricCheckOutcome] = []
    blocked = False
    warned = False

    # Required checks first.
    for name in rubric.required_checks:
        result = checks.get(name)
        if result is True:
            outcomes.append(RubricCheckOutcome(name=name, status="pass"))
        elif result is False:
            outcomes.append(
                RubricCheckOutcome(name=name, status="fail", detail="Required check failed.")
            )
            if name in rubric.block_if_missing:
                blocked = True
            else:
                warned = True
        else:
            outcomes.append(
                RubricCheckOutcome(
                    name=name, status="missing", detail="Required check not reported."
                )
            )
            if name in rubric.block_if_missing:
                blocked = True
            else:
                warned = True

    # Optional warning checks.
    for name in rubric.warning_checks:
        result = checks.get(name)
        if result is True:
            outcomes.append(RubricCheckOutcome(name=name, status="pass"))
        elif result is False:
            outcomes.append(RubricCheckOutcome(name=name, status="warn"))
            warned = True
        else:
            outcomes.append(RubricCheckOutcome(name=name, status="missing"))
            warned = True

    escalations: list[str] = []
    for cond in rubric.escalation_conditions:
        if checks.get(cond):
            escalations.append(cond)

    if escalations:
        status: str = "escalate"
    elif blocked:
        status = "blocked"
    elif warned:
        status = "warn"
    else:
        status = "pass"

    return RubricResult(
        rubric_id=rubric.id,
        status=status,  # type: ignore[arg-type]
        outcomes=outcomes,
        escalations=escalations,
    )


def load_packaged_rubrics() -> list[Rubric]:
    """Load all rubrics shipped with the package."""
    # TODO: Implement actual loading from package resources
    return []
