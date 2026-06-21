"""Systematic per-flow audit of EVERY atelier run across all swe tasks.

One row per flow with behavior signals; per-task rollup. Corrupt flows marked.
Usage: python _flow_audit.py <results_dir>
"""

import glob
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, "benchmarks")
from wire_savings._trace_results import largest_request, text_of

D = sys.argv[1]

# cost / correct / turns from results.jsonl
meta = {}
with open(os.path.join(D, "results.jsonl")) as fh:
    _meta_lines = fh.readlines()
for line in _meta_lines:
    if not line.strip():
        continue
    r = json.loads(line)
    if r["arm"] == "atelier":
        meta[(r["task"], r.get("rep"))] = (r.get("correct"), r.get("cost_usd") or 0, r.get("num_turns") or 0)

REPL = re.compile(r"python3? -c")
TEST = re.compile(r"pytest|runtests|\.test\(|python -m pytest")
PATH = re.compile(r'"path"\s*:\s*"([^"]+)"')
RANGE = re.compile(r'"range"\s*:\s*"([^"]*)"')


def audit(flow):
    j = largest_request(flow)
    if not j:
        return None
    tools = defaultdict(int)
    read_keys = defaultdict(int)
    test_cmds = defaultdict(int)
    sig = dict(
        repeat_read=0,
        consec_repl=0,
        empty_grep=0,
        failed_edit=0,
        repeat_test=0,
        edit_shell=0,
        subagent=0,
        web=0,
        first_edit=None,
    )
    seq = []
    pending = None
    prev_repl = False
    ncalls = 0
    for m in j.get("messages") or []:
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                nm = (b.get("name") or "").replace("mcp__plugin_atelier_atelier__", "")
                inp = b.get("input") or {}
                tools[nm] += 1
                ncalls += 1
                seq.append(nm)
                if nm in ("Agent", "Task"):
                    sig["subagent"] += 1
                if nm == "edit" and sig["first_edit"] is None:
                    sig["first_edit"] = ncalls
                if nm == "read":
                    key = (inp.get("path"), inp.get("range"))
                    read_keys[key] += 1
                    if read_keys[key] > 1:
                        sig["repeat_read"] += 1
                if nm == "shell":
                    cmd = str(inp.get("command") or "")
                    is_repl = bool(REPL.search(cmd))
                    if is_repl and prev_repl:
                        sig["consec_repl"] += 1
                    prev_repl = is_repl
                    if TEST.search(cmd):
                        k = re.sub(r"\s+", " ", cmd)[:80]
                        test_cmds[k] += 1
                        if test_cmds[k] > 1:
                            sig["repeat_test"] += 1
                else:
                    prev_repl = False
                pending = nm
            elif b.get("type") == "tool_result" and pending:
                res = text_of(b.get("content"))
                if pending == "edit" and ('"failed":[{' in res or '"failed": [{' in res):
                    sig["failed_edit"] += 1
                if pending == "grep" and ("(0 files)" in res or '"content":[]' in res or len(res) < 20):
                    sig["empty_grep"] += 1
                if pending in ("Agent", "Task") and re.search(
                    r"raw\.githubusercontent|github\.com|verbatim|upstream|gold", res, re.I
                ):
                    sig["web"] += 1
                pending = None
    for i in range(len(seq) - 1):
        if seq[i] == "edit" and seq[i + 1] == "shell":
            sig["edit_shell"] += 1
    return tools, sig


flows = sorted(glob.glob(D + "/*_atelier_rep*.flow"))
by_task = defaultdict(list)
corrupt = []
for f in flows:
    base = os.path.basename(f)
    mt = re.match(r"(.+)_atelier_rep(\d+)\.flow", base)
    task, rep = mt.group(1), int(mt.group(2))
    try:
        out = audit(f)
    except Exception:
        out = None
    if out is None:
        corrupt.append((task, rep))
        continue
    by_task[task].append((rep, out[0], out[1]))

hdr = f"{'task/rep':<26}{'ok':>3}{'$':>6}{'turns':>6}  {'rd gp ed sh repl ag':>20}  waste(rR cR eG fE rT eS web)"
print(hdr)
print("-" * len(hdr))
for task in sorted(by_task):
    for rep, tools, sig in sorted(by_task[task]):
        c, cost, turns = meta.get((task, rep), (None, 0, 0))
        ok = "✓" if c is True else ("✗" if c is False else "?")
        tmix = f"{tools.get('read', 0):>2} {tools.get('grep', 0):>2} {tools.get('edit', 0):>2} {tools.get('shell', 0):>2} {tools.get('node', 0):>2} {sig['subagent']:>2}"
        waste = f"{sig['repeat_read']:>2} {sig['consec_repl']:>2} {sig['empty_grep']:>2} {sig['failed_edit']:>2} {sig['repeat_test']:>2} {sig['edit_shell']:>2} {sig['web']:>2}"
        print(f"{task.split('__')[1] + '/' + str(rep):<26}{ok:>3}{cost:>6.2f}{turns:>6}  {tmix:>20}  {waste}")

print(f"\ncorrupt/unreadable flows ({len(corrupt)}): {[t.split('__')[1] + '/' + str(r) for t, r in corrupt]}")
print(
    "legend: rR=repeat-read cR=consec-repl eG=empty-grep fE=failed-edit rT=repeat-test eS=edit→shell web=subagent-web-fetch"
)
