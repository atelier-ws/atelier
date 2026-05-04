"""Reusable helpers for Atelier's offline runtime benchmark suite."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from atelier.infra.runtime.cost_tracker import CostTracker, estimate_cost
from atelier.infra.runtime.run_ledger import RunLedger
from atelier.infra.storage.factory import create_store


def default_tasks() -> list[tuple[str, str]]:
    """Default benchmark tasks — diverse, generic examples for any codebase."""
    return [
        ("unit_test", "write comprehensive unit tests for the authentication module"),
        (
            "refactor",
            "refactor the data validation layer to reduce complexity and improve type safety",
        ),
        ("documentation", "generate API documentation for the payment service endpoints"),
        ("optimize", "optimize database query performance by adding indexes and caching"),
        ("bugfix", "debug and fix the race condition in the concurrent request handler"),
    ]


def benchmark_report_path(root: Path) -> Path:
    return root / "benchmarks" / "runtime" / "latest.json"


def run_runtime_benchmark(
    *,
    root: Path,
    prompts: tuple[str, ...],
    model: str,
    rounds: int,
) -> dict[str, Any]:
    store = create_store(root)
    store.init()
    tasks = [("ad_hoc", prompt) for prompt in prompts] if prompts else default_tasks()
    results: list[dict[str, Any]] = []

    for domain, prompt in tasks:
        rounds_data: list[dict[str, Any]] = []
        lessons = store.search_blocks(prompt, limit=10)
        for round_index in range(rounds):
            saved_per_lesson_in = 350
            saved_per_lesson_out = 100
            base_in, base_out = 4000, 1500
            input_tok = max(800, base_in - len(lessons) * saved_per_lesson_in)
            output_tok = max(400, base_out - len(lessons) * saved_per_lesson_out)
            cache_read = 0 if round_index == 0 else min(2000, len(lessons) * 400)
            cost = estimate_cost(model, input_tok, output_tok, cache_read)

            ledger = RunLedger(
                agent="benchmark",
                root=root,
                task=prompt,
                domain=domain,
            )
            ledger.record_call(
                operation="benchmark",
                model=model,
                input_tokens=input_tok,
                output_tokens=output_tok,
                cache_read_tokens=cache_read,
                lessons_used=[block.id for block in lessons],
            )
            ledger.close("complete")
            ledger.persist(root)
            rounds_data.append(
                {
                    "round": round_index + 1,
                    "lessons_used": len(lessons),
                    "input_tokens": input_tok,
                    "output_tokens": output_tok,
                    "cache_read_tokens": cache_read,
                    "cost_usd": cost,
                }
            )

        baseline = rounds_data[0]["cost_usd"]
        final = rounds_data[-1]["cost_usd"]
        saved = baseline - final
        saved_pct = (saved / baseline * 100.0) if baseline > 0 else 0.0
        results.append(
            {
                "domain": domain,
                "task": prompt,
                "model": model,
                "rounds": rounds_data,
                "baseline_cost_usd": round(baseline, 6),
                "final_cost_usd": round(final, 6),
                "saved_usd": round(saved, 6),
                "saved_pct": round(saved_pct, 2),
            }
        )

    aggregate = CostTracker(root).total_savings()
    report = {
        "model": model,
        "rounds_per_task": rounds,
        "tasks": results,
        "aggregate": {key: value for key, value in aggregate.items() if key != "per_operation"},
    }
    path = benchmark_report_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def load_runtime_report(path: Path) -> dict[str, Any]:
    import typing

    return typing.cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def compare_runtime_reports(paths: list[Path]) -> dict[str, Any]:
    reports = [load_runtime_report(path) for path in paths]
    comparisons: list[dict[str, Any]] = []
    baseline = reports[0]
    baseline_saved = float(baseline.get("aggregate", {}).get("saved_usd", 0.0))
    for path, report in zip(paths, reports, strict=True):
        aggregate = report.get("aggregate", {})
        saved_usd = float(aggregate.get("saved_usd", 0.0))
        comparisons.append(
            {
                "path": str(path),
                "model": report.get("model", "unknown"),
                "tasks": len(report.get("tasks", [])),
                "saved_usd": saved_usd,
                "saved_pct": float(aggregate.get("saved_pct", 0.0)),
                "delta_vs_first_usd": round(saved_usd - baseline_saved, 6),
            }
        )
    return {"baseline": str(paths[0]), "reports": comparisons}


def render_runtime_report(report: dict[str, Any]) -> str:
    lines = ["# Atelier Runtime Benchmark", "", "## Aggregate"]
    aggregate = report.get("aggregate", {})
    lines.append(f"- model: `{report.get('model', 'unknown')}`")
    lines.append(f"- rounds_per_task: {report.get('rounds_per_task', 0)}")
    lines.append(f"- saved_usd: {aggregate.get('saved_usd', 0.0)}")
    lines.append(f"- saved_pct: {aggregate.get('saved_pct', 0.0)}")
    lines.append("")
    lines.append("## Tasks")
    lines.append("| Domain | Baseline $ | Final $ | Saved $ | Saved % | Task |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
    for task in report.get("tasks", []):
        lines.append(
            f"| {task['domain']} | {task['baseline_cost_usd']:.4f} | {task['final_cost_usd']:.4f} | {task['saved_usd']:.4f} | {task['saved_pct']:.2f} | {task['task']} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def export_runtime_report(report: dict[str, Any], *, output_path: Path, output_format: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return output_path
    if output_format == "markdown":
        output_path.write_text(render_runtime_report(report), encoding="utf-8")
        return output_path
    if output_format == "csv":
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "domain",
                    "task",
                    "baseline_cost_usd",
                    "final_cost_usd",
                    "saved_usd",
                    "saved_pct",
                ],
            )
            writer.writeheader()
            for task in report.get("tasks", []):
                writer.writerow(
                    {
                        "domain": task["domain"],
                        "task": task["task"],
                        "baseline_cost_usd": task["baseline_cost_usd"],
                        "final_cost_usd": task["final_cost_usd"],
                        "saved_usd": task["saved_usd"],
                        "saved_pct": task["saved_pct"],
                    }
                )
        return output_path
    raise ValueError(f"Unsupported export format: {output_format}")
