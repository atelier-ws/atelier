"""Workspace hygiene snapshot/report for bench-style runs.

File-hygiene verifiers (e.g. ``os.listdir(dir) == [expected_file]``) fail on
leftover scratch outputs even when the solution is correct. Snapshot the tree
before solving, then report new files that look like build/debug residue.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

_SKIP_DIRS = frozenset({".git"})

_SCRATCH_PATTERNS: tuple[str, ...] = (
    "*.o",
    "*.obj",
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*.temp",
    "*.log",
    "*.swp",
    "*.bak",
    "a.out",
    "core",
    "__pycache__/*",
    "build/*",
    "*.egg-info/*",
)


def snapshot_workspace(root: Path) -> frozenset[str]:
    """Relative paths of all files under *root*, excluding VCS internals."""
    if not root.is_dir():
        return frozenset()
    paths: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.split("/", 1)[0] in _SKIP_DIRS:
            continue
        paths.add(rel)
    return frozenset(paths)


def scratch_leftovers(root: Path, before: frozenset[str]) -> list[str]:
    """New files since *before* that match scratch/build-residue patterns."""
    new_paths = snapshot_workspace(root) - before
    flagged = [
        rel
        for rel in new_paths
        if any(
            fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pattern)
            for pattern in _SCRATCH_PATTERNS
        )
    ]
    return sorted(flagged)
