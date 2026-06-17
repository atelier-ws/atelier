"""Aggregate codegraph 7-repo A/B (efficiency-only) CodeBench results.

Reads one or more run dirs' ``results.jsonl``, keeps only clean rows
(``ok and valid and not timed_out``), takes the per-rep median of each metric
per arm, and reports baseline-vs-atelier savings.

Usage::

    uv run python -m benchmarks.codebench.cg_report <run_dir> [<run_dir> ...] [--json]

This is a standalone, read-only aggregator -- it never spends money and never
touches the runner. Tasks/arms missing from a run dir are tolerated.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

# Display order + names mirror codegraph's README table.
TASK_ORDER: list[tuple[str, str]] = [
    ("cg_vscode", "VS Code"),
    ("cg_excalidraw", "Excalidraw"),
    ("cg_django", "Django"),
    ("cg_tokio", "Tokio"),
    ("cg_okhttp", "OkHttp"),
    ("cg_gin", "gin"),
    ("cg_alamofire", "Alamofire"),
]

ARMS = ("baseline", "atelier")
METRICS = ("cost", "tokens", "time", "turns")


def _row_tokens(row: dict[str, Any]) -> int:
    return (
        int(row.get("input_tokens", 0))
        + int(row.get("cache_read_tokens", 0))
        + int(row.get("cache_creation_tokens", 0))
        + int(row.get("output_tokens", 0))
    )


def _load_rows(run_dirs: list[Path]) -> list[dict[str, Any]]:
    """Read + merge results.jsonl from each run dir, keeping only clean rows."""
    rows: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        path = run_dir / "results.jsonl"
        if not path.exists():
            print(f"[cg_report] skip: no results.jsonl in {run_dir}", file=sys.stderr)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("ok") is True and row.get("valid") is True and row.get("timed_out") is False:
                rows.append(row)
    return rows


def _metric_values(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    return {
        "cost": [float(r.get("cost_usd", 0.0)) for r in rows],
        "tokens": [float(_row_tokens(r)) for r in rows],
        "time": [float(r.get("duration_ms", 0)) for r in rows],
        "turns": [float(r.get("num_turns", 0)) for r in rows],
    }


def _medians(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    """Per-metric median over reps; None when there are no rows for this arm."""
    if not rows:
        return None
    values = _metric_values(rows)
    return {metric: statistics.median(vals) for metric, vals in values.items()}


def _pct(baseline: float, atelier: float) -> float | None:
    """Savings vs baseline as a percentage; None on divide-by-zero."""
    if baseline == 0:
        return None
    return round((1 - atelier / baseline) * 100, 1)


def compute(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Group rows by task/arm, take medians, and compute savings percentages."""
    tasks: dict[str, dict[str, Any]] = {}
    for task_id, _display in TASK_ORDER:
        task_rows = [r for r in rows if r.get("task") == task_id]
        arm_medians: dict[str, dict[str, float] | None] = {}
        arm_reps: dict[str, int] = {}
        for arm in ARMS:
            arm_rows = [r for r in task_rows if r.get("arm") == arm]
            arm_medians[arm] = _medians(arm_rows)
            arm_reps[arm] = len(arm_rows)
        base = arm_medians["baseline"]
        atel = arm_medians["atelier"]
        pct: dict[str, float | None] = {}
        if base is not None and atel is not None:
            for metric in METRICS:
                pct[metric] = _pct(base[metric], atel[metric])
        tasks[task_id] = {
            "medians": arm_medians,
            "reps": arm_reps,
            "pct": pct,
        }
    return tasks


def _phrase(metric: str, pct: float | None) -> str:
    """Render a savings percentage as a human phrase per the metric's verb."""
    if pct is None:
        return "n/a"
    if abs(pct) < 3:
        return "even"
    magnitude = abs(pct)
    if metric == "cost":
        word = "cheaper" if pct > 0 else "pricier"
    elif metric == "time":
        word = "faster" if pct > 0 else "slower"
    else:  # tokens, turns
        word = "fewer" if pct > 0 else "more"
    return f"{magnitude:g}% {word}"


