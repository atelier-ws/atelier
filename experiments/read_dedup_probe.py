"""Why didn't read-dedup fire on the heavy re-reads?

For every atelier `read` tool_use: does it use files=[...] (batch -> delta path
disabled) or path= (single -> delta eligible)? And does any result already carry
the `[dedup]`/`[delta]` stub marker (i.e. dedup actually fired)?

PYTHONPATH=src uv run --project benchmarks python experiments/read_dedup_probe.py <run_dir>
"""

import json
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


def main(run_dir, arm):
    d = Path(run_dir)
    shape = Counter()  # which param the read used
    stub_hits = Counter()  # how many results carry a dedup/delta marker
    pend = {}
    nflows = 0
    for fp in sorted(d.glob(f"*_{arm}_rep*.flow")):
        nflows += 1
        for m in largest(fp):
            for b in m.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and str(b.get("name", "")).split("__")[-1].lower() == "read":
                    inp = b.get("input") or {}
                    if isinstance(inp, dict) and inp.get("files") is not None:
                        shape["files=[...] (delta DISABLED)"] += 1
                    elif isinstance(inp, dict) and (inp.get("path") or inp.get("file_path")):
                        shape["path= (delta eligible)"] += 1
                    else:
                        shape["other/symbol"] += 1
                    pend[b.get("id")] = True
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in pend:
                    pend.pop(b.get("tool_use_id"))
                    inner = b.get("content")
                    txt = (
                        " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                        if isinstance(inner, list)
                        else str(inner or "")
                    )
                    if "[dedup] =read" in txt:
                        stub_hits["[dedup] byte-identical stub"] += 1
                    elif "[delta]" in txt:
                        stub_hits["[delta] same-resource diff"] += 1
    print(f"[{arm}] flows={nflows}")
    print("  read call shapes:")
    for k, v in shape.most_common():
        print(f"    {v:>5}  {k}")
    print("  dedup/delta markers actually present in results:")
    if stub_hits:
        for k, v in stub_hits.most_common():
            print(f"    {v:>5}  {k}")
    else:
        print("        0  (dedup never fired on any read)")


if __name__ == "__main__":
    rd = sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep"
    main(rd, "atelier")
    print()
    main(rd, "baseline")
