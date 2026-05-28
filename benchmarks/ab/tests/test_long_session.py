"""Tests for ab.suites.long_session — LS-01."""

from ab.suites.long_session import TASK_IDS, TASKS, get_task, load_tasks


def test_three_tasks_defined_ls01():
    """LS-01: exactly 3 tasks at 50/100/200 turn cuts."""
    assert len(TASKS) == 3
    cuts = [t.turn_cut for t in TASKS]
    assert cuts == [50, 100, 200]


def test_task_ids_unique():
    assert len(set(TASK_IDS)) == len(TASK_IDS)


def test_get_task_returns_correct_task():
    task = get_task("ls-recall-50")
    assert task.turn_cut == 50
    assert "project_name" in task.setup_facts


def test_get_task_raises_for_unknown():
    try:
        get_task("nonexistent")
        raise AssertionError("should have raised KeyError")
    except KeyError:
        pass


def test_load_tasks_returns_all():
    assert load_tasks() == TASK_IDS


def test_load_tasks_respects_n_tasks():
    assert load_tasks(2) == TASK_IDS[:2]
    assert load_tasks(1) == [TASK_IDS[0]]


def test_tasks_have_setup_facts():
    """LS-01: tasks define setup_facts for recall measurement."""
    for task in TASKS:
        assert len(task.setup_facts) >= 3, f"{task.task_id} needs at least 3 setup facts"


def test_200_turn_task_has_consistency_mention():
    task = get_task("ls-recall-200")
    assert "consistency" in task.description.lower()
