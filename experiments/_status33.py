import re
from pathlib import Path

D = Path("reports/benchmark/codebench/swe50_rest33_smart")
log = (D / "run.log").read_text(errors="ignore")
lines = [l for l in log.splitlines() if "/atelier rep1:" in l]
costs = []
failed = []
cor = 0
for l in lines:
    if "correct=True" in l:
        cor += 1
    m = re.search(r"-> (\S+)/atelier.*cost=.([0-9.]+) turns=([0-9]+)", l)
    if m:
        costs.append(float(m.group(2)))
        if "correct=False" in l:
            failed.append((m.group(1), m.group(2), m.group(3)))
print(f"completed progress lines: {len(lines)}/33   correct={cor}/{len(lines)}")
print(f"total cost so far: ${sum(costs):.2f}   avg ${sum(costs) / max(len(costs), 1):.3f}")
print("FAILED (correct=False):")
for t, c, tn in failed:
    print(f"  {t:34} ${c} turns={tn}")
rj = D / "results.jsonl"
print(f"\nresults.jsonl rows: {sum(1 for _ in open(rj)) if rj.exists() else 'MISSING'}")
print("run ended cleanly:", "YES" if "Chart data" in log else "NO (no summary block yet)")
tail = log.splitlines()[-3:]
print("last log lines:", " | ".join(t.strip()[:80] for t in tail))
