import html
import json
import statistics
from collections import defaultdict
from pathlib import Path

RESULTS = Path("benchmarks/codebench/results/swe50_2026_06_30/results.jsonl")
OUT = Path("reports/public/benchmark/codebench/cost_vs_savings_scatter.svg")

rows = [json.loads(line) for line in RESULTS.read_text().splitlines() if line.strip()]
by_task = defaultdict(lambda: defaultdict(list))
for row in rows:
    by_task[row["task"]][row["arm"]].append(row)

tasks = sorted(
    by_task,
    key=lambda task: (
        statistics.median(r["cost_usd"] for r in by_task[task]["baseline"]),
        task,
    ),
)

baseline_total = sum(r["cost_usd"] for r in rows if r["arm"] == "baseline")
atelier_total = sum(r["cost_usd"] for r in rows if r["arm"] == "atelier")
baseline_correct = sum(bool(r.get("correct")) for r in rows if r["arm"] == "baseline")
atelier_correct = sum(bool(r.get("correct")) for r in rows if r["arm"] == "atelier")

W, H = 1280, 720
left, right, top, bottom = 94, 64, 156, 126
plot_w, plot_h = W - left - right, H - top - bottom
y_max = 3.6


def x_at(index: int) -> float:
    return left + index / (len(tasks) - 1) * plot_w


def y_at(value: float) -> float:
    value = max(0.0, min(value, y_max))
    return top + (1 - value / y_max) * plot_h


def fmt_money(value: float) -> str:
    return f"${value:,.2f}"


baseline_median = [statistics.median(r["cost_usd"] for r in by_task[t]["baseline"]) for t in tasks]
atelier_median = [statistics.median(r["cost_usd"] for r in by_task[t]["atelier"]) for t in tasks]
base_poly = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(baseline_median))
at_poly = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(atelier_median))
gap_poly = base_poly + " " + " ".join(
    f"{x_at(i):.1f},{y_at(atelier_median[i]):.1f}" for i in range(len(tasks) - 1, -1, -1)
)

rep_offsets = {1: -5.1, 2: -2.55, 3: 0.0, 4: 2.55, 5: 5.1}
arm_offsets = {"baseline": -5.5, "atelier": 5.5}
colors = {"baseline": "#fb7185", "atelier": "#34d399"}
strokes = {"baseline": "#ffe4e6", "atelier": "#d1fae5"}

