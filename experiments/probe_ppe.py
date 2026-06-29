"""Replicate the benchmark's ProcessPoolExecutor+fork zoekt path with explicit
error capture, to see why _zoekt_candidate_files returns [] in workers."""

import concurrent.futures as cf
import json
import os
import traceback
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

ROOT = "/home/pankaj/Projects/leanchain/atelier"
d = json.load(open(f"{ROOT}/benchmarks/codebench/data/bench_pairs_multi.json"))
repos = d["repos"]
PFX = next(x for x in repos if "astropy" in x)
WS = Path(repos[PFX]["ws"])
DB = Path(repos[PFX]["db"]) if repos[PFX].get("db") else None

eng = CodeContextEngine(WS, db_path=DB, autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
eng._schema_ready = True

# Parent warm (like harness)
get_zoekt_supervisor(WS)
srv = get_zoekt_supervisor(WS).server
print("[parent] warm:", srv.wait_until_searchable(30.0), "ready:", srv._webserver_ready.is_set())


def _winit():
    import concurrent.futures as c

    import atelier.core.capabilities.code_context.engine as m

    m._SEARCH_CHANNEL_EXECUTOR.shutdown(wait=False)
    m._SEARCH_CHANNEL_EXECUTOR = c.ThreadPoolExecutor(max_workers=16)


def _task(q):
    sup = get_zoekt_supervisor(eng.repo_root)
    s = sup.server
    info = {
        "pid": os.getpid(),
        "ready": s._webserver_ready.is_set(),
        "failed": s._webserver_failed,
        "owner": s._webserver_owner_pid,
        "url": s._webserver_url,
    }
    try:
        info["should_route"] = sup.should_route(eng._resolve_inside_repo("."))
    except Exception as e:
        info["should_route_EXC"] = repr(e)
    try:
        res = sup.search(
            query=q,
            search_path=eng._resolve_inside_repo("."),
            max_files=10,
            max_chars_per_file=800,
            include_outline=False,
            _include_index_age=False,
        )
        info["search_n"] = len(res.matches)
    except Exception:
        info["search_EXC"] = traceback.format_exc().splitlines()[-3:]
    info["zcf_n"] = len(eng._zoekt_candidate_files(q, max_files=10))
    return info


with cf.ProcessPoolExecutor(max_workers=1, initializer=_winit) as ex:
    for q in ["Quantity", "def test_cds", "Unit"]:
        print(q, "->", ex.submit(_task, q).result())
