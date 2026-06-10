"""Aggregate TerminalBench ``runs.jsonl`` files into ``summary.json``."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atelier.core.capabilities.optimization import (
    load_terminalbench_records,
    summarize_terminalbench_arm,
)
from atelier.core.capabilities.optimization.non_inferiority import wilson_interval


@dataclass(frozen=True)
class CellSummary:
    task_id: str
    mode: str
    total: int
    passed: int
    failed: int
    error_like: int
    pass_rate: float
    wilson_lower: float
    wilson_upper: float
    input_tokens_sum: int
    output_tokens_sum: int
    cache_creation_input_tokens_sum: int
    cache_read_input_tokens_sum: int
    latency_ms_mean: float
    latency_api_ms_mean: float
    cost_usd_sum: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "mode": self.mode,
            "counts": {"passed": self.passed, "total": self.total},
            "failed": self.failed,
            "error_like": self.error_like,
            "pass_rate": self.pass_rate,
            "wilson_95": {"lower": self.wilson_lower, "upper": self.wilson_upper},
            "input_tokens_sum": self.input_tokens_sum,
            "output_tokens_sum": self.output_tokens_sum,
            "cache_creation_input_tokens_sum": self.cache_creation_input_tokens_sum,
            "cache_read_input_tokens_sum": self.cache_read_input_tokens_sum,
            "latency_ms_mean": self.latency_ms_mean,
            "latency_api_ms_mean": self.latency_api_ms_mean,
            "cost_usd_sum": self.cost_usd_sum,
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_cell(records: list[dict[str, Any]], *, task_id: str, mode: str, confidence: float = 0.95) -> CellSummary:
    filtered = [
        record
        for record in records
        if str(record.get("task_id") or "") == task_id and str(record.get("mode") or "").lower() == mode.lower()
    ]
    if not filtered:
        raise ValueError(f"no TerminalBench rows found for task_id={task_id!r} mode={mode!r}")

    passed = 0
    error_like = 0
    input_tokens: list[float] = []
    output_tokens: list[float] = []
    cache_creation_input_tokens: list[float] = []
    cache_read_input_tokens: list[float] = []
    latency_ms: list[float] = []
    latency_api_ms: list[float] = []
    cost_usd: list[float] = []

    for record in filtered:
        verdict = str(record.get("grader_verdict") or "").lower()
        if verdict == "pass":
            passed += 1
        if bool(record.get("is_error")) or verdict in {"", "error"}:
            error_like += 1
        input_tokens.append(float(record.get("input_tokens") or 0))
        output_tokens.append(float(record.get("output_tokens") or 0))
        cache_creation_input_tokens.append(float(record.get("cache_creation_input_tokens") or 0))
        cache_read_input_tokens.append(float(record.get("cache_read_input_tokens") or 0))
        latency_ms.append(float(record.get("latency_ms") or 0))
        latency_api_ms.append(float(record.get("latency_api_ms") or 0))
        cost_usd.append(float(record.get("cost_usd") or 0))

    total = len(filtered)
    lower, upper = wilson_interval(passed, total, confidence=confidence)
    return CellSummary(
        task_id=task_id,
        mode=mode,
        total=total,
        passed=passed,
        failed=total - passed,
        error_like=error_like,
        pass_rate=passed / total,
        wilson_lower=lower,
        wilson_upper=upper,
        input_tokens_sum=int(sum(input_tokens)),
        output_tokens_sum=int(sum(output_tokens)),
        cache_creation_input_tokens_sum=int(sum(cache_creation_input_tokens)),
        cache_read_input_tokens_sum=int(sum(cache_read_input_tokens)),
        latency_ms_mean=_mean(latency_ms),
        latency_api_ms_mean=_mean(latency_api_ms),
        cost_usd_sum=sum(cost_usd),
    )


def summarize_runs(records: list[dict[str, Any]], *, confidence: float = 0.95) -> dict[str, Any]:
    tasks = sorted({str(record.get("task_id") or "") for record in records if record.get("task_id")})
    modes = sorted({str(record.get("mode") or "").lower() for record in records if record.get("mode")})
    if not tasks:
        raise ValueError("no TerminalBench task rows found")
    if not modes:
        raise ValueError("no TerminalBench mode rows found")

    cells: dict[str, dict[str, Any]] = {}
    for task_id in tasks:
        task_cells: dict[str, Any] = {}
        for mode in modes:
            matching = [
                record
                for record in records
                if str(record.get("task_id") or "") == task_id and str(record.get("mode") or "").lower() == mode
            ]
            if not matching:
                continue
            task_cells[mode] = summarize_cell(records, task_id=task_id, mode=mode, confidence=confidence).to_dict()
        if task_cells:
            cells[task_id] = task_cells

    by_mode: dict[str, Any] = {}
    for mode in modes:
        arm = summarize_terminalbench_arm(records, mode=mode, confidence=confidence)
        mode_records = [record for record in records if str(record.get("mode") or "").lower() == mode]
        by_mode[mode] = {
            **arm.to_dict(),
            "counts": {"passed": arm.passed, "total": arm.total},
            "wilson_95": {"lower": arm.wilson_lower, "upper": arm.wilson_upper},
            "input_tokens_sum": int(sum(float(record.get("input_tokens") or 0) for record in mode_records)),
            "output_tokens_sum": int(sum(float(record.get("output_tokens") or 0) for record in mode_records)),
            "cache_creation_input_tokens_sum": int(
                sum(float(record.get("cache_creation_input_tokens") or 0) for record in mode_records)
            ),
            "cache_read_input_tokens_sum": int(
                sum(float(record.get("cache_read_input_tokens") or 0) for record in mode_records)
            ),
            "latency_ms_mean": _mean([float(record.get("latency_ms") or 0) for record in mode_records]),
            "latency_api_ms_mean": _mean([float(record.get("latency_api_ms") or 0) for record in mode_records]),
            "cost_usd_sum": sum(float(record.get("cost_usd") or 0) for record in mode_records),
        }

    delta: dict[str, Any] = {}
    if "on" in by_mode and "off" in by_mode:
        delta = {
            "pass_rate": by_mode["on"]["pass_rate"] - by_mode["off"]["pass_rate"],
            "latency_ms_mean": by_mode["on"]["latency_ms_mean"] - by_mode["off"]["latency_ms_mean"],
            "input_tokens_sum": by_mode["on"]["input_tokens_sum"] - by_mode["off"]["input_tokens_sum"],
            "output_tokens_sum": by_mode["on"]["output_tokens_sum"] - by_mode["off"]["output_tokens_sum"],
            "cost_usd_sum": by_mode["on"]["cost_usd_sum"] - by_mode["off"]["cost_usd_sum"],
        }

    return {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "confidence": confidence,
            "record_count": len(records),
            "tasks": tasks,
            "modes": modes,
            "models": sorted({str(record.get("model") or "") for record in records if record.get("model")}),
        },
        "cells": cells,
        "by_mode": by_mode,
        "delta_on_minus_off": delta,
    }


def write_summary(
    runs_path_or_dir: str | Path,
    *,
    out_path: str | Path | None = None,
    confidence: float = 0.95,
) -> Path:
    candidate = Path(runs_path_or_dir)
    runs_path = candidate / "runs.jsonl" if candidate.is_dir() else candidate
    destination = Path(out_path) if out_path is not None else runs_path.with_name("summary.json")
    summary = summarize_runs(load_terminalbench_records(runs_path), confidence=confidence)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="terminalbench.aggregate",
        description="Aggregate TerminalBench runs.jsonl into summary.json with Wilson intervals.",
    )
    parser.add_argument("--runs", required=True, help="runs.jsonl file or directory that contains it")
    parser.add_argument("--out", help="summary.json output path (defaults next to runs.jsonl)")
    parser.add_argument("--confidence", type=float, default=0.95, help="Wilson CI confidence level")
    args = parser.parse_args()

    destination = write_summary(args.runs, out_path=args.out, confidence=args.confidence)
    print(destination)


if __name__ == "__main__":
    main()
