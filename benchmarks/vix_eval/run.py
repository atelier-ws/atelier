"""Head-to-head runner: vanilla Claude Code (baseline) vs Atelier-enabled (candidate).

For each task and arm we:
  1. prepare an isolated workspace (empty / git checkout / bundled copy),
  2. start mitmdump capturing the model traffic to a .flow file,
  3. run ``claude -p <prompt>`` headless, pinned to one model, through the proxy,
  4. record cost (real, from CLI JSON), latency, and token usage.

Baseline uses an isolated CLAUDE_CONFIG_DIR with plugins/hooks/MCP stripped
(but real subscription credentials copied in) so it is contamination-free.
The Atelier arm adds the atelier stdio MCP server + a tool-discipline CLAUDE.md.

Usage:
    uv run python -m benchmarks.vix_eval.run --tasks task1 --reps 1 --model sonnet
    uv run python -m benchmarks.vix_eval.run --report results/<run_dir>
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from benchmarks.vix_eval.tasks import BY_ID, TASKS, Task

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "benchmarks" / "vix_eval" / "results"
CA_CERT = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"

ATELIER_MCP = {
    "mcpServers": {
        "atelier": {
            "type": "stdio",
            "command": "atelier-mcp",
            "args": ["--host", "claude"],
            "env": {},
        }
    }
}
EMPTY_MCP: dict[str, dict[str, object]] = {"mcpServers": {}}

ATELIER_CLAUDE_MD = """# Tool discipline (benchmark candidate)

