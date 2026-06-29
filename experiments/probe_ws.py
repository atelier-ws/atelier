import json
import logging
import time
import urllib.request

logging.basicConfig(level=logging.DEBUG)
from pathlib import Path

from atelier.infra.code_intel.zoekt import server as S
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

WS = Path("/home/pankaj/Projects/leanchain/atelier")
sup = get_zoekt_supervisor(WS)
srv = sup.server
print("runtime:", None if srv.resolution is None else srv.resolution.runtime)
srv.ensure_started()
res = srv.resolution
print("resolution.path:", None if res is None else res.path)
print("index_root:", srv.index_root, "exists:", srv.index_root.exists())
print(
    "shards:", [p.name for p in srv.index_root.glob("*.zoekt")][:5], "...n=", len(list(srv.index_root.glob("*.zoekt")))
)
try:
    wb = S._resolve_webserver_binary(res)
    print("webserver_binary:", wb, "exists:", wb.is_file())
except Exception as e:  # noqa: BLE001
    print("resolve_webserver_binary FAILED:", repr(e))
    wb = None

if wb is not None:
    port = S._pick_free_port()
    import subprocess

    proc = subprocess.Popen(
        [str(wb), "-listen", f"127.0.0.1:{port}", "-index", str(srv.index_root), "-rpc"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    url = f"http://127.0.0.1:{port}"
    print("spawned pid", proc.pid, "url", url)
    body = json.dumps({"Q": ""}).encode()
    ok = False
    for i in range(120):
        time.sleep(0.1)
        if proc.poll() is not None:
            print("PROC DIED rc=", proc.returncode)
            print("OUTPUT:", proc.stdout.read().decode()[:2000])
            break
        try:
            req = urllib.request.Request(
                f"{url}/api/list", data=body, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=1.0) as r:
                raw = r.read()
                hasrepo = S._list_has_loaded_repo(raw)
                if i % 10 == 0 or hasrepo:
                    print(f"poll {i}: status={r.status} has_loaded_repo={hasrepo} raw[:300]={raw[:300]!r}")
                if r.status == 200 and hasrepo:
                    ok = True
                    break
        except Exception as e:  # noqa: BLE001
            if i % 20 == 0:
                print(f"poll {i}: err {e!r}")
    print("READY:", ok, "after", (i + 1) * 0.1, "s")
    proc.terminate()