def _present_tasks(tasks: dict[str, Any]) -> list[tuple[str, str]]:
    """Tasks (in display order) with valid medians in BOTH arms."""
    present: list[tuple[str, str]] = []
    for task_id, display in TASK_ORDER:
        entry = tasks.get(task_id)
        if not entry:
            continue
        medians = entry["medians"]
        if medians["baseline"] is not None and medians["atelier"] is not None:
            present.append((task_id, display))
    return present


def render_tables(tasks: dict[str, Any]) -> str:
    present = _present_tasks(tasks)
    lines: list[str] = []

    # (a) savings table
    lines.append("| Codebase | Cost | Tokens | Time | Tool calls |")
    lines.append("| --- | --- | --- | --- | --- |")
    sums: dict[str, list[float]] = {m: [] for m in METRICS}
    for task_id, display in present:
        pct = tasks[task_id]["pct"]
        cells = [_phrase(m, pct.get(m)) for m in METRICS]
        for metric in METRICS:
            value = pct.get(metric)
            if value is not None:
                sums[metric].append(value)
        lines.append(f"| {display} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")

    # (b) per-repo average row: mean of per-repo percentages. Caps at -100% on
    # wins but is unbounded on losses, so it skews high when repos disagree.
    avg_cells: list[str] = []
    for metric in METRICS:
        vals = sums[metric]
        avg = round(statistics.mean(vals), 1) if vals else None
        avg_cells.append(_phrase(metric, avg))
    lines.append(f"| **Average (per-repo)** | {avg_cells[0]} | {avg_cells[1]} | {avg_cells[2]} | {avg_cells[3]} |")

    # (b2) pooled-total row: sum each arm's per-repo medians, then take the
    # percentage. The statistically sound aggregate, free of the bounded/
    # unbounded skew that distorts the per-repo mean above.
    if present:
        pooled_cells: list[str] = []
        for metric in METRICS:
            base_total = sum(tasks[t]["medians"]["baseline"][metric] for t, _ in present)
            atel_total = sum(tasks[t]["medians"]["atelier"][metric] for t, _ in present)
            pooled_cells.append(_phrase(metric, _pct(base_total, atel_total)))
        lines.append(
            f"| **Overall (pooled)** | {pooled_cells[0]} | {pooled_cells[1]} | {pooled_cells[2]} | {pooled_cells[3]} |"
        )

    if not present:
        lines.append("")
        lines.append("_(no tasks with valid rows in both arms)_")

    # (c) raw-medians table
    lines.append("")
    lines.append("| Codebase | arm | cost_usd | tokens | time_s | turns | reps_used |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for task_id, display in TASK_ORDER:
        entry = tasks.get(task_id)
        if not entry:
            continue
        for arm in ARMS:
            medians = entry["medians"][arm]
            reps = entry["reps"][arm]
            if medians is None:
                continue
            cost = f"{medians['cost']:.4f}"
            tokens = f"{medians['tokens']:.0f}"
            time_s = f"{medians['time'] / 1000:.1f}"
            turns = f"{medians['turns']:.0f}"
            lines.append(f"| {display} | {arm} | {cost} | {tokens} | {time_s} | {turns} | {reps} |")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate codegraph A/B CodeBench results.")
    parser.add_argument("run_dirs", nargs="+", metavar="RUN_DIR", help="one or more result run dirs to merge")
    parser.add_argument("--json", action="store_true", help="dump computed structure as JSON instead of tables")
    args = parser.parse_args(argv)

    rows = _load_rows([Path(d) for d in args.run_dirs])
    tasks = compute(rows)

    if args.json:
        print(json.dumps(tasks, indent=2, sort_keys=True))
    else:
        print(render_tables(tasks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
