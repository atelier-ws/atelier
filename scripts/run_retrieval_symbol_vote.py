"""Run the full retrieval benchmark and report actual plus oracle top-k metrics."""

from __future__ import annotations

import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def _norm(path: str) -> str:
    return (path or "").replace("\\", "/")


def _rank(files: Iterable[str], gold: Iterable[str]) -> int | None:
    normalized = [_norm(path) for path in gold]
    for index, file_path in enumerate(files, 1):
        candidate = _norm(str(file_path))
        if any(candidate.endswith(target) for target in normalized):
            return index
    return None


def _empty_bucket() -> dict[str, int | float]:
    return {"rr": 0.0, "h1": 0, "h2": 0, "h3": 0, "n": 0}


def _add_rank(bucket: dict[str, int | float], rank: int | None) -> None:
    bucket["n"] = int(bucket["n"]) + 1
    bucket["rr"] = float(bucket["rr"]) + (1.0 / rank if rank else 0.0)
    bucket["h1"] = int(bucket["h1"]) + int(rank == 1)
    bucket["h2"] = int(bucket["h2"]) + int(rank is not None and rank <= 2)
    bucket["h3"] = int(bucket["h3"]) + int(rank is not None and rank <= 3)


def _rates(bucket: dict[str, int | float]) -> dict[str, int | float]:
    count = max(1, int(bucket["n"]))
    return {
        "mrr": round(float(bucket["rr"]) / count, 4),
        "hit1": round(int(bucket["h1"]) / count, 4),
        "hit2": round(int(bucket["h2"]) / count, 4),
        "hit3": round(int(bucket["h3"]) / count, 4),
        "n": int(bucket["n"]),
    }


def _empty_recall_bucket() -> dict[str, int]:
    return {"r3": 0, "r10": 0, "r50": 0, "all": 0, "n": 0}


def _add_recall(bucket: dict[str, int], rank: int | None) -> None:
    bucket["n"] += 1
    bucket["r3"] += int(rank is not None and rank <= 3)
    bucket["r10"] += int(rank is not None and rank <= 10)
    bucket["r50"] += int(rank is not None and rank <= 50)
    bucket["all"] += int(rank is not None)


def _recall_rates(bucket: dict[str, int]) -> dict[str, int | float]:
    count = max(1, bucket["n"])
    return {
        "recall3": round(bucket["r3"] / count, 4),
        "recall10": round(bucket["r10"] / count, 4),
        "recall50": round(bucket["r50"] / count, 4),
        "recall_all": round(bucket["all"] / count, 4),
        "n": bucket["n"],
    }


def _interleaved_union(channels: dict[str, list[str]], limit: int = 500) -> list[str]:
    """Round-robin union without using labels; useful as a diagnostic ordering."""
    ordered_names = [
        name
        for name in (
            "baseline",
            "fielded",
            "zoekt",
            "exact",
            "anchors",
            "line",
            "semantic",
            "structural",
        )
        if name in channels
    ]
    output: list[str] = []
    seen: set[str] = set()
    depth = 0
    while len(output) < limit:
        added = False
        for name in ordered_names:
            files = channels[name]
            if depth >= len(files):
                continue
            file_path = str(files[depth])
            if file_path and file_path not in seen:
                seen.add(file_path)
                output.append(file_path)
                added = True
                if len(output) >= limit:
                    break
        if not added and all(depth >= len(channels[name]) for name in ordered_names):
            break
        depth += 1
    return output


