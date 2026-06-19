"""Extract the `tools` array from /v1/messages requests in a mitmproxy flow.

Usage: uv run python benchmarks/codebench/_flowtools_probe.py <flow> [<flow> ...]
"""

import json
import sys
from collections import Counter

from mitmproxy import io as mio

NATIVE = {
    "Read",
    "Edit",
    "Write",
    "Grep",
    "Glob",
    "Bash",
    "WebFetch",
    "Task",
    "Agent",
    "ExitPlanMode",
    "AskUserQuestion",
    "NotebookEdit",
    "TodoWrite",
    "WebSearch",
}


def tool_sets_for(path: str) -> list[list[str]]:
    out: list[list[str]] = []
    with open(path, "rb") as fh:
        for flow in mio.FlowReader(fh).stream():
            req = getattr(flow, "request", None)
            if not req or "/v1/messages" not in req.path:
                continue
            try:
                body = json.loads(req.get_text(strict=False))
            except Exception:
                continue
            tools = body.get("tools") or []
            out.append([t.get("name") for t in tools if isinstance(t, dict)])
    return out


for path in sys.argv[1:]:
    print("=" * 70)
    print(path.rsplit("/", 1)[-1])
    try:
        sets = tool_sets_for(path)
    except Exception as exc:
        print("  parse error:", exc)
        continue
    if not sets:
        print("  no /v1/messages requests")
        continue
    counts = Counter(n for s in sets for n in s if n)
    mcp = sorted(n for n in counts if n.startswith("mcp__"))
    native = sorted(n for n in counts if n in NATIVE)
    other = sorted(n for n in counts if not n.startswith("mcp__") and n not in NATIVE)
    print(f"  /v1/messages requests: {len(sets)}")
    print(f"  req tool counts: first={len(sets[0])} min={min(len(s) for s in sets)} max={max(len(s) for s in sets)}")
    print(f"  unique tool names: {len(counts)}")
    print(f"  MCP tools ({len(mcp)}): {mcp}")
    print(f"  native tools ({len(native)}): {native}")
    print(f"  other tools ({len(other)}): {other}")
