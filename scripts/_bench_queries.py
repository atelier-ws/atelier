"""Large-scale offline retrieval benchmark: explore (upgraded) vs CodeGraph on the
REAL queries the model fired in past benchmarks. Scored by rank-of-gold-true-file.
Results depend only on (query, index), so each unique query runs once per system."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ["PATH"] = os.path.expanduser("~/go/bin") + os.pathsep + os.environ.get("PATH", "")
sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
from benchmarks.codebench import swebench_data

DJ = Path(open("/tmp/djroot.txt").read().strip())
DB = Path("/tmp/chanx_django5.db")
CGBIN = Path("/tmp/" + open("/tmp/cgdir.txt").read().strip()) / "dist/bin/codegraph.js"
RUN = Path("reports/benchmark/codebench/swe50_stress_run1")
TESTRE = re.compile(r"(^|/)(test_|tests?/|conftest)")

eng = CodeContextEngine(DJ, db_path=DB, autosync_enabled=False)
if not DB.exists():
    eng.index_repo()
sup = get_zoekt_supervisor(DJ)

# ---- 1. task -> gold true files that exist in this checkout ----
TID_RE = re.compile(r"^(.*?)_(?:atelier|baseline)_rep\d+\.flow_dump\.txt$")
dumps = sorted(d for d in RUN.glob("django__*_dump.txt") if TID_RE.match(d.name))
task_ids = sorted({TID_RE.match(d.name).group(1) for d in dumps})
insts = {i.instance_id: i for i in swebench_data.load_instances(dataset=None, instances=task_ids)}
true_map = {}
for tid, inst in insts.items():
    files = [f for f in re.findall(r"^\+\+\+ b/(.+)$", getattr(inst, "patch", "") or "", re.M) if not TESTRE.search(f)]
    files = [f for f in files if (DJ / f).exists()]
    if files:
        true_map[tid] = files

# ---- 2. mine the real queries the model fired (atelier grep regex) ----
GREP = re.compile(r"mcp__plugin_atelier_atelier__grep\] (\{.*?\})", re.S)
pairs = []  # (query, task)
for d in dumps:
    tid = TID_RE.match(d.name).group(1)
    if tid not in true_map:
        continue
    txt = d.read_text(errors="replace")
    for blob in GREP.findall(txt):
        m = re.search(r'"regex":\s*"((?:[^"\\]|\\.)*)"', blob)
        if not m:
            continue
        q = m.group(1).encode().decode("unicode_escape", "replace")
        if 3 <= len(q) <= 80:
            pairs.append((q, tid))

uniq = sorted({q for q, _ in pairs})
print(f"mined {len(pairs)} (query,task) pairs | {len(uniq)} unique queries | {len(true_map)} tasks", flush=True)


# ---- 3. run each system ONCE per unique query ----
def norm(p):
    return (p or "").replace("\\", "/")


def dedup(fs):
    seen = set()
    out = []
    for f in fs:
        f = norm(f)
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _tok(s):
    return max(0, len(s) // 4)  # ~4 chars/token proxy, consistent across systems

def explore_files(q):
    try:
        r = eng.tool_explore(q, max_files=10, auto_index=False)
        files = dedup([f.get("path", "") for f in r.get("files", [])])
        return files, _tok(json.dumps(r))
    except Exception:
        return [], 0

def search_files(q):
    # Cheap locator (symbols [+ semantic when Ollama is up]); apples-to-apples vs cg_query.
    try:
        rows = eng.search_symbols(q, limit=15, snippet="none", auto_index=False)
        locs = [{"name": r.symbol_name, "file": r.file_path, "line": r.start_line, "kind": r.kind} for r in rows]
        files = dedup([r.file_path for r in rows])[:10]
        return files, _tok(json.dumps(locs))
    except Exception:
        return [], 0

def cg_explore_files(q):
    try:
        out = subprocess.run(["node", str(CGBIN), "explore", q, "-p", str(DJ), "--max-files", "10"],
                             capture_output=True, text=True, timeout=60)
        files = dedup(re.findall(r"([A-Za-z0-9_./-]+\.py)", out.stdout))[:10]
        return files, _tok(out.stdout)
    except Exception:
        return [], 0

def cg_query_files(q):
    try:
        out = subprocess.run(["node", str(CGBIN), "query", q, "-p", str(DJ), "-j", "-l", "15"],
                             capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout)
        rows = data if isinstance(data, list) else []
        return dedup([(r.get("node") or {}).get("filePath", "") for r in rows]), _tok(out.stdout)
    except Exception:
        return [], 0


SYSTEMS = ["search", "explore", "cg_query", "cg_explore"]
cache = {}
toks = {}
for i, q in enumerate(uniq):
    sf, st = search_files(q)
    ef, et = explore_files(q)
    cf, ct = cg_explore_files(q)
    qf, qt = cg_query_files(q)
    cache[q] = {"search": sf, "explore": ef, "cg_explore": cf, "cg_query": qf}
    toks[q] = {"search": st, "explore": et, "cg_explore": ct, "cg_query": qt}
    if (i + 1) % 25 == 0:
        print(f"  ran {i + 1}/{len(uniq)} unique queries", flush=True)


# ---- 4. score per (query, task) ----
def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


score = {s: [0, 0, 0.0, 0] for s in SYSTEMS}  # hit1, hit3, rr, n
for q, tid in pairs:
    trues = true_map.get(tid)
    if not trues:
        continue
    for s in SYSTEMS:
        r = rank_true(cache[q][s], trues)
        score[s][3] += 1
        if r:
            score[s][2] += 1.0 / r
            if r == 1:
                score[s][0] += 1
            if r <= 3:
                score[s][1] += 1

avg_files = {s: sum(len(cache[q][s]) for q in uniq) / max(len(uniq), 1) for s in SYSTEMS}
avg_tok = {s: sum(toks[q][s] for q in uniq) / max(len(uniq), 1) for s in SYSTEMS}
print(f"\n{'system':14} {'hit@1':>8} {'hit@3':>8} {'MRR':>7} {'avg_files':>10} {'avg_tokens':>11} {'tok/hit@1':>10}")
print("-" * 78)
for s in sorted(SYSTEMS, key=lambda s: -score[s][2] / max(score[s][3], 1)):
    h1, h3, rr, n = score[s]
    tph = avg_tok[s] * len(uniq) / h1 if h1 else 0  # total tokens / hits-at-1
    print(f"{s:14} {h1}/{n:<6} {h3}/{n:<6} {rr / max(n, 1):6.3f} {avg_files[s]:10.1f} {avg_tok[s]:11.0f} {tph:10.0f}")
json.dump({"pairs": len(pairs), "unique": len(uniq), "score": score}, open("/tmp/bench_queries_result.json", "w"))
