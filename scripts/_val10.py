"""10-task validation: Atelier channels vs CodeGraph, rank of gold true file.
One concept query per task. All offline. Shared django checkout + indexes."""

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

DJ = Path(open("/tmp/djroot.txt").read().strip())
DB = Path("/tmp/chanx_django.db")
CG = Path("/tmp/" + open("/tmp/cgdir.txt").read().strip())
CGBIN = CG / "dist/bin/codegraph.js"
TASKS = json.loads(Path("/tmp/tasks10.json").read_text())
K = 60

eng = CodeContextEngine(DJ, db_path=DB, autosync_enabled=False)
sup = get_zoekt_supervisor(DJ)
cent = eng.call_graph_centrality(limit=8000).get("symbols", [])
FILE_CENT = {}
for s in cent:
    fp = (s.get("file_path") or "").replace("\\", "/")
    if fp:
        FILE_CENT[fp] = max(FILE_CENT.get(fp, 0.0), float(s.get("eigenvector") or s.get("degree") or 0))


def norm(p):
    return (p or "").replace("\\", "/")


def dedup(files):
    seen = set()
    out = []
    for f in files:
        f = norm(f)
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def ch_ripgrep(q):
    try:
        out = subprocess.run(["rg", "-l", "-e", q, str(DJ / "django")], capture_output=True, text=True, timeout=30)
        return dedup([str(Path(x).resolve().relative_to(DJ)) for x in out.stdout.splitlines() if x.strip()])
    except Exception:
        return []


def ch_ripgrep_kw(q):
    toks = [
        t
        for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", q)
        if t.lower() not in {"with", "when", "that", "this", "description", "value", "used", "into", "from"}
    ]
    if not toks:
        return []
    return ch_ripgrep("|".join(toks[:5]))


def ch_symbol(q):
    try:
        return dedup([s.file_path for s in eng.search_symbols(q, limit=30, mode="lexical", auto_index=False)])
    except Exception:
        return []


def ch_zoekt(q):
    try:
        r = sup.search(query=q, search_path=DJ, max_files=30, max_chars_per_file=200, include_outline=False)
        return dedup([m.path for m in r.matches])
    except Exception:
        return []


def rrf(lists):
    sc = {}
    for lst in lists:
        for rank, f in enumerate(lst, 1):
            sc[f] = sc.get(f, 0.0) + 1.0 / (K + rank)
    return [f for f, _ in sorted(sc.items(), key=lambda kv: -kv[1])]


def shape_router_centrality(q):
    if " " in q:
        res = rrf([ch_symbol(q), ch_zoekt(q)])
    elif any(c in q for c in "|()[]\\.*+?"):
        res = ch_zoekt(q) or rrf([ch_symbol(q), ch_zoekt(q)])
    else:
        res = ch_symbol(q) or ch_zoekt(q)
    cand = dedup(res)
    return sorted(cand, key=lambda f: -FILE_CENT.get(f, 0.0))


def _cg_file(r):
    node = r.get("node") if isinstance(r, dict) else None
    if isinstance(node, dict):
        return node.get("filePath") or node.get("file") or ""
    return r.get("filePath") or r.get("file") or r.get("path") or ""

def cg_query(q):
    try:
        out = subprocess.run(["node", str(CGBIN), "query", q, "-p", str(DJ), "-j", "-l", "20"],
                             capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout)
        rows = data if isinstance(data, list) else data.get("results") or data.get("symbols") or []
        return dedup([_cg_file(r) for r in rows])
    except Exception:
        return []


def cg_explore(q):
    try:
        out = subprocess.run(
            ["node", str(CGBIN), "explore", q, "-p", str(DJ), "--max-files", "15"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        # parse file paths in order of appearance in the text output
        files = re.findall(r"([A-Za-z0-9_./-]+\.py)", out.stdout)
        return dedup(files)
    except Exception:
        return []


STOP = {"with", "when", "that", "this", "description", "value", "used", "into", "from", "crashes", "settings", "using", "following"}

def keywords(stmt):
    """Deterministic salient terms: CamelCase, snake_case, ALLCAPS, quoted."""
    toks = []
    for m in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stmt):
        if "_" in m or re.search(r"[a-z][A-Z]", m) or (m.isupper() and len(m) > 2):
            if m.lower() not in STOP and m not in toks:
                toks.append(m)
    if len(toks) < 2:  # fall back to longer plain words
        for m in re.findall(r"[A-Za-z]{5,}", stmt):
            if m.lower() not in STOP and m not in toks:
                toks.append(m)
    return toks[:5]

# (name, fn, query_form): nl=sentence, kw=space-joined keywords, rx=regex alternation
SYSTEMS = [
    ("atelier_ripgrep", ch_ripgrep, "rx"),
    ("atelier_symbol", ch_symbol, "kw"),
    ("atelier_zoekt", ch_zoekt, "rx"),
    ("atelier_shape+cent", shape_router_centrality, "kw"),
    ("codegraph_query", cg_query, "kw"),
    ("codegraph_explore", cg_explore, "nl"),
]

def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None

score = {name: [0, 0, 0.0] for name, _, _ in SYSTEMS}
per_task = []
for t in TASKS:
    nl = t["query"]; trues = t["true_files"]
    kw_toks = keywords(t["query"]) or keywords(nl)
    kw = " ".join(kw_toks) or nl
    rx = "|".join(re.escape(x) for x in kw_toks) or re.escape(nl.split()[0])
    forms = {"nl": nl, "kw": kw, "rx": rx}
    row = {"task": t["task"].split("__")[-1], "kw": kw[:30]}
    for name, fn, qf in SYSTEMS:
        r = rank_true(fn(forms[qf]), trues)
        row[name] = r or "-"
        if r:
            score[name][2] += 1.0 / r
            if r == 1: score[name][0] += 1
            if r <= 3: score[name][1] += 1
    per_task.append(row)

n = len(TASKS)
print(f"\n{'system':22} {'qform':>6} {'hit@1':>6} {'hit@3':>6} {'MRR':>6}")
print("-" * 52)
qform = {s[0]: s[2] for s in SYSTEMS}
for name, _, qf in sorted(SYSTEMS, key=lambda s: -score[s[0]][2]):
    h1, h3, rr = score[name]
    print(f"{name:22} {qf:>6} {h1}/{n:<4} {h3}/{n:<4} {rr/n:6.3f}")
print("\n=== per-task rank of true file ===")
print("task".ljust(15) + "".join(s[0].split('_')[-1][:8].rjust(9) for s in SYSTEMS) + "  keywords")
for row in per_task:
    print(row["task"].ljust(15) + "".join(str(row[s[0]]).rjust(9) for s in SYSTEMS) + "  " + row["kw"])
