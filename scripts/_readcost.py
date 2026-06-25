import re
from collections import defaultdict
from pathlib import Path

D = Path("reports/benchmark/codebench/swe50_stress_run1")

# normalize tool names across arms
ATEL = {"read": "READ", "grep": "GREP/SEARCH", "relations": "GREP/SEARCH"}
BASE = {"Read": "READ", "Grep": "GREP/SEARCH", "Glob": "GREP/SEARCH"}


def profile(dump: Path, arm: str):
    t = dump.read_text(errors="replace")
    blocks = t.split("=== Turn")
    last = None
    agg = defaultdict(lambda: [0, 0])  # cat -> [count, bytes]
    for b in blocks:
        # find tool_use names in this block (assistant side)
        if arm == "atelier":
            for m in re.finditer(r"tool_use: mcp__plugin_atelier_atelier__([a-z]+)", b):
                last = ATEL.get(m.group(1))
        else:
            for m in re.finditer(r"tool_use: ([A-Za-z_]+)", b):
                last = BASE.get(m.group(1))
        if "tool_result" in b and last:
            res = b.split("tool_result", 1)[1]
            agg[last][0] += 1
            agg[last][1] += len(res)
            last = None
    return agg


for arm, pat in (("baseline", "*baseline*_dump.txt"), ("atelier", "*atelier*_dump.txt")):
    dumps = sorted(D.glob(pat))
    tot = defaultdict(lambda: [0, 0])
    nreps = 0
    for d in dumps:
        nreps += 1
        for cat, (c, by) in profile(d, arm).items():
            tot[cat][0] += c
            tot[cat][1] += by
    print(f"=== {arm} ({nreps} reps) ===")
    for cat in ("READ", "GREP/SEARCH"):
        c, by = tot[cat]
        print(
            f"  {cat:12} ops={c:4} ({c / nreps:.1f}/rep)  bytes={by:8,} ({by // nreps:6,}/rep)  avg={by // max(c, 1):5,}B/op"
        )
    allc = sum(v[0] for v in tot.values())
    allb = sum(v[1] for v in tot.values())
    print(f"  read+grep TOTAL/rep: {allc / nreps:.1f} ops, {allb // nreps:,}B injected into context\n")
