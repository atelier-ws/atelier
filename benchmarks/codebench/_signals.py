"""Generalizable behavioral signals per task/rep, vs cost/score deltas.

Reconstructs each atelier rep's tool trajectory (compaction-proof) and computes
repo/language-agnostic signals, then buckets tasks by a data-driven split.
"""

import collections
import csv
import json
import os
import re
import sys

from mitmproxy.io import FlowReader

FD = sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe20_run2"

GIT_ARCH = re.compile(r"\bgit\s+(log|show|blame)\b")
GIT_OK = re.compile(r"\bgit\s+(diff|status|add|stash|apply|rev-parse|config)\b")
CHANGELOG = re.compile(r"(?i)(changelog|release|whatsnew|whats_new|/news|history|docs/releases)")
TEST = re.compile(r"(?i)\b(pytest|runtests|unittest|nosetests|tox)\b")
TEST_TARGETED = re.compile(r"::|test_[\w]+\.py\b")


def trajectory(fp):
    try:
        with open(fp, "rb") as f:
            flows = [
                fl for fl in FlowReader(f).stream() if getattr(fl, "request", None) and "/messages" in fl.request.path
            ]
    except Exception:
        return 0, [], 0
    seq, prose = [], 0
    for fl in flows:
        try:
            body = json.loads(fl.request.get_text() or "{}")
        except Exception:
            continue
        for m in reversed(body.get("messages", [])):
            if m.get("role") == "assistant":
                c = m.get("content", [])
                tus = (
                    [b for b in c if isinstance(b, dict) and b.get("type") == "tool_use"] if isinstance(c, list) else []
                )
                if not tus:
                    prose += 1
                for b in tus:
                    seq.append((b["name"].split("__")[-1], b.get("input", {})))
                break
    return len(flows), seq, prose


def signals(fp):
    _n_tx, seq, prose = trajectory(fp)
    cmds = [i.get("command") for _, i in seq if isinstance(i, dict) and i.get("command")]
    tools = collections.Counter(n for n, _ in seq)
    web = tools.get("WebSearch", 0)
    git_arch = sum(1 for c in cmds if GIT_ARCH.search(c) and not GIT_OK.search(c))
    changelog = sum(
        1 for n, i in seq if n.lower() == "read" and CHANGELOG.search(str(i.get("path", "") or i.get("file_path", "")))
    )
    subagent = tools.get("Agent", 0) + tools.get("Task", 0)
    test_cmds = [c for c in cmds if TEST.search(c)]
    broad_test = sum(1 for c in test_cmds if not TEST_TARGETED.search(c))
    edits = tools.get("edit", 0) + tools.get("Edit", 0) + tools.get("Write", 0)
    sig = [
        (
            n,
            (
                (
                    i.get("command")
                    or i.get("content_regex")
                    or i.get("path")
                    or i.get("file_path")
                    or i.get("query")
                    or ""
                )[:80]
                if isinstance(i, dict)
                else ""
            ),
        )
        for n, i in seq
    ]
    dup_ratio = (len(sig) - len(set(sig))) / len(sig) if sig else 0.0
    return dict(
        acts=len(seq),
        web=web,
        git_arch=git_arch,
        changelog=changelog,
        answer_seek=web + git_arch + changelog,
        subagent=subagent,
        tests=len(test_cmds),
        broad_test=broad_test,
        edits=edits,
        edited_no_test=1 if (edits > 0 and not test_cmds) else 0,
        prose=prose,
        dup_ratio=dup_ratio,
    )


def main():
    with open(f"{FD}/results.csv") as fh:
        rows = list(csv.DictReader(fh))
    cost = collections.defaultdict(lambda: collections.defaultdict(float))
    score = collections.defaultdict(lambda: collections.defaultdict(list))
    turns = collections.defaultdict(lambda: collections.defaultdict(float))
    for r in rows:
        t = r.get("instance_id") or r.get("task")
        cost[r["arm"]][t] += float(r["cost_usd"] or 0)
        score[r["arm"]][t].append(float(r["score"] or 0))
        turns[r["arm"]][t] += float(r["num_turns"] or 0)
    tasks = sorted(cost["atelier"])
    agg = {}
    for t in tasks:
        s = collections.Counter()
        for rep in ("1", "2", "3"):
            fp = f"{FD}/{t}_atelier_rep{rep}.flow"
            if os.path.exists(fp):
                for k, v in signals(fp).items():
                    s[k] += v
        agg[t] = s
    out = []
    for t in tasks:
        b, a = cost["baseline"][t], cost["atelier"][t]
        loss = 100 * (a - b) / b if b else 0
        ds = (sum(score["atelier"][t]) - sum(score["baseline"][t])) / 3
        out.append((a - b, loss, t, b, a, ds, agg[t]))
    print(
        f"{'task':26}{'b$':>6}{'a$':>7}{'dD$':>7}{'loss%':>6}{'dSc':>6}"
        f"{'turnB/A':>11}{'ansSeek':>8}{'subAg':>6}{'broadT':>7}{'dupR':>6}"
    )
    for d, loss, t, b, a, ds, s in sorted(out, reverse=True):
        ta = f"{int(turns['baseline'][t])}/{int(turns['atelier'][t])}"
        print(
            f"{t[:26]:26}{b:6.2f}{a:7.2f}{d:+7.2f}{loss:6.0f}{ds:+6.2f}"
            f"{ta:>11}{s['answer_seek']:8}{s['subagent']:6}{s['broad_test']:7}{s['dup_ratio'] / 3:6.2f}"
        )
    balloon = [(t, s, a - b, ds) for d, loss, t, b, a, ds, s in out if s["subagent"] >= 10]
    lean = [(t, s, a - b, ds) for d, loss, t, b, a, ds, s in out if s["subagent"] < 10]

    def avg(group, key):
        return round(sum(g[1][key] for g in group) / len(group), 1) if group else 0

    print(f"\nBUCKET BY RUNAWAY-EXPLORATION (subagent>=10): {len(balloon)} balloon vs {len(lean)} lean")
    for label, g in (("balloon", balloon), ("lean", lean)):
        print(f"  {label:8} tasks={[x[0].split('__')[-1] for x in g]}")
        print(
            f"           avg acts={avg(g, 'acts')} ansSeek={avg(g, 'answer_seek')} "
            f"subagent={avg(g, 'subagent')} | sum dD$={round(sum(x[2] for x in g), 2):+} "
            f"sum dScore={round(sum(x[3] for x in g), 2):+}"
        )


if __name__ == "__main__":
    main()
