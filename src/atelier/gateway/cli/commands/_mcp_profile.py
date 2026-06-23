"""MCP tool latency profiling with history + drift detection.

Backing logic for ``atelier profile``. Drives the MCP dispatch (``_handle``) for
a representative set of tool calls against a target repo, measures cold + warm
latency per tool, and compares a run against the last recorded one so latency
drift is visible. History is plain JSONL (one run per line, newest last), keyed
by git sha/branch, so the comparison is computed from the file itself -- nothing
ephemeral.
"""

from __future__ import annotations

import json
import os
import statistics as st
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Representative, deterministic, read-only calls covering the hot code-intel
# tools. Queries are fixed so runs stay comparable over time. ``edit`` mutates,
# so it is profiled separately against a self-contained scratch file.
READ_ONLY_CALLS: list[tuple[str, dict[str, Any]]] = [
    ("read", {"path": "README.md"}),
    ("grep", {"regex": "def ", "path": "src/atelier/core", "mode": "file_paths_only"}),
    ("search", {"query": "edit verify gate", "path": "."}),
    ("explore", {"query": "render tool result text"}),
]
DEFAULT_HISTORY_REL = "reports/perf/mcp_latency_history.jsonl"


def default_history_path(repo: Path) -> Path:
    return repo / DEFAULT_HISTORY_REL


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _call(handle: Callable[[dict[str, Any]], Any], name: str, args: dict[str, Any], rid: int) -> None:
    handle({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}})


def _time_tool(
    handle: Callable[[dict[str, Any]], Any],
    name: str,
    args: dict[str, Any],
    *,
    warmup: int,
    runs: int,
    base_rid: int,
) -> dict[str, Any]:
    """Return cold (first in-process call) and warm-median latency in ms."""
    t0 = time.perf_counter()
    _call(handle, name, args, base_rid)
    cold = (time.perf_counter() - t0) * 1000
    for i in range(warmup):
        _call(handle, name, args, base_rid + 1 + i)
    samples: list[float] = []
    for i in range(runs):
        t = time.perf_counter()
        _call(handle, name, args, base_rid + 1 + warmup + i)
        samples.append((time.perf_counter() - t) * 1000)
    return {
        "cold_ms": round(cold, 1),
        "warm_ms": round(st.median(samples), 1),
        "warm_p95_ms": round(max(samples), 1),
        "runs": runs,
    }


def _profile_edit(
    handle: Callable[[dict[str, Any]], Any],
    repo: Path,
    *,
    warmup: int,
    runs: int,
    base_rid: int,
) -> dict[str, Any] | None:
    """Profile ``edit`` against a throwaway file created+removed in the repo."""
    scratch = repo / "._perf_edit_probe.py"
    try:
        scratch.write_text("VALUE = 0\n", encoding="utf-8")
        rel = scratch.name
        flip = {"0": "1", "1": "0"}
        samples: list[float] = []
        cold = 0.0
        cur = "0"
        for i in range(1 + warmup + runs):
            nxt = flip[cur]
            t = time.perf_counter()
            _call(
                handle,
                "edit",
                {"edits": [{"path": rel, "old_string": f"VALUE = {cur}", "new_string": f"VALUE = {nxt}"}]},
                base_rid + i,
            )
            dt = (time.perf_counter() - t) * 1000
            cur = nxt
            if i == 0:
                cold = dt
            elif i >= 1 + warmup:
                samples.append(dt)
        if not samples:
            return None
        return {
            "cold_ms": round(cold, 1),
            "warm_ms": round(st.median(samples), 1),
            "warm_p95_ms": round(max(samples), 1),
            "runs": runs,
        }
    finally:
        scratch.unlink(missing_ok=True)


