"""Provision diverse-6 SWE-bench repos for the multi-repo retrieval fitness.

Per repo: pick the dump-mined task with the most queries as the snapshot anchor,
clone + checkout its base_commit (Django reuses the existing checkout/index), build
the Atelier symbol index into /tmp/idx_<repo>.db, warm zoekt. Emits
benchmarks/codebench/data/bench_pairs_multi.json: {pairs:[[query,tid,prefix]], true_map:{tid:[files]},
repos:{prefix:{ws,db,anchor}}}. Idempotent: skips clone/index when present.

The main work is guarded by ``if __name__ == "__main__"`` so that index_repo()'s
worker processes (which re-import this module) do NOT re-run provisioning.
"""

import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from benchmarks.codebench import swebench_data

try:
    from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
except Exception:
    get_zoekt_supervisor = None

RUN = Path("reports/benchmark/codebench/swe50_stress_run1")
TESTRE = re.compile(r"(^|/)(test_|tests?/|conftest)")
TID_RE = re.compile(r"^(.*?)_(?:atelier|baseline)_rep\d+\.flow_dump\.txt$")
GREP = re.compile(r"mcp__plugin_atelier_atelier__grep\] (\{.*?\})", re.S)

PREFIX2REPO = {
    "django__django": "django/django",
    "pytest-dev__pytest": "pytest-dev/pytest",
    "astropy__astropy": "astropy/astropy",
    "sympy__sympy": "sympy/sympy",
    "scikit-learn__scikit-learn": "scikit-learn/scikit-learn",
    "pydata__xarray": "pydata/xarray",
}


def mine_queries(dump):
    out = []
    for blob in GREP.findall(dump.read_text(errors="replace")):
        m = re.search(r'"regex":\s*"((?:[^"\\]|\\.)*)"', blob)
        if m:
            q = m.group(1).encode().decode("unicode_escape", "replace")
            if 3 <= len(q) <= 80:
                out.append(q)
    return out


def symbol_count(db):
    try:
        con = sqlite3.connect(str(db))
        n = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
        con.close()
        return n
    except Exception:
        return -1


def main():
    django_ws = Path(open("/tmp/djroot.txt").read().strip())
    django_db = Path("/tmp/chanx_django5.db")
    repos_meta, pairs, true_map = {}, [], {}

    for prefix, repo in PREFIX2REPO.items():
        dumps = sorted(d for d in RUN.glob(f"{prefix}*_dump.txt") if TID_RE.match(d.name))
        by_task = {}
        for d in dumps:
            by_task.setdefault(TID_RE.match(d.name).group(1), []).extend(mine_queries(d))
        if not by_task:
            print(f"[{prefix}] no dumps, skip", flush=True)
            continue
        task_ids = sorted(by_task)
        insts = {i.instance_id: i for i in swebench_data.load_instances(dataset=None, instances=task_ids)}
        anchor = max(task_ids, key=lambda t: len(by_task.get(t, [])))
        base_commit = getattr(insts.get(anchor), "base_commit", "") if insts.get(anchor) else ""

        if prefix == "django__django":
            ws, db = django_ws, django_db
        else:
            safe = prefix.replace("/", "_")
            ws, db = Path(f"/tmp/idx_ws_{safe}"), Path(f"/tmp/idx_{safe}.db")
            if not ws.exists() or not any(ws.iterdir()):
                print(f"[{prefix}] clone {repo}@{base_commit[:10]} -> {ws}", flush=True)
                subprocess.run(
                    ["git", "clone", "--quiet", f"https://github.com/{repo}.git", str(ws)], check=True, timeout=1200
                )
                if base_commit:
                    subprocess.run(["git", "-C", str(ws), "checkout", "--quiet", base_commit], check=True, timeout=300)
            if not db.exists():
                print(f"[{prefix}] indexing -> {db}", flush=True)
                t0 = time.time()
                try:
                    CodeContextEngine(ws, db_path=db, autosync_enabled=False).index_repo()
                except Exception as e:
                    print(f"[{prefix}] INDEX FAILED: {e}", flush=True)
                    continue
                print(f"[{prefix}] index done {time.time() - t0:.0f}s, symbols={symbol_count(db)}", flush=True)
            else:
                print(f"[{prefix}] index exists, symbols={symbol_count(db)}", flush=True)

        if get_zoekt_supervisor is not None:
            try:
                get_zoekt_supervisor(ws)
            except Exception as e:
                print(f"[{prefix}] zoekt warn: {e}", flush=True)

        kept = 0
        for tid in task_ids:
            inst = insts.get(tid)
            files = re.findall(r"^\+\+\+ b/(.+)$", getattr(inst, "patch", "") or "", re.M) if inst else []
            files = [f for f in files if not TESTRE.search(f) and (ws / f).exists()]
            if files:
                true_map[tid] = files
                for q in by_task.get(tid, []):
                    pairs.append([q, tid, prefix])
                    kept += 1
        repos_meta[prefix] = {"ws": str(ws), "db": str(db), "anchor": anchor, "base_commit": base_commit}
        print(f"[{prefix}] ready: {kept} pairs, symbols={symbol_count(db)}", flush=True)

    json.dump(
        {"pairs": pairs, "true_map": true_map, "repos": repos_meta},
        open("benchmarks/codebench/data/bench_pairs_multi.json", "w"),
    )
    uniq = len({(q, p) for q, _, p in pairs})
    print(f"\nDONE: {len(pairs)} pairs | {uniq} unique (query,repo) | {len(repos_meta)} repos", flush=True)


if __name__ == "__main__":
    main()
