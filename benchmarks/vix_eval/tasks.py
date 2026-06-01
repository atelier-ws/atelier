"""The 7 vix-eval tasks, ported faithfully from kirby88/vix-eval.

Prompts and bundled workspaces are read from a local checkout of vix-eval
(default ``../benchmarks/<repo>/vix-eval``; override with ``VIX_EVAL_DIR``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

TaskSource: TypeAlias = (  # noqa: UP040
    tuple[Literal["empty"]] | tuple[Literal["repo"], str, str | None] | tuple[Literal["workspace"], str]
)


def vix_eval_dir() -> Path:
    root = os.environ.get("VIX_EVAL_DIR")
    if root:
        return Path(root)
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root.parent / "benchmarks" / repo_root.name / "vix-eval"


@dataclass(frozen=True)
class Task:
    id: str
    language: str
    # source kinds: ("empty",) | ("repo", url, commit_or_None) | ("workspace", subdir)
    source: TaskSource
    # rough budget ordering for cheap-first runs
    weight: int  # 1=cheap (no clone) .. 3=heavy (large repo clone+build)
    task_dir: str  # folder name under vix-eval/tasks/

    def prompt_path(self) -> Path:
        task_root = vix_eval_dir() / "tasks" / self.task_dir
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
            return vix_eval_dir() / "tasks" / self.task_dir / self.source[1]
        return None


TASKS: list[Task] = [
    Task("task1", "swift", ("empty",), 1, "task1_LRUFileCacheSPec"),
    Task(
        "task2",
        "swift",
        ("repo", "https://github.com/maquannene/Track", None),
        2,
        "task2_AddLoggingToCache",
    ),
    Task(
        "task3",
        "rust",
        ("repo", "https://github.com/serde-rs/json", "4f6dbfac79647d032b0997b5ab73022340c6dab7"),
        2,
        "task3_FixJsonParsingBug",
    ),
    Task("task4", "python", ("workspace", "workspace"), 1, "task4_WriteTestsForExportFlows"),
    Task("task5", "python", ("workspace", "workspace"), 1, "task5_RefactorBasedOnTests"),
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
    ),
    Task(
        "task7",
        "rust",
        ("repo", "https://github.com/kirby88/codex", "7a393668185da6710425698885731b9af28ca0e0"),
        3,
        "task7_FixCompileBugCodex",
    ),
]

BY_ID = {t.id: t for t in TASKS}
