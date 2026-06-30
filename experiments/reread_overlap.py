"""True re-read waste = lines emitted that were ALREADY emitted earlier in the
same session (overlapping range re-reads). Per (flow,file): sum of per-read
line counts vs the union of covered lines; the gap is redundant lines re-paid
as cache_read every later turn.

PYTHONPATH=src uv run --project benchmarks python experiments/reread_overlap.py <run_dir>
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader

_R = re.compile(r"^L?(\d+)-L?(\d+)$", re.IGNORECASE)


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


def _ranges(inp):
    """yield (path, lo, hi) for each CLOSED line-range read target."""
    f = inp.get("files") if isinstance(inp, dict) else None
    items = []
    if isinstance(f, list):
        for e in f:
            if isinstance(e, str):
                parts = e.split(":")
                if len(parts) > 1 and _R.match(parts[-1]):
                    items.append((":".join(parts[:-1]), parts[-1]))
            elif isinstance(e, dict) and e.get("range"):
                items.append((str(e.get("path") or ""), str(e["range"])))
    for path, spec in items:
        m = _R.match(spec)
        if path and m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if hi >= lo:
                yield path, lo, hi


def _union_len(intervals):
    merged = 0
    cur_lo = cur_hi = None
    for lo, hi in sorted(intervals):
        if cur_hi is None or lo > cur_hi + 1:
            if cur_hi is not None:
                merged += cur_hi - cur_lo + 1
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    if cur_hi is not None:
        merged += cur_hi - cur_lo + 1
    return merged


def main(run_dir):
    d = Path(run_dir)
    per_file = defaultdict(list)  # (flow,path) -> [(lo,hi)]
    for fp in sorted(d.glob("*_atelier_rep*.flow")):
        for m in largest(fp):
            for b in m.get("content") or []:
                if (
                    isinstance(b, dict)
                    and b.get("type") == "tool_use"
                    and str(b.get("name", "")).split("__")[-1].lower() == "read"
                ):
                    for path, lo, hi in _ranges(b.get("input") or {}):
                        per_file[(fp.name, path)].append((lo, hi))
    total_lines = 0
    union_lines = 0
    redundant_by_file = []
    for key, ivs in per_file.items():
        emitted = sum(hi - lo + 1 for lo, hi in ivs)
        union = _union_len(ivs)
        total_lines += emitted
        union_lines += union
        if emitted > union:
            redundant_by_file.append((emitted - union, len(ivs), key))
    redundant = total_lines - union_lines
    print(f"closed-range reads aggregated over {len(per_file)} (flow,file) groups")
    print(f"  total lines emitted (sum of ranges): {total_lines}")
    print(f"  distinct lines covered (union)      : {union_lines}")
    print(
        f"  REDUNDANT (re-emitted) lines        : {redundant}  ({redundant / max(total_lines, 1) * 100:.1f}% of emitted)"
    )
    print(f"  ~chars (35 b/line): {redundant * 35} ; ~tokens (4 c/tok): {redundant * 35 // 4}")
    print("\n  worst files by redundant lines (redundant / #reads / file):")
    for red, n, (flow, path) in sorted(redundant_by_file, reverse=True)[:10]:
        print(f"    {red:>5} lines  x{n:<2} {path.split('/')[-1][:34]:34} [{flow[:26]}]")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
