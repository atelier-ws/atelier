"""Run the full retrieval benchmark with the symbol-vote experiment enabled."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    experiment_dir = root / "experiments" / "retrieval_symbol_vote"
    diagnostics = Path(os.environ.get("ATELIER_EXPERIMENT_DIAGNOSTICS", "/tmp/atelier_symbol_vote_diagnostics.jsonl"))
    diagnostics.unlink(missing_ok=True)

    env = os.environ.copy()
    env["ATELIER_EXPERIMENT_SYMBOL_VOTE"] = "1"
    env["ATELIER_EXPERIMENT_DIAGNOSTICS"] = str(diagnostics)
    env["PYTHONPATH"] = str(experiment_dir) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    command = ["uv", "run", "atelier", "eval", "retrieval", "--full", *sys.argv[1:]]
    print(f"[experiment] commit branch: bench", flush=True)
    print(f"[experiment] diagnostics: {diagnostics}", flush=True)
    print(f"[experiment] command: {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=root, env=env, check=False)
    print(f"[experiment] diagnostics written to {diagnostics}", flush=True)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
