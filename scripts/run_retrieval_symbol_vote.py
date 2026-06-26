"""Run the full retrieval benchmark with the symbol-vote experiment enabled."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    experiment_dir = root / "experiments" / "retrieval_symbol_vote"
    diagnostics = Path("/tmp/atelier_symbol_vote_diagnostics.jsonl")
    diagnostics.unlink(missing_ok=True)

    env = os.environ.copy()
    env["ATELIER_EXPERIMENT_SYMBOL_VOTE"] = "1"
    env["ATELIER_EXPERIMENT_DIAGNOSTICS"] = str(diagnostics)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(experiment_dir) if not existing_pythonpath else str(experiment_dir) + os.pathsep + existing_pythonpath

    command = ["uv", "run", "atelier", "eval", "retrieval", "--full"]
    print(f"[experiment] repo root: {root}", flush=True)
    print(f"[experiment] diagnostics: {diagnostics}", flush=True)
    completed = subprocess.run(command, cwd=root, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
