"""Directly spawn the pylint zoekt-webserver and inspect /api/list + search."""

import json
import os
import subprocess
import time
import urllib.request

os.environ["FITNESS_LEAN"] = "1"
os.environ["ATELIER_ZOEKT_MODE"] = "auto"
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt import server as S
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
meta = DATA["repos"]["pylint-dev__pylint"]
eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
srv = get_zoekt_supervisor(eng.repo_root).server
print("repo_root:", eng.repo_root)
try:
    srv.ensure_started()
    print("ensure_started OK")
except Exception as e:  # noqa: BLE001
    print("ensure_started FAILED:", repr(e))
res = srv.resolution
idx = srv.index_root
shards = list(idx.glob("*.zoekt"))
print("index_root:", idx)
print("shards:", [(p.name, p.stat().st_size) for p in shards])
print("state_path:", srv.state_path, "exists:", srv.state_path.exists())

wb = S._resolve_webserver_binary(res)
port = S._pick_free_port()
proc = subprocess.Popen(
    [str(wb), "-listen", f"127.0.0.1:{port}", "-index", str(idx), "-rpc"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
url = f"http://127.0.0.1:{port}"
body = json.dumps({"Q": ""}).encode()
print("spawned pid", proc.pid)
for i in range(60):
    time.sleep(0.25)
    if proc.poll() is not None:
        print("PROC DIED rc=", proc.returncode, "out:", proc.stdout.read().decode()[:1500])
        break
    try:
        req = urllib.request.Request(
            f"{url}/api/list", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=2.0) as r:
            raw = r.read()
        hasrepo = S._list_has_loaded_repo(raw)
        if i % 4 == 0 or hasrepo:
            print(f"poll {i * 0.25:.1f}s: has_loaded_repo={hasrepo} raw={raw[:400]!r}")
        if hasrepo:
            # now run the regex search
            sb = json.dumps({"Q": "regexp_csv|bad.name.rgxs|_regexp_csv_transfomer|regex.*csv"}).encode()
            t = time.perf_counter()
            sreq = urllib.request.Request(
                f"{url}/api/search", data=sb, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(sreq, timeout=10.0) as r2:
                sraw = r2.read()
            print(f"SEARCH regex took {(time.perf_counter() - t) * 1000:.1f}ms bytes={len(sraw)}")
            break
    except Exception as e:  # noqa: BLE001
        if i % 8 == 0:
            print(f"poll {i * 0.25:.1f}s err {e!r}")
with __import__("contextlib").suppress(Exception):
    proc.terminate()
