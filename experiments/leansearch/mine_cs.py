"""Mine real code_search/grep calls + raw results from ALL benchmark flows.

Builds an offline corpus so the code_search lean-projection can be validated on
every query the agent actually issued across the 50 tasks -- no token spend.

Writes:
  experiments/leansearch/corpus.jsonl   one row per code_search call
  experiments/leansearch/gold.json      edited files per task from patches
"""

from __future__ import annotations

import glob
import json
import os
import re
import statistics

from mitmproxy import http
from mitmproxy import io as mio

ROOT = "/home/pankaj/Projects/leanchain/atelier/reports/benchmark/codebench"
OUT = "/home/pankaj/Projects/leanchain/atelier/experiments/leansearch"
os.makedirs(OUT, exist_ok=True)


def final_body(path):
    best = None
    n = -1
    try:
        with open(path, "rb") as f:
            for fl in mio.FlowReader(f).stream():
                if isinstance(fl, http.HTTPFlow) and fl.request and "/v1/messages" in fl.request.path:
                    try:
                        b = json.loads(fl.request.get_text())
                    except Exception:
                        continue
                    if len(b.get("messages", [])) > n:
                        n = len(b["messages"])
                        best = b
    except Exception:
        return None
    return best


def mine_flow(path):
    b = final_body(path)
    if not b:
        return
    id2 = {}
    for m in b["messages"]:
        if not isinstance(m.get("content"), list):
            continue
        for blk in m["content"]:
            t = blk.get("type")
            if t == "tool_use":
                nm = blk.get("name", "")
                if nm.endswith("code_search") or nm.endswith("__grep") or nm.endswith("__explore"):
                    id2[blk["id"]] = (nm.split("__")[-1], blk.get("input", {}))
            elif t == "tool_result":
                tid = blk.get("tool_use_id")
                if tid in id2:
                    tool, inp = id2[tid]
                    txt = blk.get("content")
                    if isinstance(txt, list):
                        txt = "".join(x.get("text", "") for x in txt if isinstance(x, dict))
                    txt = txt or ""
                    res = None
                    if tool == "code_search":
                        try:
                            res = json.loads(txt)
                        except Exception:
                            res = None
                    yield {"tool": tool, "input": inp, "result_chars": len(txt), "result": res}


def main():
    rows = []
    gold = {}
    flows = sorted(glob.glob(f"{ROOT}/**/*_atelier_rep*.flow", recursive=True))
    cs_by_task = {}
    for flow in flows:
        run = os.path.relpath(os.path.dirname(flow), ROOT)
        base = os.path.basename(flow)
        task = re.split(r"_atelier_rep", base)[0]
        rep = re.search(r"_rep(\d+)", base)
        rep = int(rep.group(1)) if rep else 0
        for call in mine_flow(flow):
            call.update({"run": run, "task": task, "rep": rep})
            rows.append(call)
            if call["tool"] == "code_search" and call["result"] is not None:
                cs_by_task.setdefault(task, set()).add(run)
    for patch in sorted(glob.glob(f"{ROOT}/**/*_atelier_rep*.patch", recursive=True)):
        task = re.split(r"_atelier_rep", os.path.basename(patch))[0]
        try:
            files = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", open(patch).read(), re.M)))
        except Exception:
            files = []
        if files:
            gold.setdefault(task, files)
    with open(f"{OUT}/corpus.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    json.dump(gold, open(f"{OUT}/gold.json", "w"), indent=0)
    cs = [r for r in rows if r["tool"] == "code_search" and r["result"] is not None]
    print(f"flows scanned       : {len(flows)}")
    print(
        f"total mined calls   : {len(rows)} (code_search={sum(1 for r in rows if r['tool'] == 'code_search')}, grep={sum(1 for r in rows if r['tool'] == 'grep')}, explore={sum(1 for r in rows if r['tool'] == 'explore')})"
    )
    print(f"code_search w/ parsed result : {len(cs)}")
    print(f"distinct tasks w/ code_search: {len(cs_by_task)}")
    print(f"gold files for tasks         : {len(gold)}")
    sizes = sorted(r["result_chars"] for r in cs)
    if sizes:
        print(
            f"code_search result_chars: min={sizes[0]} med={statistics.median(sizes):.0f} p90={sizes[min(len(sizes) - 1, int(len(sizes) * 0.9))]} max={sizes[-1]} mean={statistics.mean(sizes):.0f}"
        )


if __name__ == "__main__":
    main()
