"""Build a real retrieval-training corpus from existing flow dumps + a golden JSON.

Unlike build_real_retrieval_corpus.py this script does NOT call the SWE-bench
API.  Gold files come from the ``true_map`` in a pre-existing benchmark JSON
(e.g. benchmarks/codebench/data/bench_pairs_multi.json).  No evaluation
exclusion is required: the training / validation split is handled entirely by
train_real_retrieval_reranker.py at training time.

Usage::

    ROOT=/home/pankaj/Projects/leanchain/atelier
    uv run python \\
      experiments/retrieval_symbol_vote/build_existing_dump_query_holdout.py \\
      --dump-root "$ROOT/reports/benchmark/codebench" \\
      --golden-json \\
        "$ROOT/benchmarks/codebench/data/bench_pairs_multi.json" \\
      --output \\
        "$ROOT/experiments/retrieval_symbol_vote/real_training_pairs.jsonl"
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_TEST_PATH_RE = re.compile(
    r"(^|/)(test_|tests?/|testing/|conftest(?:\.py)?$)",
    re.IGNORECASE,
)
_TASK_NAME_RE = re.compile(
    r"^(?P<task>.+?)_(?:atelier|baseline)"
    r"(?:_[A-Za-z0-9.-]+)?_rep\d+\.flow_dump\.txt$"
)
_TASK_FALLBACK_RE = re.compile(r"(?P<task>[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+)")
_GREP_CALL_RE = re.compile(
    r"(?:mcp__plugin_atelier_atelier__grep|"
    r"mcp__atelier__grep|atelier__grep)\]\s*(\{.*?\})",
    re.DOTALL,
)
_REGEX_FIELD_RE = re.compile(r'"regex"\s*:\s*"((?:[^"\\]|\\.)*)"')


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


def _decode_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.encode().decode("unicode_escape", "replace")


def _mine_queries(
    path: Path,
    min_length: int,
    max_length: int,
) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    output: list[str] = []
    seen: set[str] = set()
    for blob in _GREP_CALL_RE.findall(text):
        match = _REGEX_FIELD_RE.search(blob)
        if not match:
            continue
        query = _decode_json_string(match.group(1)).strip()
        if len(query) < min_length:
            continue
        if max_length > 0 and len(query) > max_length:
            continue
        if query in seen:
            continue
        seen.add(query)
        output.append(query)
    return output

def _load_golden(
    path: Path,
    include_tests: bool,
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]], list[tuple[str, str, str]]]:
    """Return (true_map, repos, pairs) from a bench_pairs_multi-style JSON.

    true_map: task_id -> [gold_file, ...]
    repos:    repo_prefix -> {ws, db, base_commit, ...}
    pairs:    [(query, task_id, repo_prefix), ...] — pre-mined pairs from the JSON
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_true_map: dict[str, list[str]] = data.get("true_map", {})
    repos: dict[str, dict[str, Any]] = data.get("repos", {})
    raw_pairs: list[Any] = data.get("pairs", [])

    true_map: dict[str, list[str]] = {}
    for task_id, files in raw_true_map.items():
        filtered = [f for f in files if include_tests or not _TEST_PATH_RE.search(f)]
        if filtered:
            true_map[task_id] = filtered

    pairs: list[tuple[str, str, str]] = [
        (str(q), str(tid), str(pfx))
        for q, tid, pfx in raw_pairs
        if q and tid and pfx
    ]

    return true_map, repos, pairs

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build retrieval training corpus from dump queries + golden JSON",
    )
    parser.add_argument(
        "--dump-root",
        action="append",
        default=[],
        help="Flow-dump file or directory to mine queries from. Repeatable.",
    )
    parser.add_argument(
        "--golden-json",
        required=True,
        help="bench_pairs_multi.json path (provides true_map, pairs, and repo metadata).",
    )
    parser.add_argument(
        "--use-bench-pairs",
        action="store_true",
        help=(
            "Use pre-mined pairs from the golden JSON instead of (or in addition "
            "to) dump-mined queries. These are the same queries the eval uses and "
            "achieve high hit rates in tool_explore."
        ),
    )
    parser.add_argument(
        "--exclude-task-ids",
        action="append",
        default=[],
        help="Plain text file of task IDs to exclude (e.g. eval holdout). Repeatable.",
    )
    parser.add_argument(
        "--output",
        default="experiments/retrieval_symbol_vote/real_training_pairs.jsonl",
    )
    parser.add_argument("--min-query-length", type=int, default=3)
    parser.add_argument(
        "--max-query-length",
        type=int,
        default=0,
        help="0 disables the upper bound.",
    )
    parser.add_argument("--include-tests", action="store_true")
    args = parser.parse_args()

    golden_path = Path(args.golden_json).expanduser()
    if not golden_path.is_absolute():
        golden_path = _PROJECT_ROOT / golden_path

    true_map, repos, bench_pairs = _load_golden(golden_path, args.include_tests)
    print(
        f"[build] golden JSON: {len(true_map)} task IDs, "
        f"{len(repos)} repos, {len(bench_pairs)} pre-mined pairs",
        flush=True,
    )

    # Load excluded task IDs
    excluded: set[str] = set()
    for path_str in args.exclude_task_ids:
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        for line in p.read_text(encoding="utf-8").splitlines():
            v = line.strip()
            if v and not v.startswith("#"):
                excluded.add(v)
    if excluded:
        print(f"[build] excluding {len(excluded)} task IDs", flush=True)

    # Build reverse map task_id -> repo_prefix
    # Build task_id -> repo_prefix from the pairs list (authoritative)
    # then fall back to prefix-matching for dump-mined tasks not in pairs.
    task_to_prefix: dict[str, str] = {}
    for _q, task_id, prefix in bench_pairs:
        if task_id not in task_to_prefix and prefix:
            task_to_prefix[task_id] = prefix
    for prefix in repos:
        for task_id in true_map:
            if task_id not in task_to_prefix and (
                task_id.startswith(prefix + "-") or task_id.startswith(prefix + "_")
            ):
                task_to_prefix[task_id] = prefix

    # Collect queries: bench_pairs + dump-mined (deduped per task)
    queries_by_task: dict[str, list[str]] = defaultdict(list)
    dumps_by_task: dict[str, list[str]] = defaultdict(list)
    seen_by_task: dict[str, set[str]] = defaultdict(set)

    if args.use_bench_pairs:
        for query, task_id, _prefix in bench_pairs:
            if task_id in excluded:
                continue
            if len(query) < max(1, args.min_query_length):
                continue
            if args.max_query_length > 0 and len(query) > args.max_query_length:
                continue
            if query not in seen_by_task[task_id]:
                seen_by_task[task_id].add(query)
                queries_by_task[task_id].append(query)
        print(
            f"[build] bench pairs: {sum(len(v) for v in queries_by_task.values())} "
            f"queries across {len(queries_by_task)} tasks",
            flush=True,
        )

    dump_roots = [Path(v).expanduser().resolve() for v in args.dump_root]
    if dump_roots:
        dumps = _dump_files(dump_roots)
        print(f"[build] scanning {len(dumps)} dump files", flush=True)
        unparsed = 0
        for dump_path in dumps:
            tid = _task_id(dump_path)
            if not tid or tid in excluded:
                unparsed += int(not tid)
                continue
            dumps_by_task[tid].append(str(dump_path))
            for query in _mine_queries(
                dump_path,
                min_length=max(1, args.min_query_length),
                max_length=max(0, args.max_query_length),
            ):
                if query not in seen_by_task[tid]:
                    seen_by_task[tid].add(query)
                    queries_by_task[tid].append(query)

    if not queries_by_task:
        raise SystemExit(
            "No queries collected. Pass --use-bench-pairs and/or --dump-root."
        )

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = _PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = 0
    tasks_written = 0
    skipped_no_gold = 0
    repo_counts: dict[str, int] = defaultdict(int)

    with output_path.open("w", encoding="utf-8") as handle:
        for task_id in sorted(queries_by_task):
            gold_files = true_map.get(task_id)
            if not gold_files:
                skipped_no_gold += 1
                continue

            repo_prefix = task_to_prefix.get(task_id, "")
            repo_meta = repos.get(repo_prefix, {})
            repo = repo_prefix.replace("__", "/", 1)
            base_commit = str(repo_meta.get("base_commit") or "")

            emitted = 0
            seen_queries: set[str] = set()
            for query in queries_by_task[task_id]:
                normalized = query.strip()
                if not normalized or normalized in seen_queries:
                    continue
                seen_queries.add(normalized)
                record = {
                    "task_id": task_id,
                    "repo": repo,
                    "repo_prefix": repo_prefix,
                    "base_commit": base_commit,
                    "query": normalized,
                    "query_source": "bench_pair" if normalized in (seen_by_task.get(task_id) or set()) else "agent_grep",
                    "gold_files": gold_files,
                    "problem_statement": "",
                    "source_dumps": dumps_by_task.get(task_id, []),
                }
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                records += 1
                emitted += 1
                repo_counts[repo_prefix] += 1
            tasks_written += int(emitted > 0)

    summary = {
        "excluded_tasks": len(excluded),
        "tasks_with_queries": len(queries_by_task),
        "tasks_with_gold": tasks_written,
        "skipped_no_gold": skipped_no_gold,
        "records": records,
        "output": str(output_path),
        "by_repo": dict(sorted(repo_counts.items())),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
