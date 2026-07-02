"""Differential: where does cg_explore beat atelier explore, and why? Samples
pairs, compares gold-file rank, and flags whether the gold file's NAME/DIR
contains a query token (the path-relevance lever) and whether atelier missed on
recall vs ranking."""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine

try:
    from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
except Exception:  # noqa: BLE001 - best-effort script
    get_zoekt_supervisor = None

CG = "/tmp/" + open("/tmp/cgdir.txt").read().strip() + "/dist/bin/codegraph.js"
data = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
pairs, true_map, repos = data["pairs"], data["true_map"], data["repos"]
PER_REPO = 14


def norm(p):
    return (p or "").replace("\\", "/")


def dedup(fs):
    seen, out = set(), []
    for f in fs:
        f = norm(f)
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def qtokens(q):
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", q)
    return {t for t in re.split(r"[^A-Za-z0-9]+", parts.lower()) if len(t) >= 3}


engines = {}
for prefix, meta in repos.items():
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    eng._cache_get = lambda *a, **k: (False, None)
    eng._cache_set = lambda *a, **k: None
    if get_zoekt_supervisor is not None:
        try:
            get_zoekt_supervisor(Path(meta["ws"]))
        except Exception:  # noqa: BLE001 - best-effort script
            pass
    engines[prefix] = eng


def atelier_files(prefix, q, n):
    try:
        r = engines[prefix].tool_explore(q, max_files=n, auto_index=False)
        return dedup([f.get("path", "") for f in r.get("files", [])])[:n]
    except Exception:  # noqa: BLE001 - best-effort script
        return []


def cg_files(prefix, q):
    try:
        out = subprocess.run(
            ["node", CG, "explore", q, "-p", repos[prefix]["ws"], "--max-files", "10"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return dedup(re.findall(r"([A-Za-z0-9_./-]+\.py)", out.stdout))[:10]
    except Exception:  # noqa: BLE001 - best-effort script
        return []


def rank(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


seen_repo = {}
sample = []
for q, tid, prefix in pairs:
    if seen_repo.get(prefix, 0) >= PER_REPO:
        continue
    if tid not in true_map:
        continue
    seen_repo[prefix] = seen_repo.get(prefix, 0) + 1
    sample.append((q, tid, prefix))

cg_wins = at_wins = ties = 0
cg_only = at_only = neither = both = 0
cg_win_pathtoken = 0
at_recall_miss_but_pathtoken = 0
examples = []
for q, tid, prefix in sample:
    trues = true_map[tid]
    af = atelier_files(prefix, q, 30)
    cf = cg_files(prefix, q)
    ar = rank(af[:10], trues)
    cr = rank(cf, trues)
    ar30 = rank(af, trues)
    # path-token opportunity: gold file name/dir contains a query token
    qt = qtokens(q)
    gold_path_token = any((qt & qtokens(Path(t).stem)) or (qt & qtokens(str(Path(t).parent))) for t in trues)
    if ar and cr:
        both += 1
    elif ar:
        at_only += 1
    elif cr:
        cg_only += 1
    else:
        neither += 1
    a = ar or 999
    c = cr or 999
    if c < a:
        cg_wins += 1
        if gold_path_token:
            cg_win_pathtoken += 1
        if not ar30 and gold_path_token:
            at_recall_miss_but_pathtoken += 1
        if len(examples) < 6:
            examples.append(
                (prefix, q, [Path(t).name for t in trues], af[:3], cf[:3], ar, cr, gold_path_token, bool(ar30))
            )
    elif a < c:
        at_wins += 1
    else:
        ties += 1

n = len(sample)
print(f"\nsample={n}  cg_wins={cg_wins}  atelier_wins={at_wins}  ties={ties}")
print(f"top10 hit: both={both} cg_only={cg_only} atelier_only={at_only} neither={neither}")
print(f"cg_wins where gold NAME/DIR contains a query token: {cg_win_pathtoken}/{cg_wins}")
print(
    f"cg_wins that are atelier RECALL misses (gold not in atelier top30) yet path-token present: {at_recall_miss_but_pathtoken}"
)
print("\nexamples (prefix | query | gold | atelier_top3 | cg_top3 | a_rank c_rank pathtok at_recall):")
for prefix, q, gold, a3, c3, ar, cr, pt, rec in examples:
    print(f"\n[{prefix}] q={q!r}")
    print(f"  gold={gold}  a_rank={ar} c_rank={cr} pathtoken={pt} atelier_recalled={rec}")
    print(f"  atelier_top3={a3}")
    print(f"  cg_top3={c3}")
