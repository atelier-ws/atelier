"""Fresh, same-corpus baseline: atelier explore vs cg_explore vs cg_query over
the multi-repo mined pairs. Atelier uses cache-stubbed engines (honest current
code); cg shells out per query, routed to each repo's .codegraph. One-time."""

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


def atelier_explore(prefix, q):
    try:
        r = engines[prefix].tool_explore(q, max_files=10, auto_index=False)
        return dedup([f.get("path", "") for f in r.get("files", [])])[:10]
    except Exception:  # noqa: BLE001 - best-effort script
        return []


def cg_explore(prefix, q):
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


def cg_query(prefix, q):
    try:
        out = subprocess.run(
            ["node", CG, "query", q, "-p", repos[prefix]["ws"], "-j", "-l", "15"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        rows = json.loads(out.stdout)
        rows = rows if isinstance(rows, list) else []
        return dedup([(r.get("node") or {}).get("filePath", "") for r in rows])[:10]
    except Exception:  # noqa: BLE001 - best-effort script
        return []


SYS = {"atelier_explore": atelier_explore, "cg_explore": cg_explore, "cg_query": cg_query}
uq = {}
for q, _t, prefix in pairs:
    uq.setdefault(prefix, set()).add(q)
filecache = {s: {} for s in SYS}
for prefix, qs in uq.items():
    for q in qs:
        for s, fn in SYS.items():
            filecache[s][(prefix, q)] = fn(prefix, q)


def rank_true(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


overall = {s: {"rr": 0.0, "h1": 0, "h3": 0, "n": 0} for s in SYS}
agg = {s: {} for s in SYS}
for q, tid, prefix in pairs:
    trues = true_map.get(tid)
    if not trues:
        continue
    for s in SYS:
        r = rank_true(filecache[s][(prefix, q)], trues)
        br = agg[s].setdefault(prefix, {"rr": 0.0, "h1": 0, "h3": 0, "n": 0})
        for x in (overall[s], br):
            x["n"] += 1
            if r:
                x["rr"] += 1.0 / r
                if r == 1:
                    x["h1"] += 1
                if r <= 3:
                    x["h3"] += 1


def mrr(d):
    return d["rr"] / max(d["n"], 1)


print(f"\n{'system':16}{'MRR':>8}{'hit@1':>8}{'hit@3':>8}{'n':>6}")
print("-" * 46)
for s in sorted(SYS, key=lambda s: -mrr(overall[s])):
    d = overall[s]
    print(f"{s:16}{mrr(d):8.3f}{d['h1'] / max(d['n'], 1):8.3f}{d['h3'] / max(d['n'], 1):8.3f}{d['n']:6}")
print("\nby repo (MRR):")
print(f"{'repo':28}" + "".join(f"{s:>16}" for s in SYS))
for prefix in sorted(repos):
    print(f"{prefix:28}" + "".join(f"{mrr(agg[s].get(prefix, {'rr': 0, 'n': 1})):16.3f}" for s in SYS))

json.dump(
    {
        "overall": {s: {"mrr": mrr(overall[s]), "n": overall[s]["n"]} for s in SYS},
        "by_repo": {p: {s: mrr(agg[s].get(p, {"rr": 0, "n": 1})) for s in SYS} for p in repos},
    },
    open("/tmp/baseline_compare.json", "w"),
)
print("\nwrote /tmp/baseline_compare.json")
