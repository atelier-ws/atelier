"""Compare zoekt CLI binary vs webserver result sets for django queries.

Hypothesis: the webserver /api/search with bare {"Q": q} under-fetches vs the
CLI `zoekt -jsonl`, dropping the gold file for hard queries (django recall gap).
"""

import json
import os
import random
import subprocess
import urllib.request

os.environ["FITNESS_LEAN"] = "1"
os.environ["ATELIER_ZOEKT_MODE"] = "auto"
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
meta = DATA["repos"]["django__django"]
true_map = DATA["true_map"]
pairs = [(q, tid) for q, tid, p in DATA["pairs"] if p == "django__django"]
random.Random(5).shuffle(pairs)

eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
srv = get_zoekt_supervisor(eng.repo_root).server
srv.ensure_started()
idx = srv.index_root
binpath = srv.resolution.path
print("binary:", binpath, "index:", idx)


def norm(p):
    return p.replace("\\", "/").lstrip("./").lower()


def gold_rank(files, trues):
    tn = [norm(t) for t in trues]
    for i, f in enumerate(files, 1):
        if any(norm(f).endswith(t) for t in tn):
            return i
    return None


def cli_files(q):
    cp = subprocess.run([str(binpath), "-index_dir", str(idx), "-jsonl", q], capture_output=True, text=True, timeout=10)
    out = []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        fn = d.get("FileName") or d.get("Path") or ""
        if fn:
            out.append(fn)
    return out


def ws_files(q):
    url = srv._webserver_url
    body = json.dumps({"Q": q}).encode()
    req = urllib.request.Request(
        f"{url}/api/search", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        payload = json.loads(r.read())
    files = ((payload.get("Result") or {}).get("Files")) or []
    return [str(f.get("FileName") or "") for f in files]


srv.wait_until_searchable(30.0)
print(f"{'cli_n':>6}{'ws_n':>6}{'cli_rk':>7}{'ws_rk':>7}  query")
cli_better = 0
samp = 0
for q, tid in pairs[:25]:
    trues = true_map.get(tid)
    if not trues:
        continue
    samp += 1
    try:
        cf = cli_files(q)
    except Exception:  # noqa: BLE001
        cf = []
    try:
        wf = ws_files(q)
    except Exception:  # noqa: BLE001
        wf = []
    crk = gold_rank(cf, trues)
    wrk = gold_rank(wf, trues)
    mark = ""
    if (crk or 999) < (wrk or 999):
        cli_better += 1
        mark = "  <-- CLI better"
    print(f"{len(cf):>6}{len(wf):>6}{crk!s:>7}{wrk!s:>7}  {q[:42]!r}{mark}")
print(f"\nCLI gold-rank better on {cli_better}/{samp} django queries")
