import collections
import json
from pathlib import Path

from benchmarks.codebench import swebench_data, swebench_grade

OUT = Path("reports/benchmark/codebench/swe50_stress_run1").resolve()
rows = [json.loads(x) for x in (OUT / "results.jsonl").read_text().splitlines() if x.strip()]

# Finished atelier reps with a patch on disk and no grade yet.
atel = [r for r in rows if r["arm"] == "atelier" and r.get("ok") and r.get("valid")]
task_ids = sorted({r["task"] for r in atel})
print(f"grading {len(atel)} atelier reps across {len(task_ids)} tasks", flush=True)

insts = swebench_data.load_instances(dataset=None, instances=task_ids)
by_id = {i.instance_id: i for i in insts}

by_rep = collections.defaultdict(list)
for r in atel:
    by_rep[r["rep"]].append(r)

resolved_all = {}  # (task, rep) -> bool
for rep in sorted(by_rep):
    group = by_rep[rep]
    patches = {}
    use_insts = []
    for r in group:
        pp = OUT / f"{r['task']}_atelier_rep{rep}.patch"
        if pp.exists() and r["task"] in by_id:
            patches[r["task"]] = pp.read_text(encoding="utf-8")
            use_insts.append(by_id[r["task"]])
    if not patches:
        continue
    print(f"[grade] atelier rep{rep}: {len(patches)} patch(es)", flush=True)
    res = swebench_grade.grade(
        use_insts,
        patches,
        dataset_name=None,
        work_dir=OUT / f"grade_atelier_rep{rep}",
        max_workers=2,
        timeout=1800,
    )
    for r in group:
        resolved_all[(r["task"], rep)] = bool(res.get(r["task"], False))

print("\n=== per-task atelier resolved (new persona) ===")
by_task = collections.defaultdict(list)
for (t, _rep), ok in resolved_all.items():
    by_task[t].append(ok)
for t in sorted(by_task):
    v = by_task[t]
    print(f"{t:30} {sum(v)}/{len(v)} resolved")

# persist for the comparison step
(OUT / "_atel_grades.json").write_text(json.dumps({f"{t}|{rep}": ok for (t, rep), ok in resolved_all.items()}))
print("\nwrote _atel_grades.json")
