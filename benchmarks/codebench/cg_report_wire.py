"""Corrected codegraph A/B table that counts MAIN + SUBAGENT token usage.

The default cg_report reads tokens/tool-calls from results.jsonl, which copies
the `claude -p` receipt's `usage` field and `num_turns` -- both cover only the
MAIN agent. The stock Claude Code baseline routinely delegates discovery to an
Explore subagent, so its tokens and tool calls were undercounted 10-40x, while
Atelier works inline and was fully counted.

This recovers the true token + tool-call counts straight from the mitmproxy
.flow captures (every /v1/messages round-trip, main agent + every subagent).

Cost and wall-clock TIME are taken from the receipt (results.jsonl): the
receipt's `total_cost_usd` already rolls up subagent spend (a baseline whose
main agent prices to ~$0.06 reports ~$0.43 once its subagent is billed) and is
Claude's authoritative figure, and wall-clock time was always measured
correctly. Only tokens + tool-calls were affected by the bug.

Usage: uv run python -m benchmarks.codebench.cg_report_wire <run_dir>
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader

TASK_ORDER = [
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
FLOW_RE = re.compile(r"^(cg_[a-z]+)_(baseline|atelier)_rep(\d+)\.flow$")


def _parse_response(b: bytes) -> tuple[int, int, int, int, int]:
    """One streamed response -> (input, cache_read, cache_create, output, tool_uses)."""
    inp = cr = cc = out = tools = 0
    for raw in b.split(b"\n"):
        raw = raw.strip()
        if not raw.startswith(b"data:"):
            continue
        try:
            ev = json.loads(raw[5:].strip())
        except Exception:
            continue
        t = ev.get("type")
        if t == "message_start":
            u = ev.get("message", {}).get("usage", {})
            inp += int(u.get("input_tokens", 0))
            cr += int(u.get("cache_read_input_tokens", 0))
            cc += int(u.get("cache_creation_input_tokens", 0))
        elif t == "content_block_start":
            if ev.get("content_block", {}).get("type") == "tool_use":
                tools += 1
        elif t == "message_delta":
            out = int(ev.get("usage", {}).get("output_tokens", out))
    return inp, cr, cc, out, tools


def _parse_flow(path: Path) -> dict[str, float]:
    """True wire totals for one run: tokens (all components) + tool_use count."""
    inp = cr = cc = out = tools = 0
    with open(path, "rb") as f:
        for flow in FlowReader(f).stream():
            req = getattr(flow, "request", None)
            if req is None or "/v1/messages" not in req.path:
                continue
            resp = getattr(flow, "response", None)
            if resp is None or not resp.content:
                continue
            i, r, c, o, n = _parse_response(resp.content)
            inp += i
            cr += r
            cc += c
            out += o
            tools += n
    return {"tokens": float(inp + cr + cc + out), "turns": float(tools)}


def _receipt(run_dir: Path) -> dict[tuple[str, str, int], dict[str, float]]:
    """Per-run cost ($) + wall-clock time (s) from the authoritative receipt."""
    out: dict[tuple[str, str, int], dict[str, float]] = {}
    path = run_dir / "results.jsonl"
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("ok") and not row.get("timed_out"):
            out[(row["task"], row["arm"], int(row["rep"]))] = {
                "cost": float(row.get("cost_usd", 0.0)),
                "time": float(row.get("duration_ms", 0)) / 1000.0,
            }
    return out


def _phrase(metric: str, pct: float | None) -> str:
    if pct is None:
        return "n/a"
    if abs(pct) < 3:
        return "even"
    mag = abs(pct)
    if metric == "cost":
        word = "cheaper" if pct > 0 else "pricier"
    elif metric == "time":
        word = "faster" if pct > 0 else "slower"
    else:
        word = "fewer" if pct > 0 else "more"
    return f"{mag:g}% {word}"


def _pct(base: float, atel: float) -> float | None:
    return None if base == 0 else round((1 - atel / base) * 100, 1)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: cg_report_wire <run_dir>", file=sys.stderr)
        return 2
    run_dir = Path(argv[0])
    receipt = _receipt(run_dir)

    runs: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
    for fp in sorted(run_dir.glob("*.flow")):
        fm = FLOW_RE.match(fp.name)
        if not fm:
            continue
        task, arm, rep = fm.group(1), fm.group(2), int(fm.group(3))
        rcpt = receipt.get((task, arm, rep))
        if rcpt is None:  # timed-out / errored run: drop, matching cg_report
            continue
        rec = _parse_flow(fp)
        rec["cost"] = rcpt["cost"]
        rec["time"] = rcpt["time"]
        runs[(task, arm)].append(rec)

    med: dict[tuple[str, str], dict[str, float]] = {}
    for key, recs in runs.items():
        med[key] = {m: statistics.median([r[m] for r in recs]) for m in METRICS}

    present = [(t, d) for t, d in TASK_ORDER if (t, "baseline") in med and (t, "atelier") in med]

    lines = ["| Codebase | Cost | Tokens | Time | Tool calls |", "| --- | --- | --- | --- | --- |"]
    for task, disp in present:
        b, a = med[(task, "baseline")], med[(task, "atelier")]
        cells = [_phrase(m, _pct(b[m], a[m])) for m in METRICS]
        lines.append(f"| {disp} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")
    if present:
        pooled = []
        for m in METRICS:
            bt = sum(med[(t, "baseline")][m] for t, _ in present)
            at = sum(med[(t, "atelier")][m] for t, _ in present)
            pooled.append(_phrase(m, _pct(bt, at)))
        lines.append(f"| **Overall (pooled)** | {pooled[0]} | {pooled[1]} | {pooled[2]} | {pooled[3]} |")

    lines += [
        "",
        "| Codebase | arm | cost_usd | tokens | time_s | tool_calls | reps |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for task, disp in TASK_ORDER:
        for arm in ARMS:
            if (task, arm) not in med:
                continue
            v = med[(task, arm)]
            n = len(runs[(task, arm)])
            lines.append(
                f"| {disp} | {arm} | {v['cost']:.4f} | {v['tokens']:,.0f} | {v['time']:.1f} | {v['turns']:.0f} | {n} |"
            )

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
