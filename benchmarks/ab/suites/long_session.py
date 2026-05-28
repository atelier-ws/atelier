"""Long-session benchmark suite — LS-01.

Three task cuts at 50-, 100-, and 200-turn depths requiring multi-step
context recall across the conversation lifetime.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# LS-01: tasks at 50/100/200-turn cuts  —————————————————————————————————


@dataclass(frozen=True)
class LongSessionTask:
    task_id: str
    turn_cut: int
    description: str
    setup_facts: list[str] = field(default_factory=list)


TASKS: list[LongSessionTask] = [
    LongSessionTask(
        task_id="ls-recall-50",
        turn_cut=50,
        description="50-turn session: recall 3 facts seeded in turn 1 (project_name, repo_url, target_language)",
        setup_facts=["project_name", "repo_url", "target_language"],
    ),
    LongSessionTask(
        task_id="ls-recall-100",
        turn_cut=100,
        description=(
            "100-turn session: recall 5 facts seeded in turn 1 "
            "(project_name, repo_url, target_language, test_framework, deploy_target)"
        ),
        setup_facts=["project_name", "repo_url", "target_language", "test_framework", "deploy_target"],
    ),
    LongSessionTask(
        task_id="ls-recall-200",
        turn_cut=200,
        description=("200-turn session: recall 5 facts + consistency across 10 mid-session checkpoints"),
        setup_facts=["project_name", "repo_url", "target_language", "test_framework", "deploy_target"],
    ),
]

TASK_IDS: list[str] = [t.task_id for t in TASKS]

_TASK_MAP: dict[str, LongSessionTask] = {t.task_id: t for t in TASKS}


def get_task(task_id: str) -> LongSessionTask:
    """Return task by ID, raising KeyError if not found."""
    if task_id not in _TASK_MAP:
        raise KeyError(f"Unknown long-session task: {task_id!r}")
    return _TASK_MAP[task_id]


def load_tasks(n_tasks: int | None = None) -> list[str]:
    """Return task IDs, optionally limited to first n_tasks (LS-01)."""
    ids = TASK_IDS
    if n_tasks is not None:
        ids = ids[:n_tasks]
    return list(ids)
