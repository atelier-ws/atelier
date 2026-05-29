"""TerminalBench CLI runner — drives trials and writes per-run transcript JSON.

Usage::

    python -m terminalbench.runner \\
        --task <task_id> \\
        --mode <on|off> \\
        [--model claude-sonnet-4-5] \\
        [--provider claude|ollama] \\
        [--rep 1] \\
        [--out benchmarks/terminalbench/outputs] \\
        [--dataset-name terminal-bench-core] \\
        [--dataset-version 0.1.1]

Each invocation runs a single (task, mode, rep) trial and writes:
- ``<out>/<task_id>__<mode>__rep<N>.json`` — full trial transcript (atomic write)
- ``<out>/runs.jsonl`` — append-mode JSONL log for aggregation
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# RunRecord — per-run row for JSONL aggregation
# ---------------------------------------------------------------------------


@dataclass
class RunRecord:
    """Single-row record combining AdapterResult fields with the transcript path.

    Written to a JSONL file by ``write_records()`` for downstream aggregation
    and analysis.
    """

    task_id: str
    mode: str
    rep: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    latency_ms: float
    latency_api_ms: float
    num_turns: int
    cost_usd: float
    grader_verdict: str | None
    grader_is_resolved: bool | None
    grader_failure_mode: str | None
    trial_started_at: str | None
    trial_ended_at: str | None
    is_error: bool
    stop_reason: str
    claude_error: str | None
    stream_log_path: str | None
    atelier_bench_mode: str
    atelier_root: str
    dataset_name: str
    dataset_version: str
    transcript_path: str | None = None

    def to_jsonl(self) -> str:
        """Serialise to a single JSON line (handles non-serialisable types via str)."""
        return json.dumps(dataclasses.asdict(self), default=str)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def write_records(rows: list[RunRecord], path: Path) -> Path:
    """Write a list of RunRecords to a JSONL file (one JSON object per line).

    Args:
        rows: List of ``RunRecord`` instances to write.
        path: Destination ``.jsonl`` file path (created/overwritten).

    Returns:
        The path that was written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(row.to_jsonl() + "\n")
    return path


def write_transcript(result: Any, out_dir: Path) -> Path:
    """Write a per-run transcript JSON file atomically (T-02-08).

    The filename follows the convention ``<task_id>__<mode>__rep<N>.json``.
    Writes to a ``.tmp`` file then calls ``os.replace()`` to prevent partial
    files on crash/kill.

    Args:
        result:  An ``AdapterResult`` instance.
        out_dir: Directory to write into (created if absent).

    Returns:
        Final path of the written transcript.
    """
    filename = f"{result.task_id}__{result.mode}__rep{result.rep}.json"
    final_path = out_dir / filename
    tmp_path = out_dir / f"{filename}.tmp"

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(
        json.dumps(result.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(tmp_path, final_path)
    return final_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point: run a single (task, mode, rep) trial."""
    from terminalbench.agent_adapter import run_terminalbench_trial
    from terminalbench.reporter import render_run_summary

    parser = argparse.ArgumentParser(
        prog="terminalbench.runner",
        description="Run a single TerminalBench trial and write transcript JSON.",
    )
    parser.add_argument("--task", required=True, help="TerminalBench task ID to run")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["on", "off"],
        help="Bench mode arm: 'on' (Atelier active) or 'off' (baseline)",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-5",
        help="Model slug (default: claude-sonnet-4-5). For Ollama provider, use the Ollama model name like qwen3.6:27b.",
    )
    parser.add_argument(
        "--provider",
        default="claude",
        choices=["claude", "ollama"],
        help="Agent provider: 'claude' (Anthropic Claude Code, default) or 'ollama' (local Ollama via OpenAI-compatible API).",
    )
    parser.add_argument(
        "--rep",
        type=int,
        default=1,
        help="Repetition number, 1-based (default: 1)",
    )
    parser.add_argument(
        "--out",
        default="benchmarks/terminalbench/outputs",
        help="Output directory for transcripts and JSONL log",
    )
    parser.add_argument(
        "--dataset-name",
        default="terminal-bench-core",
        help="TerminalBench dataset name (default: terminal-bench-core)",
    )
    parser.add_argument(
        "--dataset-version",
        default="0.1.1",
        help="TerminalBench dataset version (default: 0.1.1)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    print(f"Running {args.task} [{args.mode}] rep {args.rep} via {args.model}...")

    result = run_terminalbench_trial(
        task_id=args.task,
        bench_mode=args.mode,
        rep=args.rep,
        out_dir=out_dir,
        model=args.model,
        provider=args.provider,
        dataset_name=args.dataset_name,
        dataset_version=args.dataset_version,
    )

    transcript_path = write_transcript(result, out_dir)

    record = RunRecord(
        task_id=result.task_id,
        mode=result.mode,
        rep=result.rep,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_creation_input_tokens=result.cache_creation_input_tokens,
        cache_read_input_tokens=result.cache_read_input_tokens,
        latency_ms=result.latency_ms,
        latency_api_ms=result.latency_api_ms,
        num_turns=result.num_turns,
        cost_usd=result.cost_usd,
        grader_verdict=result.grader_verdict,
        grader_is_resolved=result.grader_is_resolved,
        grader_failure_mode=result.grader_failure_mode,
        trial_started_at=result.trial_started_at,
        trial_ended_at=result.trial_ended_at,
        is_error=result.is_error,
        stop_reason=result.stop_reason,
        claude_error=result.claude_error,
        stream_log_path=result.stream_log_path,
        atelier_bench_mode=result.atelier_bench_mode,
        atelier_root=result.atelier_root,
        dataset_name=result.dataset_name,
        dataset_version=result.dataset_version,
        transcript_path=str(transcript_path),
    )
    write_records([record], out_dir / "runs.jsonl")

    print(render_run_summary(result))
    print(f"Transcript: {transcript_path}")


if __name__ == "__main__":
    main()
