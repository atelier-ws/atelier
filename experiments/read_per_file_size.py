"""Median read size PER FILE (sum all reads of the same file within a run)
vs PER CALL. Tells whether the read tool bloats context via re-reads /
overlapping ranges of the same file -> i.e. whether read needs trimming.

PYTHONPATH=src uv run --project benchmarks python experiments/read_per_file_size.py <run_dir>
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

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


def _norm(p):
    p = str(p or "").split("::")[0]
    p = re.sub(r":(L\d+(-L?\d+)?|expand|head=\d+|tail=\d+|\d+)$", "", p)
    return p.strip()


def _paths_from_input(inp):
    """Return list of normalized file paths a read tool_use targeted."""
    if not isinstance(inp, dict):
        return []
    out = []
    f = inp.get("files")
    if isinstance(f, list):
        for e in f:
            if isinstance(e, str):
                out.append(_norm(e))
            elif isinstance(e, dict):
                out.append(_norm(e.get("path", "")))
    for k in ("file_path", "path", "target_file"):
        if inp.get(k):
            out.append(_norm(inp[k]))
    return [p for p in out if p]


def reads(msgs):
    """yield (path, result_size) for each read; multi-file calls split evenly."""
    pend = {}
    for m in msgs:
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and str(b.get("name", "")).split("__")[-1].lower() == "read":
                pend[b.get("id")] = _paths_from_input(b.get("input"))
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in pend:
                paths = pend.pop(b.get("tool_use_id"))
                if not paths:
                    continue
                inner = b.get("content")
                txt = (
                    " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                    if isinstance(inner, list)
                    else str(inner or "")
                )
                share = len(txt) / len(paths)
                for p in paths:
                    yield p, share


def main(run_dir, arm):
    d = Path(run_dir)
    per_call = []
    per_file = defaultdict(float)
    calls_per_file = defaultdict(int)
    glob = f"*_{arm}_rep*.flow"
    nflows = 0
    for fp in sorted(d.glob(glob)):
        nflows += 1
        for path, size in reads(largest(fp)):
            key = (fp.name, path)
            per_call.append(size)
            per_file[key] += size
            calls_per_file[key] += 1
    if not per_call:
        print(f"[{arm}] no reads found")
        return
    file_totals = sorted(per_file.values())
    reread = list(calls_per_file.values())
    multi = sum(1 for c in reread if c > 1)
    print(f"[{arm}]  flows={nflows}  read calls={len(per_call)}  distinct (flow,file)={len(per_file)}")
    print(
        f"  PER CALL : median {int(median(per_call)):>6}c  mean {int(sum(per_call) / len(per_call)):>6}c  max {int(max(per_call))}c"
    )
    print(
        f"  PER FILE : median {int(median(file_totals)):>6}c  mean {int(sum(file_totals) / len(file_totals)):>6}c  max {int(max(file_totals))}c"
    )
    print(
        f"  re-reads : {len(per_call) / len(per_file):.2f} calls/file ; {multi}/{len(per_file)} files read >1x ({multi / len(per_file) * 100:.0f}%)"
    )
    top = sorted(per_file.items(), key=lambda kv: -kv[1])[:8]
    print("  heaviest files (total bytes / #calls / file / flow):")
    for (flow, path), tot in top:
        print(f"    {int(tot):>7}c  x{calls_per_file[(flow, path)]:<2} {path.split('/')[-1][:40]:40} [{flow[:32]}]")


if __name__ == "__main__":
    rd = sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep"
    main(rd, "atelier")
    print()
    main(rd, "baseline")
