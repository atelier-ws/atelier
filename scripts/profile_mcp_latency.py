"""Wall-clock + cProfile harness for MCP tool dispatch latency.

Run:  uv run python scripts/profile_mcp_latency.py
"""

from __future__ import annotations

import cProfile
import io
import os
import pstats
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "src"))

os.environ.setdefault("CLAUDE_WORKSPACE_ROOT", str(Path.cwd()))
os.environ.setdefault("ATELIER_BENCH_MODE", "1")
os.environ.setdefault("ATELIER_CONTEXT_DEDUP", "0")
os.environ.setdefault("ATELIER_TOOL_OUTPUT_SPILL", "0")

from benchmarks.mcp_tools._env import configure_benchmark_runtime

_tmp = Path(tempfile.mkdtemp())
configure_benchmark_runtime(_tmp, workspace_root=Path.cwd())

from atelier.gateway.adapters.mcp_server import _handle  # noqa: E402


def _req(name: str, args: dict) -> dict:
    return {"id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}


def _measure(label: str, req: dict, n: int = 9) -> dict:
    times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            _handle(req)
        except Exception:  # noqa: BLE001
            pass
        times.append((time.perf_counter() - t0) * 1000)
    times_s = sorted(times)
    return {
        "tool": label,
        "mean": round(statistics.mean(times), 2),
        "p50": round(statistics.median(times), 2),
        "p95": round(times_s[max(0, int(0.95 * len(times)) - 1)], 2),
        "p99": round(times_s[max(0, int(0.99 * len(times)) - 1)], 2),
        "min": round(times_s[0], 2),
        "max": round(times_s[-1], 2),
    }


WORKLOADS: list[tuple[str, str, dict]] = [
    ("orient", "orient", {}),
    (
        "grep/with_count",
        "grep",
        {"content_regex": "import os", "path": "src/atelier", "mode": "counts"},
    ),
    (
        "grep/file_paths",
        "grep",
        {"content_regex": "def _handle", "path": "src/atelier/gateway/adapters", "mode": "paths"},
    ),
    ("grep/content", "grep", {"content_regex": "_handle", "path": "src/atelier/gateway/adapters/mcp_server.py"}),
    ("bash/echo", "bash", {"command": "echo hello"}),
    ("bash/ls", "bash", {"command": "ls src/atelier/gateway/adapters/"}),
    ("read/outline", "read", {"path": "src/atelier/gateway/adapters/mcp_server.py"}),
    ("read/range", "read", {"path": "src/atelier/gateway/adapters/mcp_server.py", "range": "1-200"}),
    ("read/small", "read", {"path": "src/atelier/gateway/adapters/__init__.py"}),
    ("scan/shallow", "scan", {"path": "src/atelier/gateway/adapters"}),
    ("relations/usages", "relations", {"symbol": "_handle", "kind": "usages"}),
    ("search/kw", "search", {"query": "mcp tool handler dispatch"}),
]

print(f"\n{'Tool':<26} {'mean':>8} {'p50':>8} {'p95':>8} {'p99':>8} {'min':>8} {'max':>8}  (ms, n=9)")
print("-" * 88)

results: list[dict] = []
for label, name, args in WORKLOADS:
    r = _measure(label, _req(name, args))
    results.append(r)
    print(
        f"{r['tool']:<26} {r['mean']:>8.1f} {r['p50']:>8.1f} {r['p95']:>8.1f} {r['p99']:>8.1f} {r['min']:>8.1f} {r['max']:>8.1f}"
    )

print("\n=== RANKED BY MEAN ===")
for r in sorted(results, key=lambda x: x["mean"], reverse=True):
    bar = "█" * max(1, int(r["mean"] / 10))
    print(f"  {r['tool']:<26}  {r['mean']:>7.1f} ms  {bar}")

# cProfile on the dispatch-overhead canaries to confirm shutil.which is gone
CANARIES = {"orient", "grep/with_count"}
for label, name, args in WORKLOADS:
    if label not in CANARIES:
        continue
    req = _req(name, args)
    print(f"\n{'=' * 60}\ncProfile (cumtime, top-20): {label}\n{'=' * 60}")
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(15):
        try:
            _handle(req)
        except Exception:  # noqa: BLE001
            pass
    pr.disable()
    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(20)
    print(buf.getvalue())
