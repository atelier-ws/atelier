"""Suite-wide tool-usage anatomy across atelier flows: where do turns/tool-calls go?

Classifies every tool call and flags recurring waste patterns (repeat full-suite
test runs, REPL probes, edit->shell->re-edit cycles).
"""

import glob
import re
import sys
from collections import Counter

sys.path.insert(0, "benchmarks")
from wire_savings._traj import turns

flows = sorted(glob.glob(sys.argv[1] + "/*_atelier_rep*.flow"))
tool_counts: Counter = Counter()
shell_kind: Counter = Counter()
total_turns = 0
edit_then_shell = 0  # edit immediately followed by a shell (verify-by-shell pattern)
repeat_testruns = 0  # flows that ran the test suite >=3 times
flow_n = 0

TEST_RE = re.compile(r"pytest|runtests|\.test\(|python -m pytest|tox")
REPL_RE = re.compile(r"python -c|python3 -c")

for f in flows:
    try:
        rows = turns(f)
    except Exception:
        continue
    if not rows:
        continue
    flow_n += 1
    total_turns += len(rows)
    seq = []
    testruns = 0
    for _text, tools in rows:
        for t in tools:
            name = t.split("(", 1)[0]
            tool_counts[name] += 1
            seq.append(name)
            if name == "a:shell":
                if TEST_RE.search(t):
                    shell_kind["test-run"] += 1
                    testruns += 1
                elif REPL_RE.search(t):
                    shell_kind["repl-probe"] += 1
                else:
                    shell_kind["other-shell"] += 1
    for i in range(len(seq) - 1):
        if seq[i] == "a:edit" and seq[i + 1] == "a:shell":
            edit_then_shell += 1
    if testruns >= 3:
        repeat_testruns += 1

print(
    f"flows analyzed: {flow_n} | total opus turns: {total_turns} | avg {total_turns / max(flow_n, 1):.1f} turns/flow\n"
)
print("=== tool-call mix (all atelier flows) ===")
tot = sum(tool_counts.values())
for name, c in tool_counts.most_common():
    print(f"  {name:<12} {c:>5}  ({c / tot * 100:4.1f}%)")
print(f"\n=== shell sub-types ({sum(shell_kind.values())} shell calls) ===")
for k, c in shell_kind.most_common():
    print(f"  {k:<12} {c:>5}")
print("\n=== waste signals ===")
print(f"  edit->shell adjacency (verify-by-shell): {edit_then_shell}  (each could be an in-tool verify)")
print(f"  flows running test-suite >=3x: {repeat_testruns}/{flow_n}")
