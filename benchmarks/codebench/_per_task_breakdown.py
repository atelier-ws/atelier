"""Per-task graded breakdown from the pre-turncap-rerun snapshot (authoritative)."""

import json
import pathlib
import statistics
from collections import defaultdict

P = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl.bak_before_turncap_rerun")
rows = defaultdict(list)
for line in P.read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    rows[(r["task"], r["arm"])].append(r)

# Overlay the freshly re-run + re-graded sphinx-8120 atelier rows (rep2 fixed).
LIVE = P.with_name("results.jsonl")
rows[("sphinx-doc__sphinx-8120", "atelier")] = []
for line in LIVE.read_text().splitlines():
    if not line.strip():
        continue
    r = json.loads(line)
    if r["task"] == "sphinx-doc__sphinx-8120" and r["arm"] == "atelier":
        rows[(r["task"], r["arm"])].append(r)


def costs(rs):
    return sorted(x["cost_usd"] for x in rs if x.get("cost_usd") is not None)


def cost(rs):
    v = costs(rs)
    return statistics.median(v) if v else 0.0


def lo(rs):
    v = costs(rs)
    return v[0] if v else 0.0


def hi(rs):
    v = costs(rs)
    return v[-1] if v else 0.0


def correct(rs):
    return sum(1 for x in rs if x.get("correct") is True)


def saving(t):
    b = cost(rows[(t, "baseline")])
    a = cost(rows[(t, "atelier")])
    return (a - b) / b if b else 0.0


tasks = sorted({t for (t, _a) in rows}, key=saving)  # most saving (most negative) first
hdr = f"{'task':<24}{'base':>5}{'atl':>5}" f"{'base cheap/med/exp':>22}{'atl cheap/med/exp':>22}{'Δmed':>7}"
print(hdr)
print("-" * len(hdr))
tb = ta = 0.0
bc = cc = 0
for t in tasks:
    bl, b, bh = lo(rows[(t, "baseline")]), cost(rows[(t, "baseline")]), hi(rows[(t, "baseline")])
    al, a, ah = lo(rows[(t, "atelier")]), cost(rows[(t, "atelier")]), hi(rows[(t, "atelier")])
    bcr = correct(rows[(t, "baseline")])
    ccr = correct(rows[(t, "atelier")])
    tb += b
    ta += a
    bc += bcr
    cc += ccr
    d = f"{(a - b) / b * 100:+.0f}%" if b else "  -  "
    bcol = f"{bl:.2f}/{b:.2f}/{bh:.2f}"
    acol = f"{al:.2f}/{a:.2f}/{ah:.2f}"
    print(f"{t.split('__')[1]:<24}{bcr}/3{'':>0}{ccr}/3{'':>0}{bcol:>22}{acol:>22}{d:>7}")
print("-" * len(hdr))
print(f"{'TOTAL (median col summed)':<24}{bc}/60{cc:>2}/60{tb:>19.2f}{ta:>22.2f}  {(ta - tb) / tb * 100:+.1f}%")
