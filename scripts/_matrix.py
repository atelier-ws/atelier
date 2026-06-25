"""Full wiring x ranking matrix on django-13449 flail queries. Offline, no API.
Channels: ripgrep, symbol-index (SQLite FTS), zoekt (trigram). Semantic parked.
Metric: rank of the TRUE file (db/models/expressions.py) per strategy."""

import os
import subprocess
import sys
from pathlib import Path

os.environ["PATH"] = os.path.expanduser("~/go/bin") + os.pathsep + os.environ.get("PATH", "")
sys.path.insert(0, "src")
from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

DJ = Path(open("/tmp/djroot.txt").read().strip())
DB = Path("/tmp/chanx_django.db")
TRUE = "db/models/expressions.py"
FLOOD = 8
K = 60  # RRF constant

eng = CodeContextEngine(DJ, db_path=DB, autosync_enabled=False)
if not DB.exists():
    eng.index_repo()
sup = get_zoekt_supervisor(DJ)
print("zoekt health:", sup.health().ok, "| semantic:", eng._semantic_ranker.available, flush=True)

# ---- centrality scores (symbol -> score), aggregated to file ----
cent = eng.call_graph_centrality(limit=5000).get("symbols", [])
FILE_CENT: dict[str, float] = {}
for s in cent:
    fp = (s.get("file_path") or "").replace("\\", "/")
    sc = float(s.get("eigenvector") or s.get("degree") or 0)
    if fp:
        FILE_CENT[fp] = max(FILE_CENT.get(fp, 0.0), sc)


def norm(p: str) -> str:
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


# ---------------- CHANNELS: query -> ordered list of files ----------------
def ch_ripgrep(q):
    try:
        out = subprocess.run(["rg", "-l", "-e", q, str(DJ / "django")], capture_output=True, text=True, timeout=30)
        files = [str(Path(l).resolve().relative_to(DJ)) for l in out.stdout.splitlines() if l.strip()]
        return dedup(files)
    except Exception:
        return []


def ch_symbol(q):
    try:
        syms = eng.search_symbols(q, limit=30, mode="lexical", auto_index=False)
        return dedup([s.file_path for s in syms])
    except Exception:
        return []


def ch_zoekt(q):
    try:
        r = sup.search(query=q, search_path=DJ, max_files=30, max_chars_per_file=200, include_outline=False)
        return dedup([m.path for m in r.matches])
    except Exception:
        return []


# ---------------- RANKING: fuse channel rankings ----------------
def rrf(channel_lists):
    score = {}
    for lst in channel_lists:
        for rank, f in enumerate(lst, 1):
            score[f] = score.get(f, 0.0) + 1.0 / (K + rank)
    return [f for f, _ in sorted(score.items(), key=lambda kv: -kv[1])]


def centrality(channel_lists):
    cand = dedup([f for lst in channel_lists for f in lst])
    return sorted(cand, key=lambda f: -FILE_CENT.get(f, 0.0))


# ---------------- WIRING strategies: query -> final ranked files ----------------
IDENT = lambda q: q.replace("_", "").isalnum() and " " not in q
REGEX = lambda q: any(c in q for c in "|()[]\\.*+?^$")


def w_ripgrep_only(q, rank):
    return ch_ripgrep(q)


def w_symbol_only(q, rank):
    return ch_symbol(q)


def w_zoekt_only(q, rank):
    return ch_zoekt(q)


def w_escalate(q, rank):
    rg = ch_ripgrep(q)
    if len(rg) == 0 or len(rg) > FLOOD:
        return rank([ch_symbol(q), ch_zoekt(q)])
    return rg


def w_shape(q, rank):
    if " " in q:  # phrase -> symbol + zoekt
        res = rank([ch_symbol(q), ch_zoekt(q)])
    elif REGEX(q):  # regex -> zoekt first
        res = ch_zoekt(q) or rank([ch_symbol(q), ch_zoekt(q)])
    elif IDENT(q):  # identifier -> symbol first
        res = ch_symbol(q) or ch_zoekt(q)
    else:
        res = rank([ch_symbol(q), ch_zoekt(q)])
    if len(res) == 0 or len(res) > FLOOD * 3:
        res = rank([ch_symbol(q), ch_zoekt(q)])
    return res


def w_always_fused(q, rank):
    return rank([ch_ripgrep(q), ch_symbol(q), ch_zoekt(q)])


SINGLE = [("ripgrep_only", w_ripgrep_only), ("symbol_only", w_symbol_only), ("zoekt_only", w_zoekt_only)]
FUSED = [("escalate", w_escalate), ("shape_router", w_shape), ("always_fused", w_always_fused)]
RANKERS = [("rrf", rrf), ("centrality", centrality)]

QUERIES = [
    "select_format",
    "as_sqlite",
    "SQLiteNumericMixin",
    "NUMERIC",
    "select_format|CAST",
    "NUMERIC|cast_data_types|CAST",
    "CAST\\(%s AS NUMERIC",
    "def as_sqlite",
    "sqlite cast decimal to numeric",
    "cast value as numeric for sqlite",
    "window function decimal sqlite",
]


def rank_true(files):
    for i, f in enumerate(files, 1):
        if norm(f).endswith(TRUE):
            return i
    return None


def evaluate(strategy):
    h1 = h3 = 0
    rr = 0.0
    flood = 0
    for q in QUERIES:
        files = strategy(q)
        r = rank_true(files)
        flood += len(files)
        if r:
            rr += 1.0 / r
            if r == 1:
                h1 += 1
            if r <= 3:
                h3 += 1
    n = len(QUERIES)
    return h1, h3, rr / n, flood / n


print(f"\n{'strategy':28} {'hit@1':>6} {'hit@3':>6} {'MRR':>6} {'avg_results':>11}")
print("-" * 62)
rows = []
for name, fn in SINGLE:
    h1, h3, mrr, fl = evaluate(lambda q, fn=fn: fn(q, None))
    rows.append((mrr, f"{name} (native)", h1, h3, mrr, fl))
for wname, wfn in FUSED:
    for rname, rfn in RANKERS:
        h1, h3, mrr, fl = evaluate(lambda q, wfn=wfn, rfn=rfn: wfn(q, rfn))
        rows.append((mrr, f"{wname} + {rname}", h1, h3, mrr, fl))
n = len(QUERIES)
for _, label, h1, h3, mrr, fl in sorted(rows, reverse=True):
    print(f"{label:28} {h1}/{n:<4} {h3}/{n:<4} {mrr:6.3f} {fl:11.1f}")
print(f"\nqueries={n}  true_file={TRUE}  flood_threshold={FLOOD}")