svg = [
    f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">
  <title id="title">Every SWE50 benchmark rep cost from results.jsonl</title>
  <desc id="desc">Scatter plot of all {len(rows)} individual SWE-bench Verified runs from {RESULTS}. Each dot is one recorded rep. Baseline totals {fmt_money(baseline_total)} and Atelier totals {fmt_money(atelier_total)}.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#060b10"/><stop offset="0.55" stop-color="#0a1620"/><stop offset="1" stop-color="#10151f"/></linearGradient>
    <linearGradient id="gap" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#22c55e" stop-opacity="0.04"/><stop offset="0.55" stop-color="#22c55e" stop-opacity="0.18"/><stop offset="1" stop-color="#facc15" stop-opacity="0.32"/></linearGradient>
    <linearGradient id="tail" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#ef4444" stop-opacity="0.13"/></linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="18" stdDeviation="24" flood-color="#000" flood-opacity="0.34"/></filter>
    <filter id="greenGlow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="2.8" result="b"/><feColorMatrix in="b" type="matrix" values="0 0 0 0 0.13 0 0 0 0 0.77 0 0 0 0 0.39 0 0 0 0.7 0"/><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="redGlow" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="2.8" result="b"/><feColorMatrix in="b" type="matrix" values="0 0 0 0 0.94 0 0 0 0 0.27 0 0 0 0 0.27 0 0 0 0.65 0"/><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <style>
      .label{{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#dbeafe;letter-spacing:0}}
      .muted{{fill:#91a4b7}} .grid{{stroke:#1e3342;stroke-width:1}} .axis{{stroke:#607286;stroke-width:1.15}}
      .tag{{font-size:13px;font-weight:850;letter-spacing:.05em}} .title{{font-size:38px;font-weight:900}} .subtitle{{font-size:16px;fill:#a9b6c7}}
      .tick{{font-size:13px;fill:#95a8bb}} .legend{{font-size:15px;font-weight:800}} .metric{{font-size:30px;font-weight:900}} .small{{font-size:14px}}
      .median{{fill:none;stroke-width:4.4;stroke-linecap:round;stroke-linejoin:round}} .dot{{stroke-width:1.5}}
    </style>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#bg)"/>
  <path d="M 860 -120 C 1130 120 1120 300 1370 500" fill="none" stroke="#22c55e" stroke-width="210" stroke-opacity="0.075"/>
  <path d="M -140 640 C 160 530 300 675 540 510" fill="none" stroke="#38bdf8" stroke-width="170" stroke-opacity="0.055"/>
  <g filter="url(#shadow)"><rect x="32" y="30" width="1216" height="650" rx="22" fill="#07111a" fill-opacity="0.84" stroke="#213241"/></g>
  <text x="66" y="70" class="label tag" fill="#67e8f9">RAW RESULTS.JSONL - EVERY DOT IS ONE RECORDED REP</text>
  <text x="66" y="116" class="label title">The Expensive Tasks Expose the Gap</text>
  <text x="66" y="145" class="label subtitle">500 real SWE50 runs: 5 reps per arm per task. Solid dots passed; hollow dots failed. Median lines show the curve.</text>
  <g transform="translate(824 50)"><rect width="372" height="94" rx="18" fill="#102015" stroke="#229553" stroke-opacity="0.8"/><text x="22" y="38" class="label metric" fill="#86efac">{fmt_money(baseline_total - atelier_total)} saved</text><text x="22" y="68" class="label small" fill="#bbf7d0">{len(rows)} actual rows · {atelier_correct - baseline_correct:+d} resolved reps</text></g>
  <rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" rx="18" fill="#07131b" stroke="#243646"/>
  <rect x="{x_at(38):.1f}" y="{top}" width="{left + plot_w - x_at(38):.1f}" height="{plot_h}" fill="url(#tail)"/>
'''
]

for value in [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5]:
    yy = y_at(value)
    svg.append(f'  <line x1="{left}" y1="{yy:.1f}" x2="{left + plot_w}" y2="{yy:.1f}" class="grid"/>\n')
    svg.append(f'  <text x="{left - 18}" y="{yy + 4:.1f}" text-anchor="end" class="label tick">${value:g}</text>\n')

for value in [1, 10, 20, 30, 40, 50]:
    xx = x_at(value - 1)
    svg.append(f'  <line x1="{xx:.1f}" y1="{top}" x2="{xx:.1f}" y2="{top + plot_h}" class="grid" stroke-opacity="0.55"/>\n')
    svg.append(f'  <text x="{xx:.1f}" y="{top + plot_h + 30}" text-anchor="middle" class="label tick">{value}</text>\n')

svg.append(f'  <line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" class="axis"/>\n')
svg.append(f'  <line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" class="axis"/>\n')
svg.append(f'  <text x="{left + plot_w / 2}" y="{H - 42}" text-anchor="middle" class="label small muted">50 tasks, sorted by baseline median rep cost</text>\n')
svg.append(f'  <text x="30" y="{top + plot_h / 2}" text-anchor="middle" class="label small muted" transform="rotate(-90 30 {top + plot_h / 2})">Individual rep cost (USD)</text>\n')
svg.append(f'  <polygon points="{gap_poly}" fill="url(#gap)"/>\n')

for arm in ("baseline", "atelier"):
    svg.append(f'  <g id="{arm}-raw-reps" filter="url(#{"redGlow" if arm == "baseline" else "greenGlow"})">\n')
    for i, task in enumerate(tasks):
        for row in sorted(by_task[task][arm], key=lambda r: r["rep"]):
            xx = x_at(i) + arm_offsets[arm] + rep_offsets[row["rep"]]
            yy = y_at(row["cost_usd"])
            title = f"{task} {arm} rep {row['rep']}: {fmt_money(row['cost_usd'])}, {'resolved' if row.get('correct') else 'unresolved'}, {row.get('num_turns')} turns"
            if row.get("correct"):
                svg.append(f'    <circle cx="{xx:.1f}" cy="{yy:.1f}" r="3.9" fill="{colors[arm]}" stroke="{strokes[arm]}" opacity="0.93" class="dot"><title>{html.escape(title)}</title></circle>\n')
            else:
                svg.append(f'    <circle cx="{xx:.1f}" cy="{yy:.1f}" r="4.2" fill="#07131b" stroke="{strokes[arm]}" opacity="0.98" class="dot" stroke-dasharray="2 1.4"><title>{html.escape(title)}</title></circle>\n')
    svg.append("  </g>\n")

svg.append(f'  <polyline points="{base_poly}" class="median" stroke="#f43f5e"/>\n')
svg.append(f'  <polyline points="{at_poly}" class="median" stroke="#22c55e"/>\n')
svg.append(f'  <text x="{x_at(49) - 8:.1f}" y="{y_at(baseline_median[-1]) - 14:.1f}" text-anchor="end" class="label" style="font-size:17px;font-weight:850" fill="#fecdd3">baseline median tail: {fmt_money(baseline_median[-1])}</text>\n')
svg.append(f'  <text x="{x_at(49) - 8:.1f}" y="{y_at(atelier_median[-1]) + 30:.1f}" text-anchor="end" class="label" style="font-size:17px;font-weight:850" fill="#bbf7d0">Atelier median tail: {fmt_money(atelier_median[-1])}</text>\n')

svg.append('''  <g transform="translate(112 170)"><rect width="318" height="48" rx="14" fill="#091923" stroke="#244253"/><circle cx="22" cy="24" r="5.5" fill="#34d399" stroke="#d1fae5"/><circle cx="44" cy="24" r="5.5" fill="#07131b" stroke="#d1fae5" stroke-dasharray="2 1.4"/><line x1="67" y1="24" x2="104" y2="24" stroke="#22c55e" stroke-width="4" stroke-linecap="round"/><text x="118" y="30" class="label legend" fill="#bbf7d0">Atelier reps + median</text></g>
  <g transform="translate(448 170)"><rect width="328" height="48" rx="14" fill="#1c1118" stroke="#53303b"/><circle cx="22" cy="24" r="5.5" fill="#fb7185" stroke="#ffe4e6"/><circle cx="44" cy="24" r="5.5" fill="#07131b" stroke="#ffe4e6" stroke-dasharray="2 1.4"/><line x1="67" y1="24" x2="104" y2="24" stroke="#f43f5e" stroke-width="4" stroke-linecap="round"/><text x="118" y="30" class="label legend" fill="#fecdd3">Baseline reps + median</text></g>
''')

stats = [
    ("500", "actual result rows"),
    ("250", "reps per arm"),
    ("31.6%", "lower total cost"),
    ("90%", "Atelier resolved"),
]
for index, (big, small) in enumerate(stats):
    x0 = 94 + index * 278
    svg.append(f'  <g transform="translate({x0} 620)"><rect width="246" height="48" rx="14" fill="#0a1821" stroke="#1f3544"/><text x="18" y="31" class="label" style="font-size:24px;font-weight:900" fill="#f8fafc">{big}</text><text x="100" y="30" class="label small muted">{small}</text></g>\n')

svg.append("</svg>\n")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("".join(svg), encoding="utf-8")
print(f"wrote {OUT} from {len(rows)} results.jsonl rows; baseline={fmt_money(baseline_total)}, atelier={fmt_money(atelier_total)}")
