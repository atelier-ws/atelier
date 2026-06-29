"""Build a real retrieval-training corpus without reading benchmark gold JSON.

Training queries come from real agent tool calls in flow dumps:
  - grep regex patterns  (query_source="agent_grep")
  - explore NL queries   (query_source="agent_explore")
  - Read file paths      (query_source="agent_read")
  - SWE-bench problem statements (query_source="problem_statement")

Positive files come from the matching SWE-bench patch.  Evaluation tasks are
excluded using only flow-dump filenames or plain task-ID files.

Supports both text `.flow_dump.txt` files (with [tool_use: ...] wrappers) and
binary `.flow` websocket files (direct JSON field extraction).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from benchmarks.codebench import swebench_data  # noqa: E402

_TEST_PATH_RE = re.compile(
    r"(^|/)(test_|tests?/|testing/|conftest(?:\.py)?$)",
    re.IGNORECASE,
)
# Matches both text dump files (.flow_dump.txt) and binary websocket files (.flow)
_TASK_NAME_RE = re.compile(
    r"^(?P<task>.+?)_(?:atelier|baseline)"
    r"(?:_[A-Za-z0-9.-]+)?_rep\d+\.flow(?:_dump\.txt)?$"
)
_TASK_FALLBACK_RE = re.compile(r"(?P<task>[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+)")
# ---- text dump patterns (require [tool_use: ...] wrapper) ----
_GREP_CALL_RE = re.compile(
    r"(?:mcp__plugin_atelier_atelier__grep|"
    r"mcp__atelier__grep|atelier__grep)\]\s*(\{.*?\})",
    re.DOTALL,
)
_REGEX_FIELD_RE = re.compile(r'"regex"\s*:\s*"((?:[^"\\]|\\.)*)')
_EXPLORE_CALL_RE = re.compile(
    r"(?:mcp__plugin_atelier_atelier__explore|"
    r"mcp__atelier__explore|atelier__explore)\]\s*(\{.*?\})",
    re.DOTALL,
)
_QUERY_FIELD_RE = re.compile(r'"query"\s*:\s*"((?:[^"\\]|\\.)*)')
_READ_CALL_RE = re.compile(
    r"(?:mcp__plugin_atelier_atelier__read|"
    r"mcp__atelier__read|atelier__read)\]\s*(\{.*?\})",
    re.DOTALL,
)
_PATH_FIELD_RE = re.compile(r'"path"\s*:\s*"([^"]{5,200})')
# ---- binary .flow patterns (direct JSON — no [tool_use:] wrapper) ----
# The tool schema descriptions use object values like "regex":{...}, so
# "regex":"string" safely selects only actual call inputs.
_FLOW_REGEX_RE = re.compile(r'"regex"\s*:\s*"([^"\\]{3,})')
_FLOW_PATH_RE = re.compile(r'"path"\s*:\s*"([^"]{5,200})')
_PATCH_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def _dump_files(roots: list[Path]) -> list[Path]:
    """Collect all mineable dump files under *roots*.

    Text dump files (*.flow_dump.txt, *_dump.txt) are always included.
    Binary websocket files (*.flow) are added only for task IDs that have
    no text dump counterpart — they are expensive to read and yield the
    same queries once deduplicated, so we avoid redundant processing.
    """
    output: list[Path] = []
    seen: set[Path] = set()
    tasks_with_text_dump: set[str] = set()

    # First pass: text dumps (cheap, preferred)
    for root in roots:
        if root.is_file():
            candidates = [root] if root.suffix in (".txt",) else []
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
                tid = _task_id(candidate)
                if tid:
                    tasks_with_text_dump.add(tid)

    # Second pass: binary .flow files — only for tasks lacking a text dump
    for root in roots:
        if root.is_file():
            candidates = [root] if root.suffix == ".flow" else []
        elif root.is_dir():
            candidates = list(root.rglob("*.flow"))
        else:
            continue
        # Collect one representative file per task (first atelier rep)
        seen_flow_tasks: set[str] = set()
        for candidate in sorted(candidates):
            if candidate.stat().st_size == 0:
                continue
            tid = _task_id(candidate)
            if not tid or tid in tasks_with_text_dump:
                continue
            if tid in seen_flow_tasks:
                continue  # keep only one file per task to limit I/O
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                output.append(resolved)
            seen_flow_tasks.add(tid)

    return sorted(output)


def _task_id(path: Path) -> str | None:
    match = _TASK_NAME_RE.match(path.name)
    if match:
        return match.group("task")
    fallback = _TASK_FALLBACK_RE.search(path.name)
    return fallback.group("task") if fallback else None


def _task_ids_from_dump_roots(roots: list[Path]) -> set[str]:
    output: set[str] = set()
    for dump_path in _dump_files(roots):
        task_id = _task_id(dump_path)
        if task_id:
            output.add(task_id)
    return output


def _task_ids_from_files(paths: list[Path]) -> set[str]:
    output: set[str] = set()
    for path in paths:
        if not path.exists():
            raise SystemExit(f"Task-ID file does not exist: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                output.add(value)
    return output


def _decode_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.encode().decode("unicode_escape", "replace")


def _mine_queries(
    path: Path,
    min_length: int,
    max_length: int,
) -> list[tuple[str, str]]:
    """Return (query, source) pairs mined from *path*.

    For text dump files the source is ``"agent_grep"`` or ``"agent_explore"``.
    For binary ``.flow`` websocket files only grep patterns are extracted
    (explore calls are not present in those older recordings).
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    output: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(raw: str, source: str) -> None:
        query = _decode_json_string(raw).strip()
        if len(query) < min_length:
            return
        if max_length > 0 and len(query) > max_length:
            return
        if query not in seen:
            seen.add(query)
            output.append((query, source))

    if path.suffix == ".flow":
        # Binary websocket file: direct JSON field extraction
        for m in _FLOW_REGEX_RE.finditer(text):
            _add(m.group(1), "agent_grep")
    else:
        # Text dump file: tool-call-wrapper extraction
        for blob in _GREP_CALL_RE.findall(text):
            m = _REGEX_FIELD_RE.search(blob)
            if m:
                _add(m.group(1), "agent_grep")
        for blob in _EXPLORE_CALL_RE.findall(text):
            m = _QUERY_FIELD_RE.search(blob)
            if m:
                _add(m.group(1), "agent_explore")

    return output


