import re
from pathlib import Path

D = Path("reports/benchmark/codebench/swe50_stress_run1")


def scope(pathval: str) -> str:
    if not pathval or pathval == ".":
        return "TREE"
    base = pathval.split("#")[0]
    if base.endswith((".py", ".txt", ".rst", ".cfg", ".toml", ".md")):
        return "FILE"
    return "DIR"


print(f"{'rep':40} {'turns':>5} | greps by scope (FILE/DIR/TREE)")
for d in sorted(D.glob("*atelier*_dump.txt"), key=lambda p: p.read_text(errors="replace").count("=== Turn")):
    t = d.read_text(errors="replace")
    greps = re.findall(r"tool_use: mcp__plugin_atelier_atelier__grep\] (\{.*?\})", t, re.S)
    counts = {"FILE": 0, "DIR": 0, "TREE": 0}
    for g in greps:
        m = re.search(r'"path":\s*"(.*?)"', g)
        counts[scope(m.group(1) if m else "")] += 1
    turns = t.count("=== Turn")
    name = d.name.replace("_atelier", "").replace(".flow_dump.txt", "")
    print(
        f"{name:40} {turns:5} | FILE={counts['FILE']:2} DIR={counts['DIR']:2} TREE={counts['TREE']:2}  (total {len(greps)})"
    )
