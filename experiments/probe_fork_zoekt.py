"""Reproduce the benchmark's fork path for zoekt: warm in parent, fork, search in child."""

import os
import sys
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

WS = "/tmp/idx_ws_astropy__astropy"
DB = Path("/tmp/idx_astropy__astropy.db")

eng = CodeContextEngine(Path(WS), db_path=DB, autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None
eng._schema_ready = True

# Parent warm (exactly like the harness prewarm)
srv = get_zoekt_supervisor(Path(WS)).server
warm = srv.wait_until_searchable(30.0)
print(
    f"[parent] warm={warm} ready={srv._webserver_ready.is_set()} failed={srv._webserver_failed} owner={srv._webserver_owner_pid} pid={os.getpid()} url={srv._webserver_url}"
)

q = "Quantity"


def do_search(tag):
    try:
        s = get_zoekt_supervisor(Path(WS)).server
        url = s._ensure_webserver()
        files = eng._zoekt_candidate_files(q, path=".", max_files=96)
        print(
            f"[{tag}] pid={os.getpid()} ready={s._webserver_ready.is_set()} failed={s._webserver_failed} owner={s._webserver_owner_pid} ensure_url={url!r} n_candidates={len(files)}",
            flush=True,
        )
    except Exception as e:
        print(f"[{tag}] pid={os.getpid()} EXC {type(e).__name__}: {e}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()


do_search("parent-before-fork")

pid = os.fork()
if pid == 0:
    # CHILD: replicate worker
    do_search("CHILD")
    os._exit(0)
else:
    os.waitpid(pid, 0)
    do_search("parent-after-fork")
