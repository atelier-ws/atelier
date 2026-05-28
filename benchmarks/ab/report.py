"""Report generator for A/B benchmark runs — RPT-01 through RPT-06.

Usage:
    python -m ab.report --run-dir bench/runs/<run-id>/ [--commit <sha>]

Reads:
    <run-dir>/config.json     — CLI args snapshot
    <run-dir>/summary.json    — Wilson CI pass-rates per cell
    <run-dir>/raw/*.json      — Individual trial records (cost, latency)

Writes:
    <run-dir>/plots/cost_delta.png
    <run-dir>/plots/latency_delta.png
    <run-dir>/plots/quality_delta.png
    <run-dir>/report.md
"""

import argparse
import datetime
import json
import subprocess
from pathlib import Path
from typing import Any

# matplotlib imported lazily to avoid slow startup when just importing the module


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_run_dir(run_dir: Path) -> tuple[dict, dict, dict[str, list[dict]]]:
    """Return (config, summary, raw_by_cell) for a run directory.

    raw_by_cell: {"{task}__{mode}": [record, ...]}
    """
    config = json.loads((run_dir / "config.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())

    raw_by_cell: dict[str, list[dict]] = {}
    raw_dir = run_dir / "raw"
    if raw_dir.exists():
        for path in sorted(raw_dir.glob("*.json")):
            if path.name.endswith(".tmp"):
                continue
            cell_key = path.stem.rsplit("__rep", 1)[0]
            try:
                record = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            raw_by_cell.setdefault(cell_key, []).append(record)

    return config, summary, raw_by_cell


def _mean(values: list[float]) -> float | None:
    finite = [v for v in values if v is not None and v >= 0]
    return sum(finite) / len(finite) if finite else None


def compute_cell_stats(raw_by_cell: dict[str, list[dict]]) -> dict[str, dict[str, Any]]:
    """Return {cell_key: {cost_usd_mean, latency_ms_mean}} from raw records."""
    stats: dict[str, dict[str, Any]] = {}
    for cell_key, records in raw_by_cell.items():
        costs = [r.get("cost_usd", 0.0) or 0.0 for r in records]
        lats = [r.get("latency_ms", 0.0) or 0.0 for r in records]
        stats[cell_key] = {
            "cost_usd_mean": _mean(costs),
            "latency_ms_mean": _mean(lats),
        }
    return stats


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------


def compute_deltas(
    tasks: list[str],
    cell_stats: dict[str, dict],
    summary_cells: dict[str, dict],
) -> list[dict[str, Any]]:
    """Compute per-task deltas: on - off.

    Returns list of dicts with keys:
        task_id, cost_delta, latency_delta, quality_delta,
        quality_on_ci_lo, quality_on_ci_hi, quality_off_ci_lo, quality_off_ci_hi,
        cost_on, cost_off, latency_on, latency_off, quality_on, quality_off
    """
    rows = []
    for task_id in tasks:
        on_key = f"{task_id}__on"
        off_key = f"{task_id}__off"

        on_stats = cell_stats.get(on_key, {})
        off_stats = cell_stats.get(off_key, {})
        on_summary = summary_cells.get(on_key, {})
        off_summary = summary_cells.get(off_key, {})

        cost_on = on_stats.get("cost_usd_mean")
        cost_off = off_stats.get("cost_usd_mean")
        lat_on = on_stats.get("latency_ms_mean")
        lat_off = off_stats.get("latency_ms_mean")

        q_on = (on_summary.get("passed", 0) / on_summary["total"]) if on_summary.get("total") else None
        q_off = (off_summary.get("passed", 0) / off_summary["total"]) if off_summary.get("total") else None

        rows.append(
            {
                "task_id": task_id,
                "cost_on": cost_on,
                "cost_off": cost_off,
                "cost_delta": (cost_on - cost_off) if (cost_on is not None and cost_off is not None) else None,
                "latency_on": lat_on,
                "latency_off": lat_off,
                "latency_delta": (lat_on - lat_off) if (lat_on is not None and lat_off is not None) else None,
                "quality_on": q_on,
                "quality_off": q_off,
                "quality_delta": (q_on - q_off) if (q_on is not None and q_off is not None) else None,
                "quality_on_ci_lo": on_summary.get("ci_lower"),
                "quality_on_ci_hi": on_summary.get("ci_upper"),
                "quality_off_ci_lo": off_summary.get("ci_lower"),
                "quality_off_ci_hi": off_summary.get("ci_upper"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Plot generation (RPT-01)
# ---------------------------------------------------------------------------


def _bar_plot(
    out_path: Path,
    task_labels: list[str],
    values: list[float | None],
    yerr_lo: list[float | None],
    yerr_hi: list[float | None],
    title: str,
    ylabel: str,
    zero_label: str = "no change",
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(max(8, len(task_labels) * 0.9), 5))
    x = range(len(task_labels))
    colors = []
    bar_values = []
    err_lo = []
    err_hi = []

    for v, lo, hi in zip(values, yerr_lo, yerr_hi, strict=False):
        bar_values.append(v if v is not None else 0.0)
        colors.append("steelblue" if v is None or v == 0 else ("tomato" if v > 0 else "seagreen"))
        err_lo.append(abs(lo) if lo is not None else 0.0)
        err_hi.append(abs(hi) if hi is not None else 0.0)

    ax.bar(x, bar_values, color=colors, yerr=[err_lo, err_hi], capsize=4, error_kw={"elinewidth": 1.5})
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_xticks(list(x))
    ax.set_xticklabels(task_labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{title}\n(positive = on higher; {zero_label})", fontsize=10)
    ax.text(
        0.99,
        0.01,
        "red = on higher / green = on lower",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=7,
        color="gray",
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def generate_plots(run_dir: Path, deltas: list[dict]) -> None:
    """Write three delta PNG plots to <run_dir>/plots/."""
    tasks = [d["task_id"] for d in deltas]

    # Cost delta plot
    _bar_plot(
        run_dir / "plots" / "cost_delta.png",
        tasks,
        [d["cost_delta"] for d in deltas],
        [0.0] * len(tasks),
        [0.0] * len(tasks),
        title="Cost delta (Atelier-on minus Atelier-off)",
        ylabel="Δ cost (USD)",
    )

    # Latency delta plot
    _bar_plot(
        run_dir / "plots" / "latency_delta.png",
        tasks,
        [d["latency_delta"] for d in deltas],
        [0.0] * len(tasks),
        [0.0] * len(tasks),
        title="Latency delta (Atelier-on minus Atelier-off)",
        ylabel="Δ latency (ms)",
    )

    # Quality delta plot — with CI error bars
    q_deltas = [d["quality_delta"] for d in deltas]
    q_err_lo = [abs((d["quality_delta"] or 0) - (d["quality_off_ci_lo"] or d["quality_delta"] or 0)) for d in deltas]
    q_err_hi = [abs((d["quality_on_ci_hi"] or d["quality_delta"] or 0) - (d["quality_delta"] or 0)) for d in deltas]
    _bar_plot(
        run_dir / "plots" / "quality_delta.png",
        tasks,
        q_deltas,
        q_err_lo,
        q_err_hi,
        title="Pass-rate delta (Atelier-on minus Atelier-off)",
        ylabel="Δ pass-rate",
        zero_label="no quality difference",
    )


# ---------------------------------------------------------------------------
# Markdown report (RPT-02 through RPT-06)
# ---------------------------------------------------------------------------

_NA = "n/a"


def _fmt(val: float | None, fmt: str = ".4f") -> str:
    return f"{val:{fmt}}" if val is not None else _NA


def _sign(val: float | None) -> str:
    if val is None:
        return _NA
    return f"+{val:.4f}" if val >= 0 else f"{val:.4f}"


def generate_report_md(
    run_dir: Path,
    config: dict,
    summary: dict,
    deltas: list[dict],
    commit_sha: str,
) -> None:
    """Write report.md to run_dir (RPT-02 through RPT-06)."""
    run_id = config.get("run_id", run_dir.name)
    model = config.get("model", "unknown")
    n_reps = config.get("n_reps", "?")
    modes = config.get("modes", ["on", "off"])
    tasks = config.get("tasks", [d["task_id"] for d in deltas])
    suite = config.get("suite", "terminalbench")
    started_at = config.get("started_at", "unknown")

    cli_cmd = (
        f"python -m ab.runner --suite {suite} --tasks {len(tasks)} "
        f"--n {n_reps} --models {model} --modes {','.join(modes)} --out bench/runs/{run_id}/"
    )

    lines: list[str] = []

    lines += [
        f"# Benchmark Report: {run_id}",
        "",
        f"**Generated:** {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    # Methodology (RPT-02)
    lines += [
        "## Methodology",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Model | `{model}` |",
        f"| Suite | {suite} |",
        f"| Tasks | {len(tasks)} |",
        f"| Repetitions | {n_reps} |",
        f"| Modes | {', '.join(modes)} |",
        "| Harness | TerminalBench 0.2.18 |",
        f"| Commit | `{commit_sha}` |",
        f"| Started | {started_at} |",
        "",
        "**Reproduce:**",
        "```bash",
        cli_cmd,
        "```",
        "",
    ]

    # Plots (RPT-01 images in markdown)
    lines += [
        "## Delta Plots",
        "",
        "![Cost Delta](plots/cost_delta.png)",
        "![Latency Delta](plots/latency_delta.png)",
        "![Quality Delta](plots/quality_delta.png)",
        "",
    ]

    # Headline table (RPT-03 + RPT-04)
    lines += [
        "## Results",
        "",
        "| Task | Cost On | Cost Off | Δ Cost | Lat On (ms) | Lat Off (ms) | Δ Lat | Q On | Q Off | Δ Q | 95% CI |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for d in deltas:
        task = d["task_id"]
        raw_dir = run_dir / "raw"
        # Link transcript: first raw file for this task (on arm)
        on_file = raw_dir / f"{task}__on__rep1.json"
        off_file = raw_dir / f"{task}__off__rep1.json"
        on_link = f"[on](raw/{task}__on__rep1.json)" if on_file.exists() else "on"
        off_link = f"[off](raw/{task}__off__rep1.json)" if off_file.exists() else "off"

        ci_lo = d.get("quality_on_ci_lo")
        ci_hi = d.get("quality_on_ci_hi")
        ci_str = f"[{_fmt(ci_lo, '.3f')}, {_fmt(ci_hi, '.3f')}]" if ci_lo is not None else _NA

        lines.append(
            f"| {task} "
            f"| {on_link} {_fmt(d['cost_on'], '.4f')} "
            f"| {off_link} {_fmt(d['cost_off'], '.4f')} "
            f"| {_sign(d['cost_delta'])} "
            f"| {_fmt(d['latency_on'], '.0f')} "
            f"| {_fmt(d['latency_off'], '.0f')} "
            f"| {_sign(d['latency_delta'])} "
            f"| {_fmt(d['quality_on'], '.3f')} "
            f"| {_fmt(d['quality_off'], '.3f')} "
            f"| {_sign(d['quality_delta'])} "
            f"| {ci_str} |"
        )
    lines.append("")

    # Losses section (RPT-05)
    lines += ["## Losses", ""]
    cost_losses = [d for d in deltas if d["cost_delta"] is not None and d["cost_delta"] > 0]
    lat_losses = [d for d in deltas if d["latency_delta"] is not None and d["latency_delta"] > 0]
    qual_losses = [d for d in deltas if d["quality_delta"] is not None and d["quality_delta"] < 0]

    if not (cost_losses or lat_losses or qual_losses):
        lines.append("_No losses this run — Atelier-on was not slower, costlier, or lower quality._")
    else:
        if cost_losses:
            lines += [
                "### Cost losses (Atelier-on was more expensive)",
                "",
                "| Task | Δ Cost (USD) |",
                "|---|---|",
            ]
            for d in cost_losses:
                lines.append(f"| {d['task_id']} | {_sign(d['cost_delta'])} |")
            lines.append("")

        if lat_losses:
            lines += [
                "### Latency losses (Atelier-on was slower)",
                "",
                "| Task | Δ Latency (ms) |",
                "|---|---|",
            ]
            for d in lat_losses:
                lines.append(f"| {d['task_id']} | {_sign(d['latency_delta'])} |")
            lines.append("")

        if qual_losses:
            lines += [
                "### Quality losses (Atelier-on had lower pass-rate)",
                "",
                "| Task | Δ Pass-rate |",
                "|---|---|",
            ]
            for d in qual_losses:
                lines.append(f"| {d['task_id']} | {_sign(d['quality_delta'])} |")
            lines.append("")

    lines.append("")

    (run_dir / "report.md").write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(prog="ab.report", description="Generate A/B benchmark report")
    parser.add_argument("--run-dir", required=True, help="Path to run directory")
    parser.add_argument("--commit", default=None, help="Git commit SHA to embed (default: auto)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    commit_sha = args.commit or _git_sha()

    print(f"Loading run: {run_dir}")
    config, summary, raw_by_cell = load_run_dir(run_dir)

    cell_stats = compute_cell_stats(raw_by_cell)
    tasks = config.get("tasks", list({k.rsplit("__", 1)[0] for k in summary["cells"]}))
    deltas = compute_deltas(tasks, cell_stats, summary["cells"])

    print("Generating plots...")
    generate_plots(run_dir, deltas)

    print("Generating report.md...")
    generate_report_md(run_dir, config, summary, deltas, commit_sha)

    print(f"Done. Report: {run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