Prefer Atelier MCP tools over native ones to minimise context/token use:
- Read files with `mcp__atelier__read` (outline mode for large files), not full reads.
- Search with `mcp__atelier__grep` / `mcp__atelier__search` instead of dumping files.
- For symbols use `mcp__atelier__node` / `mcp__atelier__symbols` (one symbol, not whole file).
- Trace callers/callees with `mcp__atelier__callers` / `mcp__atelier__callees`.
Keep reads narrow; do not re-read unchanged files.
"""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return int(port)


def _wait_port(port: int, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with (
            contextlib.suppress(OSError),
            socket.create_connection(("127.0.0.1", port), timeout=0.5),
        ):
            return True
        time.sleep(0.2)
    return False


def _make_baseline_config() -> Path:
    """Isolated CLAUDE_CONFIG_DIR: real auth, no plugins/hooks/MCP."""
    cfg = Path(_mktemp("cfg-"))
    src = Path.home() / ".claude.json"
    data = json.loads(src.read_text())
    for k in ("enabledPlugins", "hooks", "mcpServers"):
        data.pop(k, None)
    for proj in data.get("projects", {}).values():
        if isinstance(proj, dict):
            for k in ("mcpServers", "enabledPlugins", "hooks"):
                proj.pop(k, None)
    (cfg / ".claude.json").write_text(json.dumps(data))
    creds = Path.home() / ".claude" / ".credentials.json"
    if creds.exists():
        shutil.copy(creds, cfg / ".credentials.json")
    return cfg


def _mktemp(prefix: str) -> str:
    import tempfile

    return tempfile.mkdtemp(prefix=f"vixeval-{prefix}")


def prepare_workspace(task: Task) -> Path:
    ws = Path(_mktemp(f"ws-{task.id}-"))
    kind = task.source[0]
    if kind == "empty":
        pass
    elif kind == "workspace":
        src = task.workspace_src()
        if not src or not src.exists():
            raise FileNotFoundError(f"bundled workspace missing for {task.id}: {src}")
        for item in src.iterdir():
            dst = ws / item.name
            if item.is_dir():
                shutil.copytree(item, dst)
            else:
                shutil.copy(item, dst)
    elif kind == "repo":
        if len(task.source) < 3:
            raise ValueError(f"repo source missing url/commit for {task.id}: {task.source}")
        url, commit = task.source[1], task.source[2]
        subprocess.run(["git", "clone", "--quiet", url, str(ws)], check=True, timeout=900)
        if commit:
            subprocess.run(
                ["git", "-C", str(ws), "checkout", "--quiet", commit], check=True, timeout=120
            )
    else:
        raise ValueError(f"unknown source kind {kind}")
    return ws


@dataclass
class ArmResult:
    task: str
    arm: str
    rep: int
    ok: bool
    cost_usd: float
    duration_ms: int
    duration_api_ms: int
    num_turns: int
    input_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    output_tokens: int
    models: list[str]
    is_error: bool
    result_excerpt: str
    flow_path: str


def _parse_result(stdout: str, flow_path: Path, task: str, arm: str, rep: int) -> ArmResult:
    try:
        d = json.loads(stdout)
    except json.JSONDecodeError:
        return ArmResult(
            task, arm, rep, False, 0.0, 0, 0, 0, 0, 0, 0, 0, [], True, stdout[:200], str(flow_path)
        )
    u = d.get("usage", {}) or {}
    return ArmResult(
        task=task,
        arm=arm,
        rep=rep,
        ok=not d.get("is_error", False),
        cost_usd=float(d.get("total_cost_usd", 0.0) or 0.0),
        duration_ms=int(d.get("duration_ms", 0) or 0),
        duration_api_ms=int(d.get("duration_api_ms", 0) or 0),
        num_turns=int(d.get("num_turns", 0) or 0),
        input_tokens=int(u.get("input_tokens", 0) or 0),
        cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
        models=list((d.get("modelUsage", {}) or {}).keys()),
        is_error=bool(d.get("is_error", False)),
        result_excerpt=str(d.get("result", ""))[:200],
        flow_path=str(flow_path),
    )


def run_arm(task: Task, arm: str, rep: int, model: str, out_dir: Path, timeout: int) -> ArmResult:
    assert arm in ("baseline", "atelier")
    ws = prepare_workspace(task)
    flow_path = out_dir / f"{task.id}_{arm}_rep{rep}.flow"
    port = _free_port()
    mitm = subprocess.Popen(
        ["uv", "run", "mitmdump", "-w", str(flow_path), "--listen-port", str(port), "-q"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_port(port):
            raise RuntimeError("mitmdump did not start")
        env = dict(os.environ)
        env["HTTPS_PROXY"] = f"http://127.0.0.1:{port}"
        env["HTTP_PROXY"] = f"http://127.0.0.1:{port}"
        env["NODE_EXTRA_CA_CERTS"] = str(CA_CERT)
        cmd = [
            "claude",
            "-p",
            task.prompt(),
            "--model",
            model,
            "--output-format",
            "json",
            "--permission-mode",
            "bypassPermissions",
            "--strict-mcp-config",
        ]
        if arm == "atelier":
            cmd += ["--mcp-config", json.dumps(ATELIER_MCP)]
            (ws / "CLAUDE.md").write_text(ATELIER_CLAUDE_MD)
            env["CLAUDE_CONFIG_DIR"] = str(
                _make_baseline_config()
            )  # clean base + atelier mcp via flag
        else:
            cmd += ["--mcp-config", json.dumps(EMPTY_MCP)]
            env["CLAUDE_CONFIG_DIR"] = str(_make_baseline_config())
        proc = subprocess.run(
            cmd,
            cwd=str(ws),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        res = _parse_result(proc.stdout, flow_path, task.id, arm, rep)
        if not res.ok and not proc.stdout.strip():
            res.result_excerpt = (proc.stderr or "")[:200]
        return res
    finally:
        mitm.terminate()
        with contextlib.suppress(Exception):
            mitm.wait(timeout=5)
        shutil.rmtree(ws, ignore_errors=True)


def _agg(results: list[ArmResult], arm: str) -> dict[str, float | int]:
    rs = [r for r in results if r.arm == arm]
    return {
        "runs": len(rs),
        "ok": sum(1 for r in rs if r.ok),
        "cost_usd": round(sum(r.cost_usd for r in rs), 4),
        "duration_ms": sum(r.duration_ms for r in rs),
        "output_tokens": sum(r.output_tokens for r in rs),
        "input_tokens": sum(r.input_tokens for r in rs),
    }


def report(results: list[ArmResult]) -> str:
    base, atel = _agg(results, "baseline"), _agg(results, "atelier")
    lines = [
        "",
        "=== vix-eval head-to-head ===",
        f"{'metric':<16}{'baseline':>14}{'atelier':>14}{'delta':>12}",
    ]

    def row(label: str, b: float, a: float, pct: bool = True) -> str:
        d = (a - b) / b * 100 if b else 0.0
        bs = f"{b:,.4f}" if isinstance(b, float) else f"{b:,}"
        as_ = f"{a:,.4f}" if isinstance(a, float) else f"{a:,}"
        return (
            f"{label:<16}{bs:>14}{as_:>14}{d:>+11.1f}%" if pct else f"{label:<16}{bs:>14}{as_:>14}"
        )

    lines.append(row("cost_usd", base["cost_usd"], atel["cost_usd"]))
    lines.append(row("duration_ms", float(base["duration_ms"]), float(atel["duration_ms"])))
    lines.append(row("input_tokens", float(base["input_tokens"]), float(atel["input_tokens"])))
    lines.append(row("output_tokens", float(base["output_tokens"]), float(atel["output_tokens"])))
    cost_save = (1 - atel["cost_usd"] / base["cost_usd"]) * 100 if base["cost_usd"] else 0.0
    time_save = (
        (1 - atel["duration_ms"] / base["duration_ms"]) * 100 if base["duration_ms"] else 0.0
    )
    lines += [
        "",
        f"Cost saving : {cost_save:+.1f}%  (Vix target ~47-50%)",
        f"Time saving : {time_save:+.1f}%  (Vix target ~40%)",
        f"Runs ok     : baseline {base['ok']}/{base['runs']}  atelier {atel['ok']}/{atel['runs']}",
    ]
    return "\n".join(lines)


def _detail_rows(results: list[ArmResult]) -> list[dict[str, object]]:
    return [asdict(result) for result in results]


def _summary_rows(results: list[ArmResult]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for arm in ("baseline", "atelier"):
        arm_results = [result for result in results if result.arm == arm]
        rows.append(
            {
                "arm": arm,
                "runs": len(arm_results),
                "ok_runs": sum(1 for result in arm_results if result.ok),
                "failed_runs": sum(1 for result in arm_results if not result.ok),
                "cost_usd": round(sum(result.cost_usd for result in arm_results), 4),
                "duration_ms": sum(result.duration_ms for result in arm_results),
                "duration_api_ms": sum(result.duration_api_ms for result in arm_results),
                "input_tokens": sum(result.input_tokens for result in arm_results),
                "cache_read_tokens": sum(result.cache_read_tokens for result in arm_results),
                "cache_creation_tokens": sum(
                    result.cache_creation_tokens for result in arm_results
                ),
                "output_tokens": sum(result.output_tokens for result in arm_results),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_csv_artifacts(run_dir: Path, results: list[ArmResult]) -> None:
    _write_csv(
        run_dir / "results.csv",
        _detail_rows(results),
        [
            "task",
            "arm",
            "rep",
            "ok",
            "cost_usd",
            "duration_ms",
            "duration_api_ms",
            "num_turns",
            "input_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "output_tokens",
            "models",
            "is_error",
            "result_excerpt",
            "flow_path",
        ],
    )
    _write_csv(
        run_dir / "summary.csv",
        _summary_rows(results),
        [
            "arm",
            "runs",
            "ok_runs",
            "failed_runs",
            "cost_usd",
            "duration_ms",
            "duration_api_ms",
            "input_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "output_tokens",
        ],
    )


def main() -> int:
    p = argparse.ArgumentParser(description="vix-eval head-to-head runner")
    p.add_argument("--tasks", nargs="*", default=["all"], help="task ids or 'all'")
    p.add_argument("--arms", nargs="*", default=["baseline", "atelier"])
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--model", default="sonnet")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--out", type=Path, default=None, help="directory for run artifacts")
    p.add_argument("--report", default=None, help="path to a results dir to re-report")
    args = p.parse_args()

    if args.report:
        rdir = Path(args.report)
        report_results = [
            ArmResult(**json.loads(line))
            for line in (rdir / "results.jsonl").read_text().splitlines()
            if line.strip()
        ]
        write_csv_artifacts(rdir, report_results)
        print(report(report_results))
        return 0

    task_ids = [t.id for t in TASKS] if args.tasks == ["all"] else args.tasks
    run_dir = args.out if args.out is not None else RESULTS_ROOT / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    results: list[ArmResult] = []
    jl = (run_dir / "results.jsonl").open("w")
    for tid in task_ids:
        task = BY_ID[tid]
        for rep in range(args.reps):
            for arm in args.arms:
                print(f"[run] {tid} {arm} rep{rep} (model={args.model}) ...", flush=True)
                t0 = time.time()
                try:
                    res = run_arm(task, arm, rep, args.model, run_dir, args.timeout)
                except Exception as exc:
                    res = ArmResult(
                        tid,
                        arm,
                        rep,
                        False,
                        0.0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        [],
                        True,
                        f"harness error: {exc}"[:200],
                        "",
                    )
                wall = time.time() - t0
                print(
                    f"     -> ok={res.ok} cost=${res.cost_usd:.4f} dur={res.duration_ms}ms wall={wall:.0f}s turns={res.num_turns} {res.result_excerpt[:60]!r}",
                    flush=True,
                )
                results.append(res)
                jl.write(json.dumps(asdict(res)) + "\n")
                jl.flush()
    jl.close()
    write_csv_artifacts(run_dir, results)
    rep_txt = report(results)
    (run_dir / "report.txt").write_text(rep_txt)
    print(rep_txt)
    print(f"\nResults: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
