"""ANSI terminal reporter for TerminalBench run results.

Provides colour-coded run summaries and side-by-side mode comparison tables.
Uses only ANSI escape codes — no rich, click, or other third-party deps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# ANSI colour constants (matches benchmarks/mcp_tools/reporter.py)
# ---------------------------------------------------------------------------

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_DIM = "\033[2m"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verdict_color(verdict: str | None) -> str:
    """Return the ANSI colour code for a grader verdict string."""
    if verdict == "pass":
        return _GREEN
    if verdict in ("fail", "error"):
        return _RED
    return _YELLOW


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_run_summary(result: Any) -> str:
    """Render a single-run summary with colour-coded verdict and metrics.

    Args:
        result: An ``AdapterResult`` instance.

    Returns:
        Multi-line string ready for ``print()``.
    """
    vc = _verdict_color(result.grader_verdict)
    verdict_str = result.grader_verdict if result.grader_verdict is not None else "unknown"

    lines = [
        f"{_BOLD}{_CYAN}● {result.task_id}{_RESET}  " f"[mode={result.mode}  rep={result.rep}]",
        f"  Verdict: {vc}{_BOLD}{verdict_str.upper()}{_RESET}",
        (
            f"  tokens={result.input_tokens}in/{result.output_tokens}out  "
            f"cost=${result.cost_usd:.4f}  "
            f"latency={result.latency_ms:.0f}ms  "
            f"turns={result.num_turns}"
        ),
    ]
    if result.claude_error:
        lines.append(f"  {_RED}Error: {result.claude_error}{_RESET}")
    return "\n".join(lines)


def render_mode_comparison(
    on_result: Any,
    off_result: Any,
) -> str:
    """Render a side-by-side comparison table for ON vs OFF arms.

    Shows token counts, cost, and latency deltas with colour coding:
    green if the ON arm is cheaper/faster, red if it is more expensive/slower.

    Args:
        on_result:  ``AdapterResult`` for the ``bench_mode="on"`` arm.
        off_result: ``AdapterResult`` for the ``bench_mode="off"`` arm.

    Returns:
        Multi-line string ready for ``print()``.
    """
    task_id = on_result.task_id

    col_w = 12

    def _fmt_verdict(r: Any) -> str:
        v = r.grader_verdict or "unknown"
        vc = _verdict_color(r.grader_verdict)
        return f"{vc}{v.upper()}{_RESET}"

    def _delta_color(delta: float) -> str:
        """Green if delta <= 0 (ON cheaper/faster), red if > 0."""
        return _GREEN if delta <= 0 else _RED

    tok_delta = on_result.input_tokens - off_result.input_tokens
    cost_delta = on_result.cost_usd - off_result.cost_usd
    lat_delta = on_result.latency_ms - off_result.latency_ms

    tok_dc = _delta_color(tok_delta)
    cost_dc = _delta_color(cost_delta)
    lat_dc = _delta_color(lat_delta)

    # Header
    lines = [
        f"{_BOLD}{_CYAN}▶ {task_id}{_RESET}  mode comparison",
        f"  {'':>{col_w}}  {'verdict':<10}  {'tokens_in':>10}  {'cost':>8}  {'latency_ms':>10}",
        f"  {'─' * col_w}  {'─' * 10}  {'─' * 10}  {'─' * 8}  {'─' * 10}",
        # ON row
        (
            f"  {'ON':>{col_w}}  {_fmt_verdict(on_result):<10}  "
            f"{on_result.input_tokens:>10}  "
            f"${on_result.cost_usd:>7.4f}  "
            f"{on_result.latency_ms:>10.0f}"
        ),
        # OFF row
        (
            f"  {'OFF':>{col_w}}  {_fmt_verdict(off_result):<10}  "
            f"{off_result.input_tokens:>10}  "
            f"${off_result.cost_usd:>7.4f}  "
            f"{off_result.latency_ms:>10.0f}"
        ),
        f"  {'─' * col_w}  {'─' * 10}  {'─' * 10}  {'─' * 8}  {'─' * 10}",
        # Delta row
        (
            f"  {'Delta ON-OFF':>{col_w}}  {'':10}  "
            f"{tok_dc}{tok_delta:>+10}{_RESET}  "
            f"{cost_dc}${cost_delta:>+7.4f}{_RESET}  "
            f"{lat_dc}{lat_delta:>+10.0f}{_RESET}"
        ),
    ]
    return "\n".join(lines)
