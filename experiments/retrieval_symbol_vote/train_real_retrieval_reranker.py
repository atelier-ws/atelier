"""Train repository-local top-five rerankers from real agent retrieval queries.

Input records come from build_real_retrieval_corpus.py. Each query was actually
issued by an agent, and positive files come from the corresponding task patch.
Evaluation task IDs are rejected even if they accidentally appear in the input.

The expensive candidate collection is parallelized within each repository using
process workers. Each worker owns one read-only CodeContextEngine and reuses it
for many queries. Model fitting remains in the parent process.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import math
import multiprocessing
import os
import random
import re
import signal
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import sitecustomize as experiment

from atelier.core.capabilities.code_context import CodeContextEngine

_WORKER_ENGINE: CodeContextEngine | None = None
_WORKER_TIMEOUT_S = 0.0
_TOP_K = 5


def _stable_fraction(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


def _path_matches(candidate: str, gold_files: list[str]) -> bool:
    normalized = _normalize_path(candidate)
    return any(
        normalized == gold or normalized.endswith(f"/{gold}") or gold.endswith(f"/{normalized}")
        for gold in (_normalize_path(path) for path in gold_files)
    )


_TASK_NAME_RE = re.compile(
    r"^(?P<task>.+?)_(?:atelier|baseline)"
    r"(?:_[A-Za-z0-9.-]+)?_rep\\d+\\.flow_dump\\.txt$"
)
_TASK_FALLBACK_RE = re.compile(r"(?P<task>[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\\d+)")


def _dump_files(roots: list[Path]) -> list[Path]:
    output: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = [
                *root.rglob("*.flow_dump.txt"),
                *root.rglob("*_dump.txt"),
            ]
        else:
            continue
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                output.append(resolved)
    return sorted(output)


def _task_id(path: Path) -> str | None:
    match = _TASK_NAME_RE.match(path.name)
    if match:
        return match.group("task")
    fallback = _TASK_FALLBACK_RE.search(path.name)
    return fallback.group("task") if fallback else None


def _excluded_task_ids(
    dump_roots: list[Path],
    task_id_files: list[Path],
) -> set[str]:
    output: set[str] = set()
    for dump_path in _dump_files(dump_roots):
        task_id = _task_id(dump_path)
        if task_id:
            output.add(task_id)
    for path in task_id_files:
        if not path.exists():
            raise SystemExit(f"Task-ID file does not exist: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                output.add(value)
    return output


def _load_corpus(path: Path, excluded_tasks: set[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    leaked: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Malformed JSONL at {path}:{line_number}") from exc
        task_id = str(record.get("task_id") or "")
        query = str(record.get("query") or "").strip()
        prefix = str(record.get("repo_prefix") or "")
        gold_files = record.get("gold_files")
        if task_id in excluded_tasks:
            leaked.add(task_id)
            continue
        if not task_id or not query or not prefix or not isinstance(gold_files, list):
            continue
        key = (prefix, task_id, query)
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "task_id": task_id,
                "repo_prefix": prefix,
                "query": query,
                "query_source": str(record.get("query_source") or "unknown"),
                "gold_files": [str(path) for path in gold_files if str(path)],
            }
        )
    if leaked:
        print(
            f"[safety] excluded {len(leaked)} evaluation task IDs present in corpus",
            file=sys.stderr,
            flush=True,
        )
    return output


def _worker_init(repo_root: str, db_path: str, timeout_s: float, top_k: int) -> None:
    global _TOP_K, _WORKER_ENGINE, _WORKER_TIMEOUT_S

    import atelier.core.capabilities.code_context.engine as engine_mod

    engine_mod._SEARCH_CHANNEL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
        max_workers=5,
        thread_name_prefix="atelier-fts-channel",
    )
    _WORKER_TIMEOUT_S = max(0.0, timeout_s)
    _TOP_K = max(2, top_k)
    engine = CodeContextEngine(
        Path(repo_root),
        db_path=Path(db_path),
        autosync_enabled=False,
    )
    engine._cache_get = lambda *_args, **_kwargs: (False, None)
    engine._cache_set = lambda *_args, **_kwargs: None
    engine._schema_ready = True
    with contextlib.suppress(Exception):
        engine._symbol_centrality_map()
    with contextlib.suppress(Exception):
        from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

        get_zoekt_supervisor(Path(repo_root))
    _WORKER_ENGINE = engine


def _collect_one(record: dict[str, Any]) -> dict[str, Any]:
    engine = _WORKER_ENGINE
    if engine is None:
        return {"status": "worker_uninitialized"}

    timed_out = False
    previous_handler: Any = None
    can_alarm = _WORKER_TIMEOUT_S > 0 and hasattr(signal, "SIGALRM")
    if can_alarm:

        def _on_alarm(_signum: int, _frame: Any) -> None:
            raise TimeoutError

        previous_handler = signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(max(1, math.ceil(_WORKER_TIMEOUT_S)))

    try:
        payload = engine.tool_explore(
            str(record["query"]),
            max_files=max(10, _TOP_K),
            auto_index=False,
        )
    except TimeoutError:
        timed_out = True
        return {"status": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": type(exc).__name__}
    finally:
        if can_alarm:
            signal.alarm(0)
            if previous_handler is not None:
                signal.signal(signal.SIGALRM, previous_handler)

    if timed_out or not isinstance(payload, dict):
        return {"status": "timeout" if timed_out else "invalid_payload"}
    raw_entries = payload.get("files")
    if not isinstance(raw_entries, list):
        return {"status": "invalid_payload"}

    entries = [entry for entry in raw_entries[:_TOP_K] if isinstance(entry, dict) and experiment._entry_path(entry)]
    if len(entries) < 2:
        return {"status": "too_few_candidates"}

    gold_files = [str(path) for path in record["gold_files"]]
    positive_index = next(
        (index for index, entry in enumerate(entries) if _path_matches(experiment._entry_path(entry), gold_files)),
        None,
    )
    if positive_index is None:
        return {"status": "candidate_miss"}

    features = [experiment._entry_features(str(record["query"]), entry, rank) for rank, entry in enumerate(entries, 1)]
    return {
        "status": "ok",
        "task_id": str(record["task_id"]),
        "query": str(record["query"]),
        "query_source": str(record.get("query_source") or "unknown"),
        "positive_index": positive_index,
        "features": features,
    }


def _collect_repository(
    records: list[dict[str, Any]],
    repo_root: Path,
    db_path: Path,
    workers: int,
    timeout_s: float,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stats: dict[str, int] = defaultdict(int)
    examples: list[dict[str, Any]] = []
    if not records:
        return examples, dict(stats)

    context_name = "fork" if sys.platform.startswith("linux") else "spawn"
    mp_context = multiprocessing.get_context(context_name)
    chunksize = max(1, len(records) // max(1, workers * 16))

    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        mp_context=mp_context,
        initializer=_worker_init,
        initargs=(str(repo_root), str(db_path), timeout_s, top_k),
    ) as executor:
        for index, result in enumerate(
            executor.map(_collect_one, records, chunksize=chunksize),
            1,
        ):
            status = str(result.get("status") or "unknown")
            stats[status] += 1
            if status == "ok":
                examples.append(result)
            if index % 100 == 0 or index == len(records):
                print(
                    f"[collect] {index}/{len(records)} ok={len(examples)} "
                    f"miss={stats.get('candidate_miss', 0)} "
                    f"timeout={stats.get('timeout', 0)}",
                    flush=True,
                )
    return examples, dict(stats)


def _split_by_task(
    examples: list[dict[str, Any]],
    validation_fraction: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks = sorted({str(example["task_id"]) for example in examples})
    validation_tasks = {task_id for task_id in tasks if _stable_fraction(f"validation:{task_id}") < validation_fraction}
    if tasks and not validation_tasks:
        validation_tasks.add(tasks[-1])
    if len(validation_tasks) == len(tasks) and len(tasks) > 1:
        validation_tasks.remove(tasks[0])

    train = [example for example in examples if example["task_id"] not in validation_tasks]
    validation = [example for example in examples if example["task_id"] in validation_tasks]
    return train, validation


def _pairwise_rows(examples: list[dict[str, Any]]) -> list[list[float]]:
    rows: list[list[float]] = []
    for example in examples:
        features = example["features"]
        positive_index = int(example["positive_index"])
        positive = features[positive_index]
        for index, negative in enumerate(features):
            if index == positive_index:
                continue
            rows.append(
                [
                    positive_value - negative_value
                    for positive_value, negative_value in zip(
                        positive,
                        negative,
                        strict=True,
                    )
                ]
            )
    return rows


def _sigmoid_negative(value: float) -> float:
    if value >= 0:
        exponent = math.exp(-value)
        return exponent / (1.0 + exponent)
    exponent = math.exp(value)
    return 1.0 / (1.0 + exponent)


def _train_weights(
    rows: list[list[float]],
    seed: int,
    epochs: int,
    learning_rate: float,
    l2: float,
) -> list[float]:
    weights = [0.0] * len(experiment._FEATURE_NAMES)
    randomizer = random.Random(seed)
    order = list(range(len(rows)))
    for epoch in range(epochs):
        randomizer.shuffle(order)
        rate = learning_rate / math.sqrt(epoch + 1)
        for row_index in order:
            difference = rows[row_index]
            margin = sum(weight * value for weight, value in zip(weights, difference, strict=True))
            multiplier = _sigmoid_negative(margin)
            for index, value in enumerate(difference):
                weights[index] += rate * (multiplier * value - l2 * weights[index])
    return weights


def _rank_example(
    example: dict[str, Any],
    weights: list[float],
    blend: float,
    margin: float,
) -> int:
    scored: list[tuple[float, int]] = []
    for rank, features in enumerate(example["features"], 1):
        learned = experiment._linear_score(weights, features)
        combined = blend * learned + (1.0 - blend) * (1.0 / rank)
        scored.append((combined, rank))
    proposed = sorted(scored, key=lambda item: (-item[0], item[1]))
    if proposed[0][1] != 1:
        original_top_score = next(score for score, rank in scored if rank == 1)
        if proposed[0][0] - original_top_score < margin:
            proposed = sorted(scored, key=lambda item: item[1])
    original_positive_rank = int(example["positive_index"]) + 1
    return next(
        new_rank
        for new_rank, (_score, original_rank) in enumerate(proposed, 1)
        if original_rank == original_positive_rank
    )


def _metrics(
    examples: list[dict[str, Any]],
    weights: list[float] | None = None,
    blend: float = 0.0,
    margin: float = 0.0,
) -> dict[str, float | int]:
    reciprocal_rank = 0.0
    hit1 = 0
    hit2 = 0
    hit3 = 0
    for example in examples:
        rank = int(example["positive_index"]) + 1 if weights is None else _rank_example(example, weights, blend, margin)
        reciprocal_rank += 1.0 / rank
        hit1 += int(rank == 1)
        hit2 += int(rank <= 2)
        hit3 += int(rank <= 3)
    count = max(1, len(examples))
    return {
        "n": len(examples),
        "mrr": reciprocal_rank / count,
        "hit1": hit1 / count,
        "hit2": hit2 / count,
        "hit3": hit3 / count,
    }


def _choose_policy(
    validation: list[dict[str, Any]],
    weight_candidates: list[list[float]],
) -> tuple[list[float], float, float, dict[str, Any], dict[str, Any]]:
    baseline = _metrics(validation)
    best: tuple[list[float], float, float, dict[str, Any]] | None = None
    for weights in weight_candidates:
        for blend in (0.25, 0.5, 0.75, 1.0):
            for margin in (0.0, 0.01, 0.02, 0.05, 0.1):
                result = _metrics(validation, weights, blend, margin)
                if float(result["hit1"]) + 1e-12 < float(baseline["hit1"]):
                    continue
                if float(result["hit3"]) + 1e-12 < float(baseline["hit3"]):
                    continue
                candidate = (weights, blend, margin, result)
                if best is None or (
                    float(result["mrr"]),
                    float(result["hit1"]),
                    float(result["hit2"]),
                    float(result["hit3"]),
                    -margin,
                ) > (
                    float(best[3]["mrr"]),
                    float(best[3]["hit1"]),
                    float(best[3]["hit2"]),
                    float(best[3]["hit3"]),
                    -best[2],
                ):
                    best = candidate
    if best is None:
        zero_weights = [0.0] * len(experiment._FEATURE_NAMES)
        return zero_weights, 0.0, 0.0, baseline, baseline
    return best[0], best[1], best[2], baseline, best[3]


def _train_repository(
    prefix: str,
    records: list[dict[str, Any]],
    metadata: dict[str, Any],
    workers: int,
    timeout_s: float,
    top_k: int,
    epochs: int,
    validation_fraction: float,
    min_validation_gain: float,
    min_train: int = 100,
    min_val: int = 30,
    min_pairwise: int = 200,
) -> dict[str, Any]:
    repo_root = Path(str(metadata["ws"])).resolve()
    db_path = Path(str(metadata["db"])).resolve()
    existing_records = [
        record for record in records if any((repo_root / path).exists() for path in record["gold_files"])
    ]
    print(
        f"[train] repository={prefix} records={len(records)} gold-existing={len(existing_records)} workers={workers}",
        flush=True,
    )
    examples, collection = _collect_repository(
        existing_records,
        repo_root=repo_root,
        db_path=db_path,
        workers=workers,
        timeout_s=timeout_s,
        top_k=top_k,
    )
    train, validation = _split_by_task(examples, validation_fraction)
    pairwise = _pairwise_rows(train)

    engine = CodeContextEngine(repo_root, db_path=db_path, autosync_enabled=False)
    repo_id = str(engine.repo_id)
    report: dict[str, Any] = {
        "repo_id": repo_id,
        "repo_root": str(repo_root),
        "repo_prefix": prefix,
        "enabled": False,
        "records": len(records),
        "records_with_existing_gold": len(existing_records),
        "examples": len(examples),
        "train_examples": len(train),
        "validation_examples": len(validation),
        "train_tasks": len({example["task_id"] for example in train}),
        "validation_tasks": len({example["task_id"] for example in validation}),
        "pairwise_rows": len(pairwise),
        "collection": collection,
    }
    if len(train) < min_train or len(validation) < min_val or len(pairwise) < min_pairwise:
        report["reason"] = "insufficient real task-disjoint examples"
        return report

    base_seed = int(repo_id[:8], 16)
    weight_candidates = [
        _train_weights(
            pairwise,
            seed=base_seed + offset,
            epochs=epochs,
            learning_rate=0.05,
            l2=0.002,
        )
        for offset in range(3)
    ]
    weights, blend, margin, baseline, learned = _choose_policy(
        validation,
        weight_candidates,
    )
    mrr_gain = float(learned["mrr"]) - float(baseline["mrr"])
    enabled = (
        mrr_gain >= min_validation_gain
        and float(learned["hit1"]) >= float(baseline["hit1"])
        and float(learned["hit3"]) >= float(baseline["hit3"])
    )
    report.update(
        {
            "enabled": enabled,
            "training_source": "real_agent_grep_and_patch_files",
            "feature_names": list(experiment._FEATURE_NAMES),
            "weights": weights,
            "blend": blend,
            "margin": margin,
            "validation": {
                "baseline": baseline,
                "learned": learned,
                "mrr_gain": mrr_gain,
            },
        }
    )
    if not enabled:
        report["reason"] = "held-out real-task validation did not clear safety gate"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        default="experiments/retrieval_symbol_vote/real_training_pairs.jsonl",
    )
    parser.add_argument(
        "--repo-metadata",
        default=("experiments/retrieval_symbol_vote/repo_metadata.json"),
        help="JSON containing only repository workspace/index metadata.",
    )
    parser.add_argument(
        "--exclude-dump-root",
        action="append",
        default=[],
        help=("Evaluation flow-dump directory. Task IDs are inferred from filenames only. Repeatable."),
    )
    parser.add_argument(
        "--exclude-task-ids",
        action="append",
        default=[],
        help="Plain text file containing one evaluation task ID per line.",
    )
    parser.add_argument(
        "--allow-no-exclusions",
        action="store_true",
    )
    parser.add_argument("--repo", default="", help="Train only matching repo prefix.")
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(4, (os.cpu_count() or 4) // 4)),
        help="Process workers used within each repository.",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=35)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--min-validation-gain", type=float, default=0.003)
    parser.add_argument("--max-records-per-repo", type=int, default=0)
    parser.add_argument(
        "--min-train", type=int, default=100, help="Min training examples required per repo (default: 100)."
    )
    parser.add_argument(
        "--min-val", type=int, default=30, help="Min validation examples required per repo (default: 30)."
    )
    parser.add_argument(
        "--min-pairwise", type=int, default=200, help="Min pairwise rows required per repo (default: 200)."
    )
    args = parser.parse_args()

    if os.environ.get("ATELIER_SELF_SUPERVISED_TRAINING") != "1":
        raise SystemExit(
            "Run with ATELIER_SELF_SUPERVISED_TRAINING=1 so V6 candidates "
            "are collected without applying an existing learned model."
        )

    project_root = Path(__file__).resolve().parents[2]
    corpus_path = Path(args.corpus).expanduser()
    metadata_path = Path(args.repo_metadata).expanduser()
    if not corpus_path.is_absolute():
        corpus_path = project_root / corpus_path
    if not metadata_path.is_absolute():
        metadata_path = project_root / metadata_path

    exclusion_roots = [Path(value).expanduser().resolve() for value in args.exclude_dump_root]
    exclusion_files = [Path(value).expanduser().resolve() for value in args.exclude_task_ids]
    excluded_tasks = _excluded_task_ids(
        exclusion_roots,
        exclusion_files,
    )
    if not excluded_tasks and not args.allow_no_exclusions:
        raise SystemExit(
            "No evaluation exclusions supplied. Pass "
            "--exclude-dump-root <evaluation-run-dir> or "
            "--exclude-task-ids <file>."
        )

    corpus = _load_corpus(corpus_path, excluded_tasks)
    metadata_data = json.loads(metadata_path.read_text(encoding="utf-8"))
    repos = metadata_data.get("repos", metadata_data)
    if not isinstance(repos, dict):
        raise SystemExit(f"Invalid repository metadata in {metadata_path}")

    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in corpus:
        prefix = str(record["repo_prefix"])
        if args.repo and args.repo not in prefix:
            continue
        by_repo[prefix].append(record)

    model_dir = Path(
        getattr(experiment, "_MODEL_DIR", project_root / "experiments/retrieval_symbol_vote/self_supervised_models")
    )
    model_dir.mkdir(parents=True, exist_ok=True)
    enabled_models = 0
    reports: list[dict[str, Any]] = []

    for prefix in sorted(by_repo):
        metadata = repos.get(prefix)
        if not isinstance(metadata, dict) or not metadata.get("ws") or not metadata.get("db"):
            print(f"[train] skip {prefix}: no provisioned workspace/index metadata", flush=True)
            continue
        records = by_repo[prefix]
        if args.max_records_per_repo > 0:
            records = sorted(
                records,
                key=lambda record: _stable_fraction(f"{record['task_id']}\0{record['query']}"),
            )[: args.max_records_per_repo]
        report = _train_repository(
            prefix,
            records,
            metadata,
            workers=max(1, args.workers),
            timeout_s=max(0.0, args.timeout),
            top_k=max(2, args.top_k),
            epochs=max(1, args.epochs),
            validation_fraction=min(0.5, max(0.05, args.validation_fraction)),
            min_validation_gain=max(0.0, args.min_validation_gain),
            min_train=max(1, args.min_train),
            min_val=max(1, args.min_val),
            min_pairwise=max(1, args.min_pairwise),
        )
        model_path = model_dir / f"{report['repo_id']}.json"
        model_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # Deploy to the db-stem-keyed path so the production engine picks it
        # up without PYTHONPATH tricks (collision-free even in /tmp).
        if report.get("enabled"):
            db_path = Path(str(metadata.get("db", "")))
            if db_path.suffix:
                deploy_path = db_path.with_suffix(".explore_reranker.json")
                deploy_path.write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                print(f"[train] deployed -> {deploy_path}", flush=True)
        enabled_models += int(bool(report.get("enabled")))
        reports.append(report)
        print(
            f"[train] model={model_path} enabled={report.get('enabled')} "
            f"validation={report.get('validation')} reason={report.get('reason')}",
            flush=True,
        )

    summary_path = model_dir / "real_training_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "corpus": str(corpus_path),
                "evaluation_task_ids": len(excluded_tasks),
                "repositories": len(reports),
                "enabled_models": enabled_models,
                "reports": reports,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"[train] complete repositories={len(reports)} enabled_models={enabled_models} summary={summary_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
