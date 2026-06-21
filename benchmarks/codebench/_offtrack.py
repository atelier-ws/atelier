"""Per-task per-rep behavioral breakdown: reconstruct tool trajectory from flow captures.

Reconstructs the ordered tool actions from each request's messages[-2] (the prior turn's
assistant action), which is compaction-proof. Surfaces WebSearch loops, edit churn, and
repeat-signature loops.
"""

import collections
import csv
import json
import os
import sys

from mitmproxy.io import FlowReader

FD = "reports/benchmark/codebench/swe20_run"


def actions(fp):
    try:
        with open(fp, "rb") as f:
            flows = [
                fl for fl in FlowReader(f).stream() if getattr(fl, "request", None) and "/messages" in fl.request.path
            ]
    except Exception:
        return 0, []
    seq = []
    n_tx = len(flows)
    for fl in flows:
        try:
            body = json.loads(fl.request.get_text() or "{}")
        except Exception:
            continue
        msgs = body.get("messages", [])
        for m in reversed(msgs):
            if m.get("role") == "assistant":
                c = m.get("content", [])
                if isinstance(c, list):
                    for b in c:
                        if b.get("type") == "tool_use":
                            name = b["name"].split("__")[-1]
                            inp = b.get("input", {})
                            key = ""
                            for k in ("command", "content_regex", "query", "path", "file_path", "pattern", "prompt"):
                                if k in inp:
                                    key = str(inp[k])[:80]
                                    break
                            seq.append((name, key))
                break
    return n_tx, seq


def loopmetric(seq):
    if not seq:
        return 0, 0, 0
    maxrun = run = 1
    for i in range(1, len(seq)):
        if seq[i] == seq[i - 1]:
            run += 1
            maxrun = max(maxrun, run)
        else:
            run = 1
    sigs = collections.Counter(seq)
    dup = sum(c - 1 for c in sigs.values() if c > 1)
    return maxrun, dup, len(sigs)


def summarize(arm):
    with open(f"{FD}/results.csv") as fh:
        rows = list(csv.DictReader(fh))
    meta = {
        (r.get("instance_id") or r.get("task"), r["arm"], r["rep"]): (
            float(r["cost_usd"] or 0),
            int(float(r["num_turns"] or 0)),
            float(r["score"] or 0),
        )
        for r in rows
    }
    tasks = sorted({r.get("instance_id") or r.get("task") for r in rows})
    print(f"\n===== ARM={arm} =====")
    print(
        f"{'task':28} rep {'turns':>5} {'acts':>5} {'WebS':>5} {'WebF':>5} "
        f"{'shell':>5} {'edit':>4} {'maxloop':>7} {'dup':>5} {'cost$':>6} {'sc':>4}"
    )
    agg_ws = collections.Counter()
    for t in tasks:
        for rep in ("1", "2", "3"):
            fp = f"{FD}/{t}_{arm}_rep{rep}.flow"
            if not os.path.exists(fp):
                print(f"{t[:28]:28} {rep}   (no flow)")
                continue
            _n_tx, seq = actions(fp)
            hist = collections.Counter(n for n, _ in seq)
            ws = hist.get("WebSearch", 0)
            wf = hist.get("web_fetch", 0) + hist.get("WebFetch", 0)
            sh = hist.get("shell", 0)
            ed = hist.get("edit", 0)
            mx, dup, _distinct = loopmetric(seq)
            cost, turns, sc = meta.get((t, arm, rep), (0, 0, 0))
            agg_ws[t] += ws
            flag = ""
            if ws >= 20:
                flag = " <<WEBSEARCH"
            elif mx >= 8:
                flag = " <<LOOP"
            print(
                f"{t[:28]:28} {rep}  {turns:5} {len(seq):5} {ws:5} {wf:5} "
                f"{sh:5} {ed:4} {mx:7} {dup:5} {cost:6.2f} {sc:4.1f}{flag}"
            )
    tot = sum(agg_ws.values())
    print(f"\nTotal WebSearch this arm: {tot}  by task: {dict((k, v) for k, v in agg_ws.most_common() if v)}")


if __name__ == "__main__":
    summarize(sys.argv[1] if len(sys.argv) > 1 else "atelier")
