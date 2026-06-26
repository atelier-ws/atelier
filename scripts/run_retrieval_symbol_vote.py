"""Run the full retrieval benchmark with the retrieval experiment enabled."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _norm(path: str) -> str:
    return (path or "").replace("\\", "/")


def _rank(files: list[str], gold: list[str]) -> int | None:
    normalized = [_norm(path) for path in gold]
    for index, file_path in enumerate(files, 1):
        if any(_norm(file_path).endswith(target) for target in normalized):
            return index
    return None


def _report_topk(root: Path, diagnostics: Path) -> None:
    """Evaluate hit@1/2/3 after the run; never feeds labels into retrieval."""
    if not diagnostics.exists():
        return
    try:
        from atelier.core.foundation.paths import workspace_key

        data = json.loads((root / "benchmarks/codebench/data/bench_pairs_multi.json").read_text())
        repo_by_id = {
            str(workspace_key(Path(meta["ws"]).resolve())): prefix
            for prefix, meta in data["repos"].items()
        }
        files_by_query: dict[tuple[str, str], list[str]] = {}
        for line in diagnostics.read_text().splitlines():
            if not line.strip():
                continue
            record: dict[str, Any] = json.loads(line)
            prefix = repo_by_id.get(str(record.get("repo") or ""))
            query = str(record.get("query") or "")
            final = record.get("final")
            if prefix and query and isinstance(final, list):
                files_by_query[(prefix, query)] = [str(path) for path in final]

        aggregate = {"h1": 0, "h2": 0, "h3": 0, "n": 0}
        by_repo: dict[str, dict[str, int]] = {}
        for query, task_id, prefix in data["pairs"]:
            gold = data["true_map"].get(task_id)
            if not gold:
                continue
            rank = _rank(files_by_query.get((prefix, query), []), gold)
            repo = by_repo.setdefault(prefix, {"h1": 0, "h2": 0, "h3": 0, "n": 0})
            for bucket in (aggregate, repo):
                bucket["n"] += 1
                bucket["h1"] += int(rank == 1)
                bucket["h2"] += int(rank is not None and rank <= 2)
                bucket["h3"] += int(rank is not None and rank <= 3)

        def rates(bucket: dict[str, int]) -> dict[str, float | int]:
            count = max(1, bucket["n"])
            return {
                "hit1": round(bucket["h1"] / count, 4),
                "hit2": round(bucket["h2"] / count, 4),
                "hit3": round(bucket["h3"] / count, 4),
                "n": bucket["n"],
            }

        report = {
            "experiment_topk": rates(aggregate),
            "by_repo": {prefix: rates(bucket) for prefix, bucket in sorted(by_repo.items())},
            "targets": {"hit1": 0.8, "hit2": 0.9, "hit3": 1.0},
        }
        print("[experiment-topk] " + json.dumps(report, sort_keys=True), flush=True)
    except Exception as exc:
        print(f"[experiment-topk] unable to calculate hit@2: {exc}", flush=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    experiment_dir = root / "experiments" / "retrieval_symbol_vote"
    diagnostics = Path("/tmp/atelier_symbol_vote_diagnostics.jsonl")
    diagnostics.unlink(missing_ok=True)

    env = os.environ.copy()
    env["ATELIER_EXPERIMENT_SYMBOL_VOTE"] = "1"
    env["ATELIER_EXPERIMENT_DIAGNOSTICS"] = str(diagnostics)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(experiment_dir)
        if not existing_pythonpath
        else str(experiment_dir) + os.pathsep + existing_pythonpath
    )

    command = ["uv", "run", "atelier", "eval", "retrieval", "--full"]
    print(f"[experiment] repo root: {root}", flush=True)
    print(f"[experiment] diagnostics: {diagnostics}", flush=True)
    completed = subprocess.run(command, cwd=root, env=env, check=False)
    _report_topk(root, diagnostics)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
