"""Show the code_search->read interplay: does the agent re-read files code_search
already returned (trust gap) or new files (coverage gap)? Plus requests-2931 fail.
"""

import json

from mitmproxy import http
from mitmproxy import io as mio

ROOT = "/home/pankaj/Projects/leanchain/atelier/reports/benchmark/codebench/swe50_leansearch_run1"


def final_body(p):
    best = None
    n = -1
    with open(p, "rb") as f:
        for fl in mio.FlowReader(f).stream():
            if isinstance(fl, http.HTTPFlow) and fl.request and "/v1/messages" in fl.request.path:
                try:
                    b = json.loads(fl.request.get_text())
                except Exception:
                    continue
                if len(b.get("messages", [])) > n:
                    n = len(b["messages"])
                    best = b
    return best


def seq(task):
    b = final_body(f"{ROOT}/{task}_atelier_rep1.flow")
    id2 = {}
    print(f"===== {task} =====")
    cs_files = set()
    for m in b["messages"]:
        if not isinstance(m.get("content"), list):
            continue
        for blk in m["content"]:
            if blk.get("type") == "tool_use":
                nm = blk.get("name", "").split("__")[-1]
                inp = blk.get("input", {})
                if nm == "code_search":
                    print(f"  code_search  q={json.dumps(inp.get('query', ''))[:60]} paths={inp.get('paths')}")
                    id2[blk["id"]] = "cs"
                elif nm == "read":
                    fp = inp.get("file_path") or inp.get("path") or inp.get("target") or json.dumps(inp)[:60]
                    seen = (
                        " [code_search ALREADY returned this file]"
                        if any(str(fp).endswith(c) or c in str(fp) for c in cs_files)
                        else " [NEW file]"
                    )
                    print(f"  read         {fp}{seen}")
                elif nm == "edit":
                    fp = inp.get("file_path") or inp.get("path") or "?"
                    print(f"  EDIT         {fp}")
                elif nm == "bash":
                    print(f"  bash         {json.dumps(inp.get('command', inp))[:70]}")
            elif blk.get("type") == "tool_result" and id2.get(blk.get("tool_use_id")) == "cs":
                t = blk.get("content")
                if isinstance(t, list):
                    t = "".join(x.get("text", "") for x in t if isinstance(x, dict))
                try:
                    res = json.loads(t)
                    for fobj in res.get("files", []):
                        cs_files.add(fobj.get("path"))
                    for fp in res.get("candidate_files", []):
                        cs_files.add(fp)
                except Exception:
                    pass


for task in ["django__django-11333", "django__django-14376", "psf__requests-2931"]:
    seq(task)
    print()
