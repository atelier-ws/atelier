import re
import statistics
from pathlib import Path

D = Path("reports/benchmark/codebench/swe50_stress_run1")
print("per-rep: FIND-code ops (read+grep+relations) vs FIX-loop ops (edit + test), by turns")
print(f"{'rep':42} {'turns':>5} {'find':>5} {'fix':>5}")
rows = []
for d in sorted(D.glob("*atelier*_dump.txt")):
    t = d.read_text(errors="replace")
    ops = re.findall(r"tool_use: mcp__plugin_atelier_atelier__([a-z]+)", t)
    cmds = re.findall(r"tool_use: mcp__plugin_atelier_atelier__bash\] \{\"command\": \"(.*?)\"\}", t, re.S)
    find = sum(1 for o in ops if o in ("read", "grep", "relations"))
    edit = sum(1 for o in ops if o == "edit")
    test = sum(1 for c in cmds if re.search(r"runtests|pytest|python -m|test", c))
    turns = t.count("=== Turn")
    name = d.name.replace("_atelier", "").replace(".flow_dump.txt", "")
    rows.append((turns, find, edit + test, name))
for turns, find, fix, name in sorted(rows):
    print(f"{name:42} {turns:5} {find:5} {fix:5}")

ts = [r[0] for r in rows]
fs = [r[1] for r in rows]
xs = [r[2] for r in rows]


def corr(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return num / den if den else 0


print(f"\ncorr(turns, FIND-ops) = {corr(ts, fs):.2f}")
print(f"corr(turns, FIX-ops)  = {corr(ts, xs):.2f}")
