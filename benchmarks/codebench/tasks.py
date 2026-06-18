"""The seven CodeBench tasks.

Prompts and bundled workspaces are read from a local task-source checkout
(default ``../benchmarks/<repo>/codebench-tasks``; override with
``CODEBENCH_TASKS_DIR``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

TaskSource: TypeAlias = (  # noqa: UP040
    tuple[Literal["empty"]]
    | tuple[Literal["repo"], str, str | None]
    | tuple[Literal["workspace"], str]
    | tuple[Literal["path"], str]
)


def codebench_tasks_dir() -> Path:
    root = os.environ.get("CODEBENCH_TASKS_DIR")
    if root:
        return Path(root)
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root.parent / "benchmarks" / repo_root.name / "codebench-tasks"


@dataclass(frozen=True)
class Task:
    id: str
    language: str
    # source kinds: ("empty",) | ("repo", url, commit_or_None) | ("workspace", subdir)
    source: TaskSource
    # rough budget ordering for cheap-first runs
    weight: int  # 1=cheap (no clone) .. 3=heavy (large repo clone+build)
    task_dir: str  # folder name under codebench-tasks/tasks/
    # Shell commands run inside the prepared workspace before the agent starts.
    # Each string is passed to subprocess shell=True with the workspace as cwd.
    setup_cmds: tuple[str, ...] = field(default_factory=tuple)
    # Agent capability this task exercises; selects the per-arm persona
    # (built-in twin vs atelier) and the grader. "code" -> objective verify
    # gate; "explore" -> answer-key overlap grader; "plan" -> overlap + judge.
    capability: str = "code"

    def prompt_path(self) -> Path:
        task_root = codebench_tasks_dir() / "tasks" / self.task_dir
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
            return codebench_tasks_dir() / "tasks" / self.task_dir / self.source[1]
        return None


TASKS: list[Task] = [
    # --- codegraph 7-repo A/B (efficiency-only) ---
    Task(
        "cg_vscode",
        "typescript",
        ("repo", "https://github.com/microsoft/vscode", "be441a4dc809ea2d98fe7903fcdead9eb0ec31e7"),
        3,
        "cg_vscode",
        setup_cmds=(
            'case "$(pwd)" in *_atelier_rep*) /home/pankaj/Projects/leanchain/atelier/.venv/bin/atelier code index --repo-root . || true ;; esac',
        ),
    ),
    Task(
        "cg_excalidraw",
        "typescript",
        ("repo", "https://github.com/excalidraw/excalidraw", "28a9b1711dc0625b8ab5d643dc871810ee13642f"),
        2,
        "cg_excalidraw",
        setup_cmds=(
            'case "$(pwd)" in *_atelier_rep*) /home/pankaj/Projects/leanchain/atelier/.venv/bin/atelier code index --repo-root . || true ;; esac',
        ),
    ),
    Task(
        "cg_django",
        "python",
        ("repo", "https://github.com/django/django", "cd385e6b8c16b51f68c1f220ff09a4cfd679af0c"),
        2,
        "cg_django",
        setup_cmds=(
            'case "$(pwd)" in *_atelier_rep*) /home/pankaj/Projects/leanchain/atelier/.venv/bin/atelier code index --repo-root . || true ;; esac',
        ),
    ),
    Task(
        "cg_tokio",
        "rust",
        ("repo", "https://github.com/tokio-rs/tokio", "7892f6020d9c914a41d0c350693fb71937d43c03"),
        2,
        "cg_tokio",
        setup_cmds=(
            'case "$(pwd)" in *_atelier_rep*) /home/pankaj/Projects/leanchain/atelier/.venv/bin/atelier code index --repo-root . || true ;; esac',
        ),
    ),
    Task(
        "cg_okhttp",
        "java",
        ("repo", "https://github.com/square/okhttp", "6abc678ad07aefe055cb1afb6fd897c34a988eb9"),
        2,
        "cg_okhttp",
        setup_cmds=(
            'case "$(pwd)" in *_atelier_rep*) /home/pankaj/Projects/leanchain/atelier/.venv/bin/atelier code index --repo-root . || true ;; esac',
        ),
    ),
    Task(
        "cg_gin",
        "go",
        ("repo", "https://github.com/gin-gonic/gin", "d75fcd4c9ab260e5225de590f1f0f8c0e0e12d11"),
        1,
        "cg_gin",
        setup_cmds=(
            'case "$(pwd)" in *_atelier_rep*) /home/pankaj/Projects/leanchain/atelier/.venv/bin/atelier code index --repo-root . || true ;; esac',
        ),
    ),
    Task(
        "cg_alamofire",
        "swift",
        ("repo", "https://github.com/Alamofire/Alamofire", "7595cbcf59809f9977c5f6378500de2ad73b7ddb"),
        1,
        "cg_alamofire",
        setup_cmds=(
            'case "$(pwd)" in *_atelier_rep*) /home/pankaj/Projects/leanchain/atelier/.venv/bin/atelier code index --repo-root . || true ;; esac',
        ),
    ),
]

BY_ID = {t.id: t for t in TASKS}
