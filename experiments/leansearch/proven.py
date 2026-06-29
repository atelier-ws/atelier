"""Reverse-engineer the proven (cheap, sub-baseline) build's workflow from flows.

For each cheap5 task in exp_d_proven_cheap5 rep1: tools OFFERED, then the exact
tool-call sequence (name + input summary + result size). Reveals what the proven
~4-turn workflow actually did so we can replicate it.
"""

import json

from mitmproxy import http
from mitmproxy import io as mio

ROOT = "/home/pankaj/Projects/leanchain/atelier/reports/benchmark/codebench"
CHEAP5 = [
    "django__django-12155",
    "django__django-11333",
    "pallets__flask-5014",
    "django__django-14376",
    "psf__requests-2931",
]


def bodies(p):
    first = best = None
    n = -1
    with open(p, "rb") as f:
        for fl in mio.FlowReader(f).stream():
            if isinstance(fl, http.HTTPFlow) and fl.request and "/v1/messages" in fl.request.path:
                try:
                    b = json.loads(fl.request.get_text())
                except Exception:
                    continue
                if first is None:
                    first = b
                if len(b.get("messages", [])) > n:
                    n = len(b["messages"])
                    best = b
    return first, best


def summ(inp):
    if not isinstance(inp, dict):
        return str(inp)[:60]
    for k in ("query", "pattern", "command", "file_path", "symbol"):
        if k in inp:
            v = inp[k]
            return f"{k}={json.dumps(v)[:55]}"
    if "files" in inp:
        return f"files={inp['files']}"
    if "edits" in inp:
        return f"edits[{len(inp['edits']) if isinstance(inp['edits'], list) else 1}]"
    return json.dumps(inp)[:60]


for task in CHEAP5:
    p = f"{ROOT}/exp_d_proven_cheap5/{task}_atelier_rep1.flow"
    first, best = bodies(p)
    tools = sorted(t.get("name", "") for t in (first.get("tools") or []))
    print("=" * 78)
    print(f"{task}   tools_offered({len(tools)}): {tools}")
    id2 = {}
    for m in best["messages"]:
        if not isinstance(m.get("content"), list):
            continue
        for blk in m["content"]:
            if blk.get("type") == "tool_use":
                nm = blk.get("name", "").split("__")[-1]
                id2[blk["id"]] = nm
                print(f"   {nm:12} {summ(blk.get('input', {}))}")
            elif blk.get("type") == "tool_result":
                nm = id2.get(blk.get("tool_use_id"))
                if nm:
                    t = blk.get("content")
                    if isinstance(t, list):
                        t = "".join(x.get("text", "") for x in t if isinstance(x, dict))
                    print(f"   {'':12}   -> {len(t or '')} chars")
