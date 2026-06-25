import json
from pathlib import Path

p = Path("reports/benchmark/codebench/swe50_stress_run1/results.jsonl")
rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
for r in rows:
    if r["arm"] == "atelier":
        print(
            f"{r['task']:30} rep{r['rep']} ok={r['ok']} correct={r.get('correct')} judge={r.get('judge_model')!r} reason={r.get('judge_reason')!r} patch_exists=",
            end="",
        )
        # check patch file
        fp = r.get("flow_path", "")
        patch = fp.replace(".flow", ".patch") if fp else ""
        print(Path(patch).exists() if patch else "n/a", f"valid={r.get('valid')}")
