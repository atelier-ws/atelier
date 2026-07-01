"""Provision diverse-6 SWE-bench repos for the multi-repo retrieval fitness.

Per repo: pick the dump-mined task with the most queries as the snapshot anchor,
clone + checkout its base_commit, build
the Atelier symbol index into /tmp/idx_<repo>.db, warm zoekt. Emits the raw query
universe benchmarks/codebench/data/bench_pairs_swebench_gold.json: {pairs:[[query,tid,prefix]],
true_map:{tid:[files]}, repos:{prefix:{ws,db,anchor}}}, then derives the canonical
retrieval gold benchmarks/codebench/data/bench_pairs_def_gold.json (build_definition_gold.py)
that every eval reads. Idempotent: skips clone/index when present.

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

        safe = prefix.replace("/", "_")
        ws, db = Path(f"/tmp/idx_ws_{safe}"), Path(f"/tmp/idx_{safe}.db")
        if not ws.exists() or not any(ws.iterdir()):
            # Shallow-fetch just the pinned commit (not full history) -- a plain
            # `git clone` of a large/old repo (e.g. django) can take long enough to
            # blow the timeout and leave a broken .git-only checkout behind.
            print(f"[{prefix}] shallow-fetch {repo}@{base_commit[:10]} -> {ws}", flush=True)
            ws.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "--quiet", str(ws)], check=True, timeout=60)
            subprocess.run(
                ["git", "-C", str(ws), "remote", "add", "origin", f"https://github.com/{repo}.git"],
                check=True,
                timeout=60,
            )
            rev = base_commit or "HEAD"
            subprocess.run(
                ["git", "-C", str(ws), "fetch", "--quiet", "--depth", "1", "origin", rev], check=True, timeout=1200
            )
            subprocess.run(["git", "-C", str(ws), "checkout", "--quiet", "FETCH_HEAD"], check=True, timeout=300)
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

    with open("benchmarks/codebench/data/bench_pairs_swebench_gold.json", "w") as fh:
        json.dump({"pairs": pairs, "true_map": true_map, "repos": repos_meta}, fh)
    uniq = len({(q, p) for q, _, p in pairs})
    print(f"\nDONE: {len(pairs)} pairs | {uniq} unique (query,repo) | {len(repos_meta)} repos", flush=True)
    # bench_pairs_multi.json is the RAW provisioning output (the full query universe
    # + SWE-edit true_map + repo map). Derive the canonical retrieval gold from it:
    # the definition gold that every eval reads. Re-derivable cheaply (no re-clone)
    # when tuning the gold's parameters.
    print("Deriving definition gold -> bench_pairs_def_gold.json ...", flush=True)
    subprocess.run([sys.executable, "benchmarks/codebench/build_definition_gold.py"], check=True)
    # Content/usage gold (grep-derived): gold = files whose CONTENT matches the
    # query. Complements the definition gold; this is the retrieval mode where the
    # Zoekt trigram channel earns its keep. Selectable via `eval retrieval --gold content`.
    print("Deriving content gold -> bench_pairs_content_gold.json ...", flush=True)
    subprocess.run([sys.executable, "benchmarks/codebench/build_content_gold.py"], check=True)


if __name__ == "__main__":
    main()
