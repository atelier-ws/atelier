"""Capture why the zoekt webserver fails for specific repos."""

import json
import os
import subprocess
import time
import urllib.request

os.environ["FITNESS_LEAN"] = "1"
os.environ.setdefault("ATELIER_ZOEKT_MODE", "auto")
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine
from atelier.infra.code_intel.zoekt import server as S
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor

DATA = json.load(open("benchmarks/codebench/data/bench_pairs_multi.json"))
repos = DATA["repos"]
TARGETS = ["astropy__astropy", "mwaskom__seaborn", "pytest-dev__pytest"]

for prefix in TARGETS:
    meta = repos[prefix]
    eng = CodeContextEngine(Path(meta["ws"]), db_path=Path(meta["db"]), autosync_enabled=False)
    srv = get_zoekt_supervisor(eng.repo_root).server
    try:
        srv.ensure_started()
    except Exception as e:  # noqa: BLE001
        print(prefix, "ensure_started FAILED:", repr(e))
        continue
    res = srv.resolution
    idx = srv.index_root
    shards = list(idx.glob("*.zoekt"))
    print(f"\n=== {prefix} ===")
    print(
        "index_root:", idx, "shards:", len(shards), "total_MB:", round(sum(p.stat().st_size for p in shards) / 1e6, 1)
    )
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
    ready_at = None
    t0 = time.time()
    for i in range(300):  # up to 30s
        time.sleep(0.1)
        if proc.poll() is not None:
            print("  PROC DIED rc=", proc.returncode, "after", round(time.time() - t0, 1), "s")
            print("  OUTPUT:", proc.stdout.read().decode()[:1500])
            break
        try:
            req = urllib.request.Request(
                f"{url}/api/list", data=body, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=1.0) as r:
                raw = r.read()
                if S._list_has_loaded_repo(raw):
                    ready_at = time.time() - t0
                    print(f"  READY at {ready_at:.1f}s (poll {i})")
                    break
        except Exception:  # noqa: BLE001
            pass
    if ready_at is None and proc.poll() is None:
        print("  NOT READY after 30s (still running). last /api/list:")
        try:
            req = urllib.request.Request(
                f"{url}/api/list", data=body, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=2.0) as r:
                print("   ", r.read()[:600])
        except Exception as e:  # noqa: BLE001
            print("    /api/list err:", repr(e))
    with __import__("contextlib").suppress(Exception):
        proc.terminate()
