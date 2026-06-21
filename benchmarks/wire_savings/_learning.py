"""Quantify 'learning' waste across atelier flows: repeated reads of same path,
consecutive REPL probes (batchable), repeated identical test runs."""

import glob
import re
import sys
from collections import Counter

sys.path.insert(0, "benchmarks")
from wire_savings._traj import turns

flows = sorted(glob.glob(sys.argv[1] + "/*_atelier_rep*.flow"))
REPL = re.compile(r"python3? -c")
TEST = re.compile(r"pytest|runtests|[.]test[(]|python -m pytest")
PATH = re.compile(r'"path"\s*:\s*"([^"]+)"')

tot_repl = consec_repl = repeat_reads = repeat_testcmd = flow_n = 0
flows_with_consec = 0

for f in flows:
    try:
        rows = turns(f)
    except Exception:
        continue
    if not rows:
        continue
    flow_n += 1
    seen_paths: Counter = Counter()
    seen_tests: Counter = Counter()
    prev_repl = False
    had_consec = False
    for _text, tools in rows:
        for t in tools:
            name = t.split("(", 1)[0]
            if name == "a:shell":
                is_repl = bool(REPL.search(t))
                if is_repl:
                    tot_repl += 1
                    if prev_repl:
                        consec_repl += 1
                        had_consec = True
                prev_repl = is_repl
                if TEST.search(t):
                    key = re.sub(r"\s+", " ", t)[:80]
                    seen_tests[key] += 1
                    if seen_tests[key] > 1:
                        repeat_testcmd += 1
            else:
                prev_repl = False
            if name == "a:read":
                m = PATH.search(t)
                if m:
                    seen_paths[m.group(1)] += 1
                    if seen_paths[m.group(1)] > 1:
                        repeat_reads += 1
    if had_consec:
        flows_with_consec += 1

print(f"flows: {flow_n}")
print(f"REPL probes total: {tot_repl}")
print(f"  consecutive REPL probes (batchable into one script): {consec_repl}  in {flows_with_consec} flows")
print(f"repeat reads (same path read 2+x in a flow): {repeat_reads}")
print(f"repeat identical test commands: {repeat_testcmd}")
