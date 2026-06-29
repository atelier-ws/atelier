"""Per-tool call breakdown for cheap5 across proven / bloated / lean runs.

Shows whether turn count is driven by code_search count, bash count, or reads --
so we know if the remaining turn bloat is a search problem or a workflow problem.
"""

import collections
import glob
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
RUNS = {"proven": "exp_d_proven_cheap5", "bloated": "swe50_newatelier_run1", "lean": "swe50_leansearch_run1"}


def final_body(path):
    best = None
    n = -1
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
    return best


def tool_counts(path):
    b = final_body(path)
    if not b:
        return None
    c = collections.Counter()
    for m in b["messages"]:
        if not isinstance(m.get("content"), list):
            continue
        for blk in m["content"]:
            if blk.get("type") == "tool_use":
                c[blk.get("name", "?").split("__")[-1]] += 1
    return c


def main():
    tools = ["code_search", "grep", "read", "bash", "edit", "explore"]
    for task in CHEAP5:
        print("=" * 78)
        print(task)
        print(f"  {'run':8} {'calls':>5} " + " ".join(f"{t:>11}" for t in tools))
        for label, run in RUNS.items():
            fs = sorted(glob.glob(f"{ROOT}/{run}/{task}_atelier_rep1.flow"))
            if not fs:
                print(f"  {label:8}  (no flow)")
                continue
            c = tool_counts(fs[0])
            if c is None:
                print(f"  {label:8}  (parse fail)")
                continue
            print(f"  {label:8} {sum(c.values()):5} " + " ".join(f"{c.get(t, 0):>11}" for t in tools))


if __name__ == "__main__":
    main()
