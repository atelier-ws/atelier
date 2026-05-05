"""V3 honest context-savings replay harness.

The harness simulates a host CLI dispatch loop over recorded synthetic transcripts.
Atelier itself does not call an LLM; token accounting is deterministic over recorded
host-native and Atelier-tool outputs.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tiktoken

from atelier.infra.storage.ids import make_uuid7
from atelier.infra.storage.sqlite_store import SQLiteStore

_CORPUS_DIR = Path(__file__).parent / "replay_corpus"
_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class ReplayPromptResult:
    id: str
    task_type: str
    baseline_input_tokens: int
    optimized_input_tokens: int
    lever: str

    @property
    def tokens_saved(self) -> int:
        return self.baseline_input_tokens - self.optimized_input_tokens

    @property
    def reduction_pct(self) -> float:
        if self.baseline_input_tokens == 0:
            return 0.0
        return self.tokens_saved / self.baseline_input_tokens * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "baseline_input_tokens": self.baseline_input_tokens,
            "optimized_input_tokens": self.optimized_input_tokens,
            "tokens_saved": self.tokens_saved,
            "reduction_pct": round(self.reduction_pct, 2),
            "lever": self.lever,
        }


@dataclass
class ReplayResult:
    run_id: str
    n_prompts: int
    median_input_tokens_baseline: int
    median_input_tokens_optimized: int
    reduction_pct: float
    lever_totals: dict[str, int] = field(default_factory=dict)
    prompts: list[ReplayPromptResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "n_prompts": self.n_prompts,
            "median_input_tokens_baseline": self.median_input_tokens_baseline,
            "median_input_tokens_optimized": self.median_input_tokens_optimized,
            "reduction_pct": round(self.reduction_pct, 2),
            "lever_totals": self.lever_totals,
            "prompts": [prompt.to_dict() for prompt in self.prompts],
        }


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _load_corpus(corpus_dir: Path = _CORPUS_DIR) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(corpus_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _config_fingerprint(root: Path) -> str:
    import hashlib

    config = root / "config.toml"
    data = config.read_bytes() if config.exists() else b""
    return hashlib.sha256(data).hexdigest()[:16]


def run_replay(
    root: str | Path | None = None,
    *,
    corpus_dir: Path = _CORPUS_DIR,
    csv_path: Path | None = None,
) -> ReplayResult:
    resolved_root = Path(root or os.environ.get("ATELIER_ROOT", ".atelier"))
    store = SQLiteStore(resolved_root)
    store.init()
    rows = _load_corpus(corpus_dir)
    if len(rows) < 50:
        raise ValueError(f"replay corpus must contain at least 50 transcripts, got {len(rows)}")

    prompts: list[ReplayPromptResult] = []
    lever_totals: dict[str, int] = {}
    for row in rows:
        baseline_text = "\n".join([str(row["task"]), str(row["baseline"])])
        atelier_text = "\n".join([str(row["task"]), str(row["atelier"])])
        baseline_tokens = _count_tokens(baseline_text)
        optimized_tokens = _count_tokens(atelier_text)
        result = ReplayPromptResult(
            id=str(row["id"]),
            task_type=str(row["task_type"]),
            baseline_input_tokens=baseline_tokens,
            optimized_input_tokens=optimized_tokens,
            lever=str(row["lever"]),
        )
        prompts.append(result)
        lever_totals[result.lever] = lever_totals.get(result.lever, 0) + result.tokens_saved

    total_baseline = sum(prompt.baseline_input_tokens for prompt in prompts)
    total_optimized = sum(prompt.optimized_input_tokens for prompt in prompts)
    reduction_pct = (total_baseline - total_optimized) / total_baseline * 100.0
    run_id = f"bench-{make_uuid7()}"
    completed_at = datetime.now(UTC)
    replay_result = ReplayResult(
        run_id=run_id,
        n_prompts=len(prompts),
        median_input_tokens_baseline=int(
            statistics.median(p.baseline_input_tokens for p in prompts)
        ),
        median_input_tokens_optimized=int(
            statistics.median(p.optimized_input_tokens for p in prompts)
        ),
        reduction_pct=reduction_pct,
        lever_totals=lever_totals,
        prompts=prompts,
    )
    _persist_result(store.db_path, replay_result, completed_at, resolved_root)
    if csv_path is not None:
        _write_csv(csv_path, replay_result)
    return replay_result


def _persist_result(
    db_path: Path, result: ReplayResult, completed_at: datetime, root: Path
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO benchmark_run (
                id, started_at, completed_at, suite, git_sha, config_fingerprint,
                n_prompts, median_input_tokens_baseline, median_input_tokens_optimized,
                reduction_pct, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                completed_at.isoformat(),
                completed_at.isoformat(),
                "savings_replay_v3",
                _git_sha(),
                _config_fingerprint(root),
                result.n_prompts,
                result.median_input_tokens_baseline,
                result.median_input_tokens_optimized,
                result.reduction_pct,
                "synthetic host-transcript replay; deterministic token accounting",
            ),
        )
        for prompt in result.prompts:
            conn.execute(
                """
                INSERT INTO benchmark_prompt_result (
                    id, run_id, prompt_id, task_type, baseline_input_tokens,
                    optimized_input_tokens, reduction_pct, lever_attribution_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"bpr-{make_uuid7()}",
                    result.run_id,
                    prompt.id,
                    prompt.task_type,
                    prompt.baseline_input_tokens,
                    prompt.optimized_input_tokens,
                    prompt.reduction_pct,
                    json.dumps({prompt.lever: prompt.tokens_saved}, sort_keys=True),
                ),
            )


def _write_csv(path: Path, result: ReplayResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "task_type",
                "baseline_input_tokens",
                "optimized_input_tokens",
                "tokens_saved",
                "reduction_pct",
                "lever",
            ],
        )
        writer.writeheader()
        for prompt in result.prompts:
            writer.writerow(prompt.to_dict())


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    csv_path = None
    if "--csv" in args:
        idx = args.index("--csv")
        csv_path = Path(args[idx + 1])
    result = run_replay(csv_path=csv_path)
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
