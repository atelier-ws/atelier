"""Benchmark report renderer.

Converts a :class:`PublishReport` into a Markdown post (via Jinja2) and a
JSON bundle suitable for archiving alongside the post.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from atelier.infra.benchmarks.publisher import PublishReport, report_to_dict

_TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Jinja2 filters
# ---------------------------------------------------------------------------


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_usd(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_decimal(value: Any, places: int = 2) -> str:
    try:
        return f"{float(value):.{places}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_signed_decimal(value: Any, places: int = 2) -> str:
    try:
        v = float(value)
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.{places}f}"
    except (TypeError, ValueError):
        return "n/a"


# ---------------------------------------------------------------------------
# Delta helper
# ---------------------------------------------------------------------------

_NA = "n/a"


def _build_delta_fn(
    prior: dict[str, float | None],
    report: PublishReport,
) -> Any:
    """Return a callable ``delta(metric_name) -> str`` for use in templates."""
    current_snapshot: dict[str, float | None] = {}
    rs = report.routing_savings
    cs = report.compact_savings
    rq = report.routing_quality
    cq = report.compact_quality
    rr = report.routing_replay

    if rs:
        current_snapshot["routing_sessions"] = float(rs.sessions_benchmarked)
        current_snapshot["routing_savings_usd"] = rs.total_cost_saved_usd
    if cs:
        current_snapshot["compact_savings_usd"] = cs.total_cost_saved_usd
    if rq:
        current_snapshot["routing_quality"] = rq.avg_quality_score
    if cq:
        current_snapshot["compact_retention"] = cq.avg_retention_score
    if rr:
        current_snapshot["replay_match"] = rr.tool_match_rate

    def delta(metric: str) -> str:
        curr = current_snapshot.get(metric)
        prev = prior.get(metric)
        if curr is None or prev is None:
            return _NA
        diff = curr - prev
        pct = (diff / prev * 100) if prev != 0 else 0.0
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%"

    return delta


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_markdown(report: PublishReport) -> str:
    """Render the benchmark post template to a Markdown string."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    env.filters["fmt_int"] = _fmt_int
    env.filters["fmt_usd"] = _fmt_usd
    env.filters["fmt_decimal"] = _fmt_decimal
    env.filters["fmt_signed_decimal"] = _fmt_signed_decimal

    template = env.get_template("post.md.j2")

    delta_fn = _build_delta_fn(report.prior, report)

    ctx: dict[str, Any] = {
        "week_start": report.week_start,
        "generated_at": report.generated_at,
        "since_arg": report.since_arg,
        "corpus_arg": report.corpus_arg,
        "corpus_path": report.corpus_path,
        "routing_savings": report.routing_savings,
        "compact_savings": report.compact_savings,
        "routing_quality": report.routing_quality,
        "compact_quality": report.compact_quality,
        "routing_replay": report.routing_replay,
        "delta": delta_fn,
    }

    return template.render(**ctx)


def render_json_bundle(report: PublishReport) -> dict[str, Any]:
    """Render the full report to a JSON-serialisable dict for archiving."""
    d = report_to_dict(report)

    # Attach a current metric snapshot so next week's report can compute Δ
    rs = report.routing_savings
    cs = report.compact_savings
    rq = report.routing_quality
    cq = report.compact_quality
    rr = report.routing_replay

    snapshot: dict[str, float | None] = {
        "routing_sessions": float(rs.sessions_benchmarked) if rs else None,
        "routing_savings_usd": rs.total_cost_saved_usd if rs else None,
        "routing_quality": rq.avg_quality_score if rq else None,
        "compact_retention": cq.avg_retention_score if cq else None,
        "compact_savings_usd": cs.total_cost_saved_usd if cs else None,
        "replay_match": rr.tool_match_rate if rr else None,
    }
    d["metric_snapshot"] = snapshot
    return d
