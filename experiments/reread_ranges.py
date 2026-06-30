"""For files re-read >1x in atelier flows: were the re-reads the SAME view
(range/expand) or DIFFERENT ranges? Decides the fix:
  - same view byte-identical  -> stub_for should fire (bug = session_id/size)
  - same view changed content -> delta_for (needs files=[...] resource key fix)
  - different ranges          -> neither; needs overlap-aware notice

PYTHONPATH=src uv run --project benchmarks python experiments/reread_ranges.py <run_dir>
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader


def largest(fp):
    best = []
    try:
        flows = list(FlowReader(open(fp, "rb")).stream())
    except (OSError, ValueError):
        return best
    for fl in flows:
        if fl.request and "v1/messages" in fl.request.url:
            try:
                b = json.loads(fl.request.content.decode("utf-8", "ignore"))
            except (json.JSONDecodeError, ValueError):
                continue
            if len(b.get("messages") or []) > len(best):
                best = b["messages"]
    return best


def _views(inp):
    """yield (path, view_spec) for each file target in a read tool_use input."""
    out = []
    f = inp.get("files") if isinstance(inp, dict) else None
    if isinstance(f, list):
        for e in f:
            if isinstance(e, str):
                # split path from trailing :range/:expand/:head/:tail token
                parts = e.split(":")
                if len(parts) > 1 and any(
                    parts[-1] == "expand"
                    or parts[-1].startswith(("head=", "tail="))
                    or parts[-1].lstrip("L")[:1].isdigit()
                    for _ in [0]
                ):
                    out.append((":".join(parts[:-1]), parts[-1]))
                else:
                    out.append((e, "<whole>"))
            elif isinstance(e, dict):
                p = str(e.get("path") or "")
                v = str(e.get("range") or ("expand" if e.get("expand") else "<whole>"))
                out.append((p, v))
    elif isinstance(inp, dict) and inp.get("path"):
        out.append((str(inp["path"]), str(inp.get("range") or ("expand" if inp.get("expand") else "<whole>"))))
    return out


def main(run_dir):
    d = Path(run_dir)
    # (flow, path) -> Counter of view specs
    views = defaultdict(Counter)
    for fp in sorted(d.glob("*_atelier_rep*.flow")):
        for m in largest(fp):
            for b in m.get("content") or []:
                if (
                    isinstance(b, dict)
                    and b.get("type") == "tool_use"
                    and str(b.get("name", "")).split("__")[-1].lower() == "read"
                ):
                    for path, view in _views(b.get("input") or {}):
                        if path:
                            views[(fp.name, path)][view] += 1
    multi = {k: c for k, c in views.items() if sum(c.values()) > 1}
    same_view_repeat = 0  # a file where some single view was read >1x
    diff_view_only = 0  # re-read but every view distinct
    for c in multi.values():
        if any(n > 1 for n in c.values()):
            same_view_repeat += 1
        else:
            diff_view_only += 1
    print(f"files re-read >1x: {len(multi)}")
    print(f"  SAME view read >=2x (stub/delta-eligible): {same_view_repeat}")
    print(f"  only DISTINCT views (no current mechanism): {diff_view_only}")
    print("\n  examples of same-view repeats (file: view xN):")
    shown = 0
    for (flow, path), c in sorted(multi.items(), key=lambda kv: -max(kv[1].values())):
        rep = {v: n for v, n in c.items() if n > 1}
        if rep and shown < 10:
            print(f"    {path.split('/')[-1][:34]:34} {rep}  [{flow[:28]}]")
            shown += 1
    print("\n  examples of distinct-view spread (file: {view:count}):")
    shown = 0
    for (flow, path), c in sorted(multi.items(), key=lambda kv: -len(kv[1])):
        if len(c) > 2 and shown < 8:
            print(f"    {path.split('/')[-1][:30]:30} {dict(c)}  [{flow[:24]}]")
            shown += 1


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
