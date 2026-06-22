#!/usr/bin/env python3
"""Render autoresearch/results.tsv -> autoresearch/progress.png.

Utility (not part of the fixed objective). Degrades gracefully if matplotlib
is not installed. Mirrors plot.py in the reference repos: scatter of every
experiment coloured by status, with the running-best line over kept runs.

    uv run python autoresearch/plot.py [path/to/results.tsv]
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS_COLORS = {"keep": "tab:green", "discard": "tab:gray", "crash": "tab:red"}


def _f(value: str | None) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "results.tsv"
    if not src.exists():
        print(f"no results file at {src}")
        return 1
    with src.open() as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if not rows:
        print("no rows to plot")
        return 1

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"matplotlib not installed; skipping plot ({len(rows)} rows logged)")
        return 0

    xs = list(range(1, len(rows) + 1))
    scores = [_f(r.get("score")) for r in rows]
    colors = [STATUS_COLORS.get(r.get("status", ""), "tab:blue") for r in rows]

    best = float("-inf")
    running: list[float | None] = []
    for r, s in zip(rows, scores, strict=True):
        if r.get("status") == "keep" and s is not None and s > best:
            best = s
        running.append(best if best != float("-inf") else None)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.scatter(
        xs,
        [s if s is not None else float("nan") for s in scores],
        c=colors,
        zorder=3,
    )
    rb_x = [x for x, v in zip(xs, running, strict=True) if v is not None]
    rb_y = [v for v in running if v is not None]
    if rb_y:
        ax.plot(rb_x, rb_y, color="tab:green", lw=2, label="running best")
        ax.legend()
    ax.set_xlabel("experiment")
    ax.set_ylabel("score (higher = better)")
    ax.set_title("autoresearch: Atelier auto-improvement")
    fig.tight_layout()
    out = HERE / "progress.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
