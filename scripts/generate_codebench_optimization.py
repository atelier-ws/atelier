#!/usr/bin/env python3
"""Generate the chronological CodeBench optimization CSV and line chart."""

from __future__ import annotations

import csv
import html
import math
import re
from datetime import UTC, datetime
from pathlib import Path

REPORT_ROOT = Path("reports/benchmark/codebench")
PUBLIC_ROOT = Path("reports/public/benchmark/codebench")
CANONICAL_RESULTS = REPORT_ROOT / "swe30_run1_20260622T043715Z" / "results.csv"
CSV_OUTPUT = PUBLIC_ROOT / "optimization_savings.csv"
SVG_OUTPUT = PUBLIC_ROOT / "optimization_savings.svg"
EXPECTED_TASKS = 30
MIN_TASKS_PER_EXPERIMENT = 3
MIN_SAVINGS_PERCENT = -100.0


def read_results(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def positive_cost(row: dict[str, str]) -> float | None:
    try:
        cost = float(row.get("cost_usd") or 0)
    except ValueError:
        return None
    return cost if math.isfinite(cost) and cost > 0 else None


def reported_correctness(row: dict[str, str]) -> bool | None:
    value = (row.get("correct") or "").strip().casefold()
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def flow_start_time(results_path: Path, rows: list[dict[str, str]]) -> float:
    timestamps: list[float] = []
    for row in rows:
        flow_path = Path(row.get("flow_path") or "")
        if not flow_path.exists():
            flow_path = results_path.parent / flow_path.name
        if not flow_path.exists():
            continue
        try:
            raw = flow_path.read_bytes()
        except OSError:
            continue
        matches = re.findall(
            rb"timestamp_start;\d+:([0-9]+(?:\.[0-9]+)?)",
            raw,
        )
        for raw_value in matches:
            value = float(raw_value)
            if 1_700_000_000 < value < 1_900_000_000:
                timestamps.append(value)
    return min(timestamps) if timestamps else results_path.stat().st_mtime


def collect_data() -> tuple[dict[str, object], list[dict[str, object]]]:
    canonical_rows = read_results(CANONICAL_RESULTS)
    tasks = list(dict.fromkeys(row["task"] for row in canonical_rows))
    if len(tasks) != EXPECTED_TASKS:
        raise RuntimeError(f"expected {EXPECTED_TASKS} canonical tasks, found {len(tasks)}")

    report_runs: list[tuple[Path, list[dict[str, str]]]] = []
    for results_path in REPORT_ROOT.glob("*/results.csv"):
        try:
            rows = read_results(results_path)
        except (OSError, csv.Error):
            continue
        report_runs.append((results_path, rows))

    baseline_rows: dict[str, tuple[float, dict[str, str]]] = {}
    for _, rows in report_runs:
        for row in rows:
            task = row.get("task")
            if row.get("arm") != "baseline" or task not in tasks:
                continue
            cost = positive_cost(row)
            if cost is None:
                continue
            previous = baseline_rows.get(task)
            if previous is None or cost < previous[0]:
                baseline_rows[task] = (cost, row)

    missing_baselines = [task for task in tasks if task not in baseline_rows]
    if missing_baselines:
        raise RuntimeError(f"missing non-zero baseline costs: {missing_baselines}")
    baseline_cost = {task: selected[0] for task, selected in baseline_rows.items()}
    baseline_correctness = [reported_correctness(selected[1]) for selected in baseline_rows.values()]
    baseline_reported = [value for value in baseline_correctness if value is not None]
    baseline = {
        "label": "CC",
        "tasks_run": len(tasks),
        "correct_tasks": sum(baseline_reported),
        "correctness_tasks": len(baseline_reported),
        "baseline_cost": sum(baseline_cost.values()),
    }

    experiments: list[dict[str, object]] = []
    for results_path, rows in report_runs:
        atelier_rows = [
            row
            for row in rows
            if row.get("arm") == "atelier" and row.get("task") in baseline_cost and positive_cost(row) is not None
        ]
        if not atelier_rows:
            continue

        task_rows: dict[str, tuple[float, dict[str, str]]] = {}
        for row in atelier_rows:
            task = row["task"]
            cost = positive_cost(row)
            assert cost is not None
            previous = task_rows.get(task)
            if previous is None or cost < previous[0]:
                task_rows[task] = (cost, row)

        task_costs = {task: selected[0] for task, selected in task_rows.items()}
        correctness_values = [reported_correctness(selected[1]) for selected in task_rows.values()]
        reported_correctness_values = [value for value in correctness_values if value is not None]
        correct_tasks = sum(reported_correctness_values)
        correctness_tasks = len(reported_correctness_values)

        pooled_baseline = sum(baseline_cost[task] for task in task_costs)
        pooled_atelier = sum(task_costs.values())
        savings = 100.0 * (pooled_baseline - pooled_atelier) / pooled_baseline
        experiments.append(
            {
                "name": results_path.parent.name,
                "started_at": flow_start_time(results_path, atelier_rows),
                "tasks_run": len(task_costs),
                "baseline_cost": pooled_baseline,
                "atelier_cost": pooled_atelier,
                "savings": savings,
                "correct_tasks": correct_tasks,
                "correctness_tasks": correctness_tasks,
            }
        )

    experiments.sort(
        key=lambda experiment: (
            float(experiment["started_at"]),
            str(experiment["name"]),
        )
    )
    for sequence, experiment in enumerate(experiments, 1):
        experiment["sequence"] = sequence
    filtered_experiments = [
        experiment
        for experiment in experiments
        if int(experiment["tasks_run"]) >= MIN_TASKS_PER_EXPERIMENT
        and float(experiment["savings"]) >= MIN_SAVINGS_PERCENT
    ]
    return baseline, filtered_experiments


def experiment_header(experiment: dict[str, object]) -> str:
    timestamp = datetime.fromtimestamp(
        float(experiment["started_at"]),
        UTC,
    ).strftime("%Y%m%dT%H%M%SZ")
    return f"exp{int(experiment['sequence']):02d}__{timestamp}__{experiment['name']}"


def write_csv(
    baseline: dict[str, object],
    experiments: list[dict[str, object]],
) -> None:
    headers = ["metric", "CC"]
    headers.extend(experiment_header(experiment) for experiment in experiments)

    rows = [
        [
            "savings_percent",
            "0.00",
            *[f"{float(experiment['savings']):.2f}" for experiment in experiments],
        ],
        [
            "correctness_percent",
            f"{100 * int(baseline['correct_tasks']) / int(baseline['tasks_run']):.2f}",
            *[
                f"{100 * int(experiment['correct_tasks']) / int(experiment['tasks_run']):.2f}"
                for experiment in experiments
            ],
        ],
        [
            "correct_tasks",
            str(baseline["correct_tasks"]),
            *[str(experiment["correct_tasks"]) for experiment in experiments],
        ],
        [
            "correctness_tasks_reported",
            str(baseline["correctness_tasks"]),
            *[str(experiment["correctness_tasks"]) for experiment in experiments],
        ],
        [
            "tasks_run",
            str(baseline["tasks_run"]),
            *[str(experiment["tasks_run"]) for experiment in experiments],
        ],
        [
            "pooled_baseline_cost_usd",
            f"{float(baseline['baseline_cost']):.6f}",
            *[f"{float(experiment['baseline_cost']):.6f}" for experiment in experiments],
        ],
        [
            "pooled_atelier_cost_usd",
            "",
            *[f"{float(experiment['atelier_cost']):.6f}" for experiment in experiments],
        ],
    ]

    with CSV_OUTPUT.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


def svg_text(value: object) -> str:
    return html.escape(str(value))


def write_svg(
    baseline: dict[str, object],
    experiments: list[dict[str, object]],
) -> None:
    width = 1900
    height = 700
    left = 95
    right = 35
    top = 105
    bottom = 135
    chart_width = width - left - right
    chart_height = height - top - bottom
    chart_bottom = top + chart_height

    savings_values = [
        0.0,
        *[float(experiment["savings"]) for experiment in experiments],
    ]
    correctness_values = [
        100 * int(baseline["correct_tasks"]) / int(baseline["tasks_run"]),
        *[100 * int(experiment["correct_tasks"]) / int(experiment["tasks_run"]) for experiment in experiments],
    ]
    percent_values = [*savings_values, *correctness_values]
    percent_min = math.floor(min(percent_values) / 50) * 50
    percent_max = math.ceil(max(percent_values) / 50) * 50
    if percent_min == percent_max:
        percent_max = percent_min + 50

    def x_position(index: int) -> float:
        return left + chart_width * index / (len(savings_values) - 1)

    def y_position(value: float) -> float:
        return top + ((percent_max - value) * chart_height / (percent_max - percent_min))

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" role="img" '
            'aria-labelledby="title desc">'
        ),
        '<title id="title">Atelier cost savings and correctness by experiment</title>',
        (
            '<desc id="desc">Pooled cost savings and correctness percentage '
            "by experiment. CC is the Claude Code baseline. "
            "Experiments require at least three tasks and savings below "
            "-100 percent are excluded.</desc>"
        ),
        '<rect width="100%" height="100%" rx="12" fill="#ffffff"/>',
        (
            "<style>text{font-family:ui-sans-serif,system-ui,-apple-system,"
            'BlinkMacSystemFont,"Segoe UI",sans-serif}.title{font-size:24px;'
            "font-weight:750;fill:#111827}.subtitle{font-size:13px;"
            "fill:#4b5563}.tick{font-size:10px;fill:#4b5563}.axis{"
            "font-size:12px;fill:#374151}</style>"
        ),
        ('<text class="title" x="24" y="38">Atelier cost savings and correctness by experiment</text>'),
        (
            f'<text class="subtitle" x="24" y="64">CC baseline plus '
            f"{len(experiments)} qualifying experiments · 3+ tasks per "
            "experiment · savings outliers below -100% excluded</text>"
        ),
        (
            '<text class="subtitle" x="24" y="84">Both lines use percent: '
            "pooled cost savings and correct tasks / all tasks run x 100."
            "</text>"
        ),
    ]
    for tick in range(percent_min, percent_max + 1, 50):
        y = y_position(float(tick))
        stroke = "#6b7280" if tick == 0 else "#d1d5db"
        stroke_width = "1.5" if tick == 0 else "1"
        parts.append(
            f'<line x1="{left}" x2="{width - right}" y1="{y:.2f}" '
            f'y2="{y:.2f}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )
        parts.append(f'<text class="axis" x="{left - 12}" y="{y + 4:.2f}" text-anchor="end">{tick:+d}%</text>')

    savings_coordinates = [
        f"{x_position(index):.2f},{y_position(value):.2f}" for index, value in enumerate(savings_values)
    ]
    parts.append(
        f'<polyline points="{" ".join(savings_coordinates)}" fill="none" '
        'stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round" '
        'stroke-linecap="round"/>'
    )

    correctness_segments: list[list[str]] = []
    correctness_segment: list[str] = []
    for index, value in enumerate(correctness_values):
        if value is None:
            if len(correctness_segment) >= 2:
                correctness_segments.append(correctness_segment)
            correctness_segment = []
            continue
        correctness_segment.append(f"{x_position(index):.2f},{y_position(value):.2f}")
    if len(correctness_segment) >= 2:
        correctness_segments.append(correctness_segment)
    for segment in correctness_segments:
        parts.append(
            f'<polyline points="{" ".join(segment)}" fill="none" '
            'stroke="#7c3aed" stroke-width="2.5" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )

    baseline_x = x_position(0)
    baseline_savings_y = y_position(0)
    parts.append(
        f'<circle cx="{baseline_x:.2f}" cy="{baseline_savings_y:.2f}" r="5" '
        'fill="#1d4ed8" stroke="#ffffff" stroke-width="2">'
        "<title>CC baseline · 0.00% savings</title></circle>"
    )
    baseline_correct = int(baseline["correct_tasks"])
    baseline_tasks = int(baseline["tasks_run"])
    baseline_correctness = 100 * baseline_correct / baseline_tasks
    parts.append(
        f'<circle cx="{baseline_x:.2f}" '
        f'cy="{y_position(baseline_correctness):.2f}" r="5" '
        'fill="#7c3aed" stroke="#ffffff" stroke-width="2">'
        f"<title>CC baseline · {baseline_correct}/{baseline_tasks} tasks "
        f"correct · {baseline_correctness:.2f}%</title></circle>"
    )
    parts.append(
        f'<text class="tick" x="{baseline_x:.2f}" '
        f'y="{chart_bottom + 19}" text-anchor="middle" '
        'font-weight="700">CC</text>'
    )

    for index, experiment in enumerate(experiments, 1):
        savings = float(experiment["savings"])
        x = x_position(index)
        fill = "#16a34a" if savings >= 0 else "#dc2626"
        timestamp = datetime.fromtimestamp(
            float(experiment["started_at"]),
            UTC,
        ).isoformat(timespec="seconds")
        sequence = int(experiment["sequence"])
        savings_tooltip = (
            f"exp{sequence:02d} · {experiment['name']} · {timestamp} · "
            f"{savings:.2f}% savings · {experiment['tasks_run']} tasks · "
            f"baseline USD {float(experiment['baseline_cost']):.6f} · "
            f"Atelier USD {float(experiment['atelier_cost']):.6f}"
        )
        parts.append(
            f'<circle cx="{x:.2f}" '
            f'cy="{y_position(savings):.2f}" r="4.5" fill="{fill}" '
            'stroke="#ffffff" stroke-width="1.5">'
            f"<title>{svg_text(savings_tooltip)}</title></circle>"
        )

        correct_tasks = int(experiment["correct_tasks"])
        tasks_run = int(experiment["tasks_run"])
        correctness = 100 * correct_tasks / tasks_run
        correctness_tooltip = (
            f"exp{sequence:02d} · {experiment['name']} · {correct_tasks}/{tasks_run} tasks correct · {correctness:.2f}%"
        )
        parts.append(
            f'<circle cx="{x:.2f}" '
            f'cy="{y_position(correctness):.2f}" r="4.5" '
            'fill="#7c3aed" stroke="#ffffff" stroke-width="1.5">'
            f"<title>{svg_text(correctness_tooltip)}</title></circle>"
        )
        parts.append(
            f'<text class="tick" x="{x:.2f}" y="{chart_bottom + 19}" '
            f'text-anchor="end" transform="rotate(-65 {x:.2f} '
            f'{chart_bottom + 19})">{sequence:02d}</text>'
        )

    parts.append(
        f'<text class="axis" x="22" y="{top + chart_height / 2:.2f}" '
        f'text-anchor="middle" transform="rotate(-90 22 '
        f'{top + chart_height / 2:.2f})">Percent</text>'
    )
    parts.append(
        f'<text class="subtitle" x="{left}" y="{height - 20}">Blue line: '
        "cost savings (green cheaper, red more expensive). Purple line: "
        "correct tasks / all tasks run x 100. Exact values and counts are in "
        "optimization_savings.csv.</text>"
    )
    parts.append("</svg>")
    SVG_OUTPUT.write_text("\n".join(parts) + "\n")


def main() -> None:
    baseline, experiments = collect_data()
    PUBLIC_ROOT.mkdir(parents=True, exist_ok=True)
    write_csv(baseline, experiments)
    write_svg(baseline, experiments)
    print(f"wrote {CSV_OUTPUT} and {SVG_OUTPUT} (CC baseline + {len(experiments)} experiment points)")


if __name__ == "__main__":
    main()
