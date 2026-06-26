#!/usr/bin/env python3
"""Fitness command for explore-ranking swarm.

Outputs benchmark cost_usd as a float to stdout;
exits 1 if the task wasn't solved correctly.

Run from the worktree root::

    uv run python scripts/swarm_explore_fitness.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    worktree_root = Path.cwd()

    # Swarm worktrees don't have git-ignored .env files from the main repo.
    # Walk up to find the main repo root by looking for a known anchor, then
    # symlink .env files so the benchmark container gets the right credentials.
    # Fall back to an environment variable for portability.
    main_repo = os.environ.get("ATELIER_MAIN_REPO")
    if not main_repo:
        # Heuristic: the swarm worktree pool is at <main_repo>-swarm-worktrees/
        # so the main repo is one level up from the pool parent.
        candidate = worktree_root
        for _ in range(6):
            candidate = candidate.parent
            if (candidate / "pyproject.toml").exists() and (candidate / ".git").exists():
                # Exclude the worktree itself
                if candidate != worktree_root:
                    main_repo = str(candidate)
                    break

    if main_repo:
        for rel in ("benchmarks/codebench/.env", "benchmarks/.env", ".env"):
            src = Path(main_repo) / rel
            dst = worktree_root / rel
            if src.is_file() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.symlink_to(src)

    with tempfile.TemporaryDirectory(prefix="swarm_bench_") as outdir:
        env = {**os.environ, "CODEBENCH_CODE_EMBEDDER": "null", "CODEBENCH_MAX_REQUESTS": "150"}
        result = subprocess.run(
            [
                "uv",
                "run",
                "--with",
                "swebench",
                "python",
                "-m",
                "benchmarks.codebench.multiswe_run",
                "--suite",
                "swe-bench-verified",
                "--instances",
                "django__django-12155",
                "-a",
                "atelier",
                "--reps",
                "1",
                "--model",
                "claude-opus-4-8",
                "--out",
                outdir,
            ],
            cwd=str(worktree_root),
            env=env,
            check=False,
        )
        if result.returncode != 0:
            print(f"Benchmark subprocess failed (exit {result.returncode})", file=sys.stderr)
            sys.exit(2)

        results_path = Path(outdir) / "results.jsonl"
        if not results_path.exists():
            print("results.jsonl not found", file=sys.stderr)
            sys.exit(2)

        data = json.loads(results_path.read_text())
        cost: float = data["cost_usd"]
        correct: bool = data["correct"]

    print(f"{cost:.4f}")
    if not correct:
        sys.exit(1)


if __name__ == "__main__":
    main()