def _mine_read_paths(
    path: Path,
    include_tests: bool,
) -> list[str]:
    """Return unique source-file paths seen in Read tool calls.

    These become ``agent_read`` query signals: querying by a file path should
    surface that file and related gold files for the same task.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    seen: set[str] = set()
    output: list[str] = []

    raw_paths: list[str] = []
    if path.suffix == ".flow":
        for m in _FLOW_PATH_RE.finditer(text):
            raw_paths.append(m.group(1))
    else:
        for blob in _READ_CALL_RE.findall(text):
            m = _PATH_FIELD_RE.search(blob)
            if m:
                raw_paths.append(m.group(1))

    for raw in raw_paths:
        # Strip line-range suffixes (#L1-L100, #123-456)
        fp = raw.split("#")[0].strip().replace("\\", "/")
        # Normalise /testbed/ prefix used inside SWE-bench containers
        if fp.startswith("/testbed/"):
            fp = fp[len("/testbed/") :]
        # Skip non-source paths
        if not fp or "/" not in fp:
            continue
        if fp.startswith(("http", "/tmp", "/var", "/usr", "/home")):
            continue
        # Must have a file extension
        last = fp.rsplit("/", 1)[-1]
        if "." not in last:
            continue
        if not include_tests and _TEST_PATH_RE.search(fp):
            continue
        if fp not in seen:
            seen.add(fp)
            output.append(fp)

    return output


def _gold_files(patch: str, include_tests: bool) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for file_path in _PATCH_FILE_RE.findall(patch or ""):
        normalized = file_path.strip().replace("\\", "/")
        if not normalized or normalized == "/dev/null":
            continue
        if not include_tests and _TEST_PATH_RE.search(normalized):
            continue
        if normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


# SWE-bench task IDs have the form owner__repo-NNN
_SWE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+$")


def _load_instances(
    task_ids: list[str],
    dataset: str | None,
) -> dict[str, Any]:
    """Load SWE-bench instances for *task_ids*, silently skipping unknowns.

    Load the full dataset once (min_changed_files=1 so single-file tasks are
    included) and filter to the requested IDs to avoid the library raising on
    task IDs from non-Python repos (Go CLI tasks, etc.).
    """
    wanted = {tid for tid in task_ids if _SWE_ID_RE.match(tid)}
    if not wanted:
        return {}
    all_instances = swebench_data.load_instances(
        dataset=dataset,
        min_changed_files=1,
    )
    return {
        str(inst.instance_id): inst
        for inst in all_instances
        if str(inst.instance_id) in wanted
    }


def _resolve_paths(values: list[str]) -> list[Path]:
    return [Path(value).expanduser().resolve() for value in values]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dump-root",
        action="append",
        default=[],
        help="Training flow-dump file or directory. Repeatable.",
    )
    parser.add_argument(
        "--exclude-dump-root",
        action="append",
        default=[],
        help=("Evaluation flow-dump directory. Task IDs are inferred only from filenames and excluded. Repeatable."),
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
        help="Permit corpus generation without any evaluation exclusion source.",
    )
    parser.add_argument(
        "--output",
        default=("experiments/retrieval_symbol_vote/real_training_pairs.jsonl"),
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Optional SWE-bench dataset name or local JSON/JSONL path.",
    )
    parser.add_argument("--min-query-length", type=int, default=3)
    parser.add_argument(
        "--max-query-length",
        type=int,
        default=0,
        help="0 disables the upper bound.",
    )
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument(
        "--include-problem-statements",
        action="store_true",
    )
    parser.add_argument(
        "--extra-task-ids",
        action="append",
        default=[],
        help=(
            "Plain text file with additional task IDs to include even when "
            "no dump files exist (e.g. train_task_ids.txt). Repeatable. "
            "Requires --include-problem-statements to emit any records."
        ),
    )
    args = parser.parse_args()

    training_roots = _resolve_paths(args.dump_root)
    if not training_roots:
        training_roots = [(_PROJECT_ROOT / "reports/benchmark/codebench").resolve()]
    exclusion_roots = _resolve_paths(args.exclude_dump_root)
    exclusion_files = _resolve_paths(args.exclude_task_ids)

    excluded = _task_ids_from_dump_roots(exclusion_roots)
    excluded |= _task_ids_from_files(exclusion_files)
    if not excluded and not args.allow_no_exclusions:
        raise SystemExit(
            "No evaluation exclusions were supplied. Pass "
            "--exclude-dump-root <evaluation-run-dir> or "
            "--exclude-task-ids <file>. Use --allow-no-exclusions only "
            "when you deliberately accept possible overlap."
        )

    extra_task_id_files = _resolve_paths(args.extra_task_ids)

    dumps = _dump_files(training_roots)
    if not dumps and not extra_task_id_files:
        raise SystemExit("No flow dumps found under: " + ", ".join(map(str, training_roots)))

    # (query, source) tuples per task
    queries_by_task: dict[str, list[tuple[str, str]]] = defaultdict(list)
    dumps_by_task: dict[str, list[str]] = defaultdict(list)
    read_paths_by_task: dict[str, list[str]] = defaultdict(list)
    seen_queries_by_task: dict[str, set[str]] = defaultdict(set)
    seen_paths_by_task: dict[str, set[str]] = defaultdict(set)
    unparsed_names = 0

    min_q = max(1, args.min_query_length)
    max_q = max(0, args.max_query_length)

    for dump_path in dumps:
        task_id = _task_id(dump_path)
        if not task_id:
            unparsed_names += 1
            continue
        if task_id in excluded:
            continue
        dumps_by_task[task_id].append(str(dump_path))
        for query, source in _mine_queries(dump_path, min_q, max_q):
            if query not in seen_queries_by_task[task_id]:
                seen_queries_by_task[task_id].add(query)
                queries_by_task[task_id].append((query, source))
        for fp in _mine_read_paths(dump_path, args.include_tests):
            if fp not in seen_paths_by_task[task_id]:
                seen_paths_by_task[task_id].add(fp)
                read_paths_by_task[task_id].append(fp)
        # Ensure task appears in queries_by_task even when only read paths exist.
        # Guard against non-SWE-bench task IDs (atelierbench uses task1, cg_gin, etc.)
        if _TASK_FALLBACK_RE.match(task_id):
            _ = queries_by_task[task_id]

    # Extra task IDs from --extra-task-ids files (no dumps; emit PS only)
    extra_task_ids = _task_ids_from_files(extra_task_id_files) - excluded
    for tid in sorted(extra_task_ids):
        if tid not in queries_by_task:
            queries_by_task[tid]  # touch defaultdict key

    task_ids = sorted(queries_by_task)
    if not task_ids:
        raise SystemExit("No non-evaluation tasks with mined queries were found.")

    instances = _load_instances(task_ids, args.dataset)
    missing_instances = sorted(set(task_ids) - set(instances))

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = _PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = 0
    tasks_written = 0
    repo_counts: dict[str, int] = defaultdict(int)
    source_counts: dict[str, int] = defaultdict(int)

    with output_path.open("w", encoding="utf-8") as handle:
        for task_id in task_ids:
            instance = instances.get(task_id)
            if instance is None:
                continue
            gold_files = _gold_files(
                str(instance.patch or ""),
                args.include_tests,
            )

            repo = str(instance.repo or "")
            repo_prefix = repo.replace("/", "__")

            # Ordered: grep/explore first, then read paths, then problem statement
            queries: list[tuple[str, str]] = list(queries_by_task[task_id])
            read_paths = read_paths_by_task.get(task_id, [])

            # Fallback gold: when patch is empty use agent-read source files
            if not gold_files and read_paths:
                source_files = [fp for fp in read_paths if not _TEST_PATH_RE.search(fp) or args.include_tests]
                gold_files = source_files[:10]  # cap to avoid noise

            if not gold_files:
                continue

            for fp in read_paths:
                queries.append((fp, "agent_read"))
            if args.include_problem_statements:
                problem = str(instance.problem_statement or "").strip()
                if problem:
                    queries.append((problem, "problem_statement"))

            emitted = 0
            seen_queries: set[str] = set()
            for query, source in queries:
                normalized = query.strip()
                if not normalized or normalized in seen_queries:
                    continue
                seen_queries.add(normalized)
                record = {
                    "task_id": task_id,
                    "repo": repo,
                    "repo_prefix": repo_prefix,
                    "base_commit": str(instance.base_commit or ""),
                    "query": normalized,
                    "query_source": source,
                    "gold_files": gold_files,
                    "problem_statement": str(instance.problem_statement or ""),
                    "source_dumps": dumps_by_task.get(task_id, []),
                }
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                records += 1
                emitted += 1
                repo_counts[repo_prefix] += 1
                source_counts[source] += 1
            tasks_written += int(emitted > 0)

    all_training_task_ids = {task_id for dump_path in dumps if (task_id := _task_id(dump_path))}
    summary = {
        "training_dump_files": len(dumps),
        "evaluation_task_ids": len(excluded),
        "evaluation_tasks_excluded": len(excluded & all_training_task_ids),
        "unparsed_dump_names": unparsed_names,
        "tasks_with_queries": len(queries_by_task),
        "missing_dataset_instances": len(missing_instances),
        "tasks_written": tasks_written,
        "records": records,
        "output": str(output_path),
        "by_repo": dict(sorted(repo_counts.items())),
        "by_source": dict(sorted(source_counts.items())),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
