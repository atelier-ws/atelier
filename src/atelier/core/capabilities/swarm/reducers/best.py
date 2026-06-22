"""The ``best`` reducer: rank candidates by a fitness, accept the top one(s).

Two fitness sources:
- **heuristic** -- the run-quality scorer (``_score_child`` / ``rank_children``)
  used today both as each child's score and as the deterministic overlap-aware
  fallback selection. Moved here verbatim from ``capability.py``.
- **measured** -- a project-supplied ``FitnessSpec`` command run per worktree
  (added in Phase 2).

The heuristic scorer lives here so there is a single source of truth shared by
the per-child score (``run_child_once``) and the deterministic fallback used by
the ``merge`` reducer when no semantic backend is available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atelier.core.capabilities.swarm.models import SwarmChildState, SwarmValidationCheck

if TYPE_CHECKING:
    from atelier.core.capabilities.swarm.models import SwarmWaveEvaluation
    from atelier.core.capabilities.swarm.reducers.base import WaveContext


def _is_structural_validation(check: SwarmValidationCheck) -> bool:
    return check.name.startswith("structural-")


def _has_non_structural_passing_validation(child: SwarmChildState) -> bool:
    return any(item.passed and not _is_structural_validation(item) for item in child.validation_results)


def _score_child(child: SwarmChildState) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    if child.status == "success":
        score += 100.0
        reasons.append("+100 successful child run")
    elif child.status == "stopped":
        score -= 30.0
        reasons.append("-30 stopped before completion")
    else:
        score -= 60.0
        reasons.append("-60 failed child run")
    validation_passes = sum(1 for item in child.validation_results if item.passed)
    validation_failures = sum(1 for item in child.validation_results if not item.passed)
    if not child.validation_results:
        score -= 12.0
        reasons.append("-12 no validation evidence")
    only_structural_validation = bool(child.validation_results) and all(
        _is_structural_validation(item) for item in child.validation_results
    )
    if validation_passes:
        delta = validation_passes * (3.0 if only_structural_validation else 15.0)
        score += delta
        if only_structural_validation:
            reasons.append(f"+{delta:.1f} structural validation checks passed")
        else:
            reasons.append(f"+{delta:.1f} validation checks passed")
    if validation_failures:
        delta = validation_failures * 25.0
        score -= delta
        reasons.append(f"-{delta:.1f} validation checks failed")
    if child.files_changed:
        score += 5.0
        reasons.append("+5 produced a git diff")
    else:
        score -= 10.0
        reasons.append("-10 no files changed")
    file_penalty = min(len(child.files_changed), 50) * 0.2
    if file_penalty:
        score -= file_penalty
        reasons.append(f"-{file_penalty:.1f} changed-file penalty")
    if child.cost_usd > 0:
        cost_penalty = child.cost_usd * 10.0
        score -= cost_penalty
        reasons.append(f"-{cost_penalty:.2f} cost penalty")
    if child.duration_seconds > 0:
        duration_penalty = min(child.duration_seconds / 120.0, 10.0)
        score -= duration_penalty
        reasons.append(f"-{duration_penalty:.2f} duration penalty")
    return round(score, 3), reasons


def rank_children(children: list[SwarmChildState]) -> list[SwarmChildState]:
    for child in children:
        score, breakdown = _score_child(child)
        child.score = score
        child.score_breakdown = breakdown
    return sorted(
        children,
        key=lambda item: (
            item.score if item.score is not None else float("-inf"),
            sum(1 for check in item.validation_results if check.passed),
            -(len(item.files_changed)),
        ),
        reverse=True,
    )


class BestReducer:
    """Heuristic best-of-N selection.

    Phase 1: the heuristic ``best`` is exactly the deterministic, overlap-aware
    fallback selection already used by the ``merge`` reducer -- it ranks by
    ``_score_child`` and accepts the strongest non-duplicate, non-conflicting
    candidate(s). Reusing it keeps a single source of truth and identical
    behavior. Phase 2 swaps the heuristic score for a measured ``FitnessSpec``
    when the job supplies one.
    """

    name = "best"

    def reduce(
        self,
        candidates: list[SwarmChildState],
        ctx: WaveContext,
    ) -> SwarmWaveEvaluation:
        from atelier.core.capabilities.swarm.capability import _fallback_wave_evaluation

        return _fallback_wave_evaluation(ctx.state, candidates)


__all__ = [
    "BestReducer",
    "_has_non_structural_passing_validation",
    "_is_structural_validation",
    "_score_child",
    "rank_children",
]
