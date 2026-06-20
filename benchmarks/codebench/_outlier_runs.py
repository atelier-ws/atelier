"""List individual reps that look failed / capped / cost-outlier / flaky -> rerun candidates."""

import json
import pathlib
import statistics
from collections import defaultdict

BASE = pathlib.Path("reports/benchmark/codebench/swe12_20260619T055432Z/results.jsonl.bak_before_turncap_rerun")
LIVE = BASE.with_name("results.jsonl")

# Load backup (fully graded), then overlay the re-run sphinx-8120 atelier rows.
by_group = defaultdict(list)
for line in BASE.read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        by_group[(r["task"], r["arm"])].append(r)
by_group[("sphinx-doc__sphinx-8120", "atelier")] = [
    json.loads(line)
    for line in LIVE.read_text().splitlines()
    if line.strip() and json.loads(line)["task"] == "sphinx-doc__sphinx-8120" and json.loads(line)["arm"] == "atelier"
]

flagged = []
for (task, arm), reps in by_group.items():
    costs = [x.get("cost_usd") or 0.0 for x in reps]
    med = statistics.median(costs) if costs else 0.0
    n_correct = sum(1 for x in reps if x.get("correct") is True)
    for x in reps:
        rep = x.get("rep")
        c = x.get("cost_usd") or 0.0
        t = x.get("num_turns") or 0
        reasons = []
        if x.get("ok") is not True:
            reasons.append("FAILED(ok=False)")
        if x.get("timed_out"):
            reasons.append("TIMED_OUT")
        if t >= 100:
            reasons.append(f"CAP/long({t}t)")
        if c >= 1.0 and med > 0 and c >= 2 * med and c == max(costs):
            reasons.append(f"COST_OUTLIER({c:.2f} vs med {med:.2f})")
        if x.get("correct") is False and n_correct >= 1:
            reasons.append("FLAKY_FAIL(sibling passed)")
        if reasons:
            flagged.append((task.split("__")[1], arm, rep, x.get("ok"), x.get("correct"), t, c, "; ".join(reasons)))

flagged.sort(key=lambda r: (r[1], -r[6]))
print(f"{'task':<20}{'arm':<9}{'rep':>3}{'ok':>6}{'corr':>6}{'turns':>6}{'cost':>8}  reasons")
print("-" * 100)
for task, arm, rep, ok, corr, t, c, reasons in flagged:
    print(f"{task:<20}{arm:<9}{rep!s:>3}{ok!s:>6}{corr!s:>6}{t:>6}{c:>8.2f}  {reasons}")
print(f"\n{len(flagged)} flagged runs")
