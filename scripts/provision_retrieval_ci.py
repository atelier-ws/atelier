"""Provision the multi-repository retrieval benchmark on an ephemeral CI host.

The committed pairs file contains the benchmark queries, gold files, upstream
repository prefixes, and snapshot commits, but its ``ws``/``db`` values point to
the machine where it was generated. This script recreates those workspaces and
SQLite indexes locally, then rewrites the same pairs file with runnable paths.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from atelier.core.capabilities.code_context.engine import CodeContextEngine

PAIRS_PATH = Path(
    os.environ.get(
        "FITNESS_PAIRS",
        "benchmarks/codebench/data/bench_pairs_multi.json",
    )
)
CORPUS_ROOT = Path(os.environ.get("RETRIEVAL_CORPUS_ROOT", "/tmp/retrieval-corpus"))
INDEX_ROOT = Path(os.environ.get("RETRIEVAL_INDEX_ROOT", "/tmp/retrieval-indexes"))

UPSTREAM: dict[str, str] = {
    "django__django": "django/django",
    "pytest-dev__pytest": "pytest-dev/pytest",
    "astropy__astropy": "astropy/astropy",
    "sympy__sympy": "sympy/sympy",
    "scikit-learn__scikit-learn": "scikit-learn/scikit-learn",
    "pydata__xarray": "pydata/xarray",
    "matplotlib__matplotlib": "matplotlib/matplotlib",
    "mwaskom__seaborn": "mwaskom/seaborn",
    "pallets__flask": "pallets/flask",
    "psf__requests": "psf/requests",
    "pylint-dev__pylint": "pylint-dev/pylint",
    "sphinx-doc__sphinx": "sphinx-doc/sphinx",
}


def _run(cmd: list[str], *, timeout: int = 1800) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, timeout=timeout)


def _clone_at_snapshot(prefix: str, meta: dict[str, Any]) -> Path:
    repository = UPSTREAM.get(prefix)
    if repository is None:
        raise RuntimeError(f"No upstream repository mapping for {prefix}")

    workspace = CORPUS_ROOT / prefix.replace("/", "_")
    if workspace.exists() and not (workspace / ".git").is_dir():
        shutil.rmtree(workspace)

    if not workspace.exists():
        _run(
            [
                "git",
                "clone",
                "--quiet",
                "--filter=blob:none",
                "--no-checkout",
                "--depth=1",
                f"https://github.com/{repository}.git",
                str(workspace),
            ]
        )

    commit = str(meta.get("base_commit") or "").strip()
    if commit:
        try:
            _run(
                [
                    "git",
                    "-C",
                    str(workspace),
                    "fetch",
                    "--quiet",
                    "--filter=blob:none",
                    "--depth=1",
                    "origin",
                    commit,
                ]
            )
        except subprocess.CalledProcessError:
            # Some servers reject a direct shallow SHA fetch. Fetch reachable
            # history without blobs as a slower but reliable fallback.
            _run(
                [
                    "git",
                    "-C",
                    str(workspace),
                    "fetch",
                    "--quiet",
                    "--filter=blob:none",
                    "origin",
                ],
                timeout=3600,
            )
            _run(["git", "-C", str(workspace), "checkout", "--quiet", "--detach", commit])
        else:
            _run(["git", "-C", str(workspace), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
    else:
        _run(["git", "-C", str(workspace), "checkout", "--quiet", "--detach", "HEAD"])

    return workspace.resolve()


def _symbol_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        return int(connection.execute("SELECT count(*) FROM symbols").fetchone()[0])


def main() -> None:
    if not PAIRS_PATH.is_file():
        raise FileNotFoundError(f"Pairs file not found: {PAIRS_PATH}")

    data = json.loads(PAIRS_PATH.read_text())
    pairs = data.get("pairs")
    repos = data.get("repos")
    if not isinstance(pairs, list) or not isinstance(repos, dict):
        raise ValueError("Pairs JSON must contain list 'pairs' and object 'repos'")

    prefixes = sorted({str(item[2]) for item in pairs if isinstance(item, list) and len(item) >= 3})
    if not prefixes:
        raise ValueError("Pairs JSON contains no repository prefixes")

    CORPUS_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Provisioning {len(prefixes)} repositories: {', '.join(prefixes)}", flush=True)

    for prefix in prefixes:
        raw_meta = repos.get(prefix)
        if not isinstance(raw_meta, dict):
            raise ValueError(f"Missing repository metadata for {prefix}")
        meta: dict[str, Any] = raw_meta

        if prefix == "atelier__atelier":
            workspace = Path.cwd().resolve()
        else:
            workspace = _clone_at_snapshot(prefix, meta)

        db_path = (INDEX_ROOT / f"{prefix.replace('/', '_')}.db").resolve()
        db_path.unlink(missing_ok=True)
        for suffix in ("-shm", "-wal"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)

        print(f"[{prefix}] indexing {workspace} -> {db_path}", flush=True)
        CodeContextEngine(workspace, db_path=db_path, autosync_enabled=False).index_repo()
        if not db_path.is_file():
            raise RuntimeError(f"Index was not created for {prefix}: {db_path}")

        count = _symbol_count(db_path)
        if count <= 0:
            raise RuntimeError(f"Index for {prefix} contains no symbols")
        print(f"[{prefix}] ready: {count} symbols", flush=True)

        meta["ws"] = str(workspace)
        meta["db"] = str(db_path)

    PAIRS_PATH.write_text(json.dumps(data))
    print(f"Rewrote {PAIRS_PATH} with CI-local workspace and index paths", flush=True)


if __name__ == "__main__":
    main()
