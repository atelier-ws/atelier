"""Export repository workspace/index metadata without exporting labels.

This reads only the ``repos`` field from the existing benchmark metadata and
writes a separate file for the trainer. The output contains no queries, task
IDs, or gold files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="benchmarks/codebench/data/bench_pairs_multi.json",
    )
    parser.add_argument(
        "--output",
        default=(
            "experiments/retrieval_symbol_vote/"
            "repo_metadata.json"
        ),
    )
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = Path.cwd() / output

    data = json.loads(source.read_text(encoding="utf-8"))
    repos = data.get("repos")
    if not isinstance(repos, dict):
        raise SystemExit(f"No valid repos object in {source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"repos": repos}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "input": str(source),
                "output": str(output.resolve()),
                "repositories": len(repos),
                "contains_queries": False,
                "contains_task_ids": False,
                "contains_gold_files": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