def _report_metrics(root: Path, diagnostics: Path) -> None:
    """Evaluate diagnostics after retrieval; labels never enter the retriever."""
    if not diagnostics.exists():
        print("[experiment-analysis] diagnostics file missing", flush=True)
        return

    try:
        data = json.loads(
            (root / "benchmarks/codebench/data/bench_pairs_multi.json").read_text()
        )
        repo_by_root = {
            str(Path(meta["ws"]).resolve()): prefix
            for prefix, meta in data["repos"].items()
        }

        records: dict[tuple[str, str], dict[str, Any]] = {}
        malformed = 0
        versions: dict[str, int] = defaultdict(int)
        for line in diagnostics.read_text().splitlines():
            if not line.strip():
                continue
            try:
                record: dict[str, Any] = json.loads(line)
            except Exception:
                malformed += 1
                continue
            version = str(record.get("version") or "unknown")
            versions[version] += 1
            repo_root = str(record.get("repo_root") or "")
            prefix = repo_by_root.get(str(Path(repo_root).resolve())) if repo_root else None
            query = str(record.get("query") or "")
            if prefix and query:
                records[(prefix, query)] = record

        actual = _empty_bucket()
        actual_by_repo: dict[str, dict[str, int | float]] = {}
        channel_recall: dict[str, dict[str, int]] = defaultdict(_empty_recall_bucket)
        channel_by_repo: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(_empty_recall_bucket)
        )
        oracle_best = _empty_recall_bucket()
        oracle_best_by_repo: dict[str, dict[str, int]] = defaultdict(_empty_recall_bucket)
        interleaved = _empty_recall_bucket()
        interleaved_by_repo: dict[str, dict[str, int]] = defaultdict(_empty_recall_bucket)
        missing_records = 0

        for query, task_id, prefix in data["pairs"]:
            gold = data["true_map"].get(task_id)
            if not gold:
                continue
            record = records.get((prefix, query))
            if record is None:
                missing_records += 1
                final: list[str] = []
                channels: dict[str, list[str]] = {}
            else:
                final = [str(path) for path in record.get("final", [])]
                raw_channels = record.get("channels")
                channels = {
                    str(name): [str(path) for path in paths]
                    for name, paths in raw_channels.items()
                    if isinstance(paths, list)
                } if isinstance(raw_channels, dict) else {}

            actual_rank = _rank(final, gold)
            _add_rank(actual, actual_rank)
            repo_bucket = actual_by_repo.setdefault(prefix, _empty_bucket())
            _add_rank(repo_bucket, actual_rank)

            best_rank: int | None = None
            for name, files in channels.items():
                rank = _rank(files, gold)
                _add_recall(channel_recall[name], rank)
                _add_recall(channel_by_repo[prefix][name], rank)
                if rank is not None:
                    best_rank = rank if best_rank is None else min(best_rank, rank)
            _add_recall(oracle_best, best_rank)
            _add_recall(oracle_best_by_repo[prefix], best_rank)

            union_files = _interleaved_union(channels)
            union_rank = _rank(union_files, gold)
            _add_recall(interleaved, union_rank)
            _add_recall(interleaved_by_repo[prefix], union_rank)

        actual_rates = _rates(actual)
        targets = {"hit1": 0.8, "hit2": 0.9, "hit3": 1.0}
        report = {
            "version_counts": dict(sorted(versions.items())),
            "records": len(records),
            "missing_records": missing_records,
            "malformed_lines": malformed,
            "actual": actual_rates,
            "targets": targets,
            "passes": {
                "hit1": float(actual_rates["hit1"]) > targets["hit1"],
                "hit2": float(actual_rates["hit2"]) > targets["hit2"],
                "hit3": float(actual_rates["hit3"]) >= targets["hit3"],
            },
            "oracle_best_channel": _recall_rates(oracle_best),
            "interleaved_union": _recall_rates(interleaved),
            "channel_recall": {
                name: _recall_rates(bucket)
                for name, bucket in sorted(channel_recall.items())
            },
            "by_repo": {
                prefix: {
                    "actual": _rates(actual_by_repo[prefix]),
                    "oracle_best_channel": _recall_rates(
                        oracle_best_by_repo[prefix]
                    ),
                    "interleaved_union": _recall_rates(
                        interleaved_by_repo[prefix]
                    ),
                    "channels": {
                        name: _recall_rates(bucket)
                        for name, bucket in sorted(
                            channel_by_repo[prefix].items()
                        )
                    },
                }
                for prefix in sorted(actual_by_repo)
            },
        }
        print("[experiment-analysis] " + json.dumps(report, sort_keys=True), flush=True)
    except Exception as exc:
        print(f"[experiment-analysis] unable to calculate diagnostics: {exc}", flush=True)


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
    _report_metrics(root, diagnostics)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