def run_profile(repo: Path, *, warmup: int = 2, runs: int = 7, include_edit: bool = True) -> dict[str, Any]:
    """Profile the MCP tools against *repo* and return a run record."""
    os.environ["ATELIER_WORKSPACE_ROOT"] = str(repo)
    from atelier.gateway.adapters import mcp_server as mcp

    handle = mcp._handle
    tools: dict[str, Any] = {}
    rid = 1
    for name, args in READ_ONLY_CALLS:
        tools[name] = _time_tool(handle, name, args, warmup=warmup, runs=runs, base_rid=rid)
        rid += 100
    if include_edit:
        edit_stats = _profile_edit(handle, repo, warmup=warmup, runs=runs, base_rid=rid)
        if edit_stats is not None:
            tools["edit"] = edit_stats
    return {
        "ts": time.time(),
        "git_sha": _git(repo, "rev-parse", "--short", "HEAD"),
        "git_branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "repo": str(repo),
        "tools": tools,
    }


def _iter_history(history: Path) -> list[dict[str, Any]]:
    if not history.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in history.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def load_last_run(history: Path, repo: str) -> dict[str, Any] | None:
    """Most recent prior run recorded for *repo* (or None)."""
    matches = [rec for rec in _iter_history(history) if rec.get("repo") == repo]
    return matches[-1] if matches else None


def append_history(history: Path, record: dict[str, Any]) -> None:
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _fmt_when(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def render_drift(current: dict[str, Any], prev: dict[str, Any] | None, threshold: float) -> tuple[str, bool]:
    """Render the per-tool drift table; return (text, any_regression)."""
    lines: list[str] = []
    lines.append(
        f"MCP tool latency  --  {current.get('git_branch', '?')}@{current.get('git_sha', '?')}  ({_fmt_when(current['ts'])})"
    )
    if prev is not None:
        lines.append(
            f"comparing vs previous run {prev.get('git_branch', '?')}@{prev.get('git_sha', '?')} ({_fmt_when(prev['ts'])})"
        )
    else:
        lines.append("no previous run for this repo -- baseline only")
    lines.append("")
    hdr = f"{'tool':10}{'cold_ms':>10}{'warm_ms':>10}{'prev_warm':>11}{'drift':>9}"
    lines.append(hdr)
    lines.append("-" * len(hdr))
    regressed = False
    prev_tools = (prev or {}).get("tools", {})
    for name, stats in current["tools"].items():
        warm = stats["warm_ms"]
        pstats = prev_tools.get(name)
        if pstats and pstats.get("warm_ms"):
            pw = pstats["warm_ms"]
            drift = (warm - pw) / pw * 100 if pw else 0.0
            flag = ""
            if drift > threshold:
                flag = "  ⚠ REGRESS"
                regressed = True
            elif drift < -threshold:
                flag = "  ✓ faster"
            lines.append(f"{name:10}{stats['cold_ms']:>10.0f}{warm:>10.1f}{pw:>11.1f}{drift:>+8.0f}%{flag}")
        else:
            lines.append(f"{name:10}{stats['cold_ms']:>10.0f}{warm:>10.1f}{'--':>11}{'new':>9}")
    lines.append("-" * len(hdr))
    runs = current["tools"][next(iter(current["tools"]))]["runs"] if current["tools"] else 0
    lines.append(f"drift threshold: ±{threshold:.0f}%  |  cold = first in-process call, warm = median of {runs} calls")
    return "\n".join(lines), regressed


def summarize_history(history: Path, repo: str, last: int = 10) -> str:
    """Render warm_ms per tool across the last *last* recorded runs for *repo*."""
    records = [rec for rec in _iter_history(history) if rec.get("repo") == repo][-last:]
    if not records:
        return f"no recorded runs for {repo} in {history}"
    tool_names: list[str] = []
    for rec in records:
        for name in rec.get("tools", {}):
            if name not in tool_names:
                tool_names.append(name)
    lines: list[str] = [f"warm_ms history ({len(records)} runs) -- {history}", ""]
    hdr = f"{'when':18}{'sha':10}" + "".join(f"{n:>10}" for n in tool_names)
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for rec in records:
        row = f"{_fmt_when(rec['ts']):18}{rec.get('git_sha', '?')!s:10}"
        for n in tool_names:
            v = rec.get("tools", {}).get(n, {}).get("warm_ms")
            row += f"{v:>10.1f}" if isinstance(v, (int, float)) else f"{'--':>10}"
        lines.append(row)
    return "\n".join(lines)
