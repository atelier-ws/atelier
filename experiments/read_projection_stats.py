"""How often did `read` spill to a projection (>200 LOC) vs return full source?

Scans every read tool_result in the atelier flows and classifies by the
'Projection: <view>' notice the read tool stamps (outline / minified / compact =
spilled because the file was large; none / exact / range = full source returned).

PYTHONPATH=src uv run --project benchmarks python experiments/read_projection_stats.py <run_dir>
"""

import json
import re
import sys
from collections import Counter
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


def read_results(msgs):
    pend, out = {}, []
    for m in msgs:
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                pend[b.get("id")] = str(b.get("name", "")).split("__")[-1].lower()
            elif b.get("type") == "tool_result" and pend.get(b.get("tool_use_id")) == "read":
                inner = b.get("content")
                txt = (
                    " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                    if isinstance(inner, list)
                    else str(inner or "")
                )
                out.append(txt)
    return out


PROJ = re.compile(r"Projection:\s*([a-z]+)", re.IGNORECASE)
SPILLED = {"outline", "minified", "compact", "summary"}


def main(run_dir):
    d = Path(run_dir)
    proj = Counter()
    total = spilled = full = 0
    sizes = []
    for fp in sorted(d.glob("*_atelier_rep*.flow"))[:60]:
        for txt in read_results(largest(fp)):
            total += 1
            sizes.append(len(txt))
            mm = PROJ.search(txt)
            view = mm.group(1).lower() if mm else "none/full"
            proj[view] += 1
            if view in SPILLED:
                spilled += 1
            else:
                full += 1
    print(f"atelier reads scanned: {total}")
    print(f"\nby projection view:")
    for v, n in proj.most_common():
        tag = "  <- spilled (large file)" if v in SPILLED else ""
        print(f"  {v:12} {n:>5}  ({n / max(total, 1) * 100:.0f}%){tag}")
    print(
        f"\nSPILLED to a projection (file too big for full source): {spilled}/{total} ({spilled / max(total, 1) * 100:.0f}%)"
    )
    print(
        f"returned full/range source:                              {full}/{total} ({full / max(total, 1) * 100:.0f}%)"
    )
    if sizes:
        sizes.sort()
        print(
            f"\nread result size: median {sizes[len(sizes) // 2]}c, max {max(sizes)}c, mean {sum(sizes) // len(sizes)}c"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
