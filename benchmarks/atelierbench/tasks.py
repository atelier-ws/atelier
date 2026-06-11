"""The seven AtelierBench tasks, adapted from kirby88/eval-eval.

Prompts and bundled workspaces are read from a local task-source checkout
(default ``../benchmarks/<repo>/atelierbench-tasks``; override with
``ATELIERBENCH_TASKS_DIR``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

TaskSource: TypeAlias = (  # noqa: UP040
    tuple[Literal["empty"]] | tuple[Literal["repo"], str, str | None] | tuple[Literal["workspace"], str]
)


def atelierbench_tasks_dir() -> Path:
    root = os.environ.get("ATELIERBENCH_TASKS_DIR")
    if root:
        return Path(root)
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root.parent / "benchmarks" / repo_root.name / "atelierbench-tasks"


@dataclass(frozen=True)
class Task:
    id: str
    language: str
    # source kinds: ("empty",) | ("repo", url, commit_or_None) | ("workspace", subdir)
    source: TaskSource
    # rough budget ordering for cheap-first runs
    weight: int  # 1=cheap (no clone) .. 3=heavy (large repo clone+build)
    task_dir: str  # folder name under atelierbench-tasks/tasks/
    # Shell commands run inside the prepared workspace before the agent starts.
    # Each string is passed to subprocess shell=True with the workspace as cwd.
    setup_cmds: tuple[str, ...] = field(default_factory=tuple)

    def prompt_path(self) -> Path:
        task_root = atelierbench_tasks_dir() / "tasks" / self.task_dir
        candidates = (
            "prompt.md",
            "prompt_hard.md",
            "prompt_medium.md",
            "prompt_trivial.md",
        )
        for name in candidates:
            path = task_root / name
            if path.exists():
                return path
        variant_prompts = sorted(task_root.glob("prompt_*.md"))
        if variant_prompts:
            return variant_prompts[0]
        return task_root / "prompt.md"

    def prompt(self) -> str:
        p = self.prompt_path()
        text = p.read_text(encoding="utf-8").strip() if p.exists() else ""
        return text

    def workspace_src(self) -> Path | None:
        if self.source[0] == "workspace":
            return atelierbench_tasks_dir() / "tasks" / self.task_dir / self.source[1]
        return None


TASKS: list[Task] = [
    Task(
        "task1",
        "swift",
        ("empty",),
        1,
        "task1_LRUFileCacheSPec",
        setup_cmds=("swift package --version",),
    ),
    Task(
        "task2",
        "swift",
        ("repo", "https://github.com/maquannene/Track", None),
        2,
        "task2_AddLoggingToCache",
        setup_cmds=("swift package resolve",),
    ),
    Task(
        "task3",
        "rust",
        ("repo", "https://github.com/serde-rs/json", "4f6dbfac79647d032b0997b5ab73022340c6dab7"),
        2,
        "task3_FixJsonParsingBug",
        setup_cmds=("cargo fetch --quiet",),
    ),
    Task(
        "task4",
        "python",
        ("workspace", "workspace"),
        1,
        "task4_WriteTestsForExportFlows",
        setup_cmds=("uv pip install --quiet mitmproxy pytest",),
    ),
    Task(
        "task5",
        "python",
        ("workspace", "workspace"),
        1,
        "task5_RefactorBasedOnTests",
        setup_cmds=("uv pip install --quiet mitmproxy pytest",),
    ),
    Task(
        "task6",
        "typescript",
        (
            "repo",
            "https://github.com/openclaw/openclaw",
            "412811ec19c553a7c249f75d94a13a65b61ea2e6",
        ),
        3,
        "task6_AddFrenchSupportToOpenClaw",
        setup_cmds=("npm ci --prefer-offline --silent 2>/dev/null || npm install --silent",),
    ),
    Task(
        "task7",
        "rust",
        ("repo", "https://github.com/kirby88/codex", "7a393668185da6710425698885731b9af28ca0e0"),
        3,
        "task7_FixCompileBugCodex",
        # Pre-fetch deps but intentionally do NOT install libcap — its absence
        # is the CI bug this task is designed to diagnose and fix.
        setup_cmds=("cargo fetch --quiet 2>/dev/null || true",),
    ),
]

BY_ID = {t.id: t for t in TASKS}
