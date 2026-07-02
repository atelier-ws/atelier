import collections
import json
from pathlib import Path

from benchmarks.codebench import swebench_data, swebench_grade

OUT = Path("reports/benchmark/codebench/swe50_stress_run1").resolve()
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]
grades = json.loads((OUT / "_grades.json").read_text()) if (OUT / "_grades.json").exists() else {}

# Grade only reps not already graded: atelier missing from _grades, baseline correct is None & missing.
to_grade = []
for r in rows:
    if not (r.get("ok") and r.get("valid")):
        continue
    key = f"{r['task']}|{r['arm']}|{r['rep']}"
    if key in grades:
        continue
    if r["arm"] == "atelier" or (r["arm"] == "baseline" and r.get("correct") is None):
        to_grade.append(r)

task_ids = sorted({r["task"] for r in to_grade})
print(f"grading {len(to_grade)} reps over {len(task_ids)} tasks: {[t.split('__')[-1] for t in task_ids]}", flush=True)
insts = swebench_data.load_instances(dataset=None, instances=task_ids)
by_id = {i.instance_id: i for i in insts}

grp = collections.defaultdict(list)
for r in to_grade:
    grp[(r["arm"], r["rep"])].append(r)

for (arm, rep), group in sorted(grp.items()):
    patches = {}
    use = []
    for r in group:
        pp = OUT / f"{r['task']}_{arm}_rep{rep}.patch"
        if pp.exists() and r["task"] in by_id:
            patches[r["task"]] = pp.read_text(encoding="utf-8")
            use.append(by_id[r["task"]])
    if not patches:
        continue
    print(f"[grade] {arm} rep{rep}: {len(patches)} patch(es)", flush=True)
    res = swebench_grade.grade(
        use, patches, dataset_name=None,
        work_dir=OUT / f"grade_{arm}_rep{rep}", max_workers=2, timeout=1800,
    )
    for r in group:
        grades[f"{r['task']}|{arm}|{rep}"] = bool(res.get(r["task"], False))

(OUT / "_grades.json").write_text(json.dumps(grades))
print(f"\ntotal grades now: {len(grades)}")
