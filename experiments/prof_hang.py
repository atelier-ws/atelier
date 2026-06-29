import cProfile
import io
import os
import pstats
import time

os.environ["FITNESS_LEAN"] = "1"
os.environ.setdefault("ATELIER_ZOEKT_MODE", "installed")
from pathlib import Path

from atelier.core.capabilities.code_context.engine import CodeContextEngine

WS = "/home/pankaj/Projects/leanchain/atelier"
DB = "/home/pankaj/.atelier/workspaces/Projects-leanchain-atelier/code_context.sqlite"
Q = "background process tracking pid session bash execution"

eng = CodeContextEngine(Path(WS), db_path=Path(DB), autosync_enabled=False)
eng._cache_get = lambda *a, **k: (False, None)
eng._cache_set = lambda *a, **k: None

# warm once (build index/connections), ignore timing
try:
    eng.tool_explore(Q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
except Exception as e:
    print("warm err", repr(e))

# timed, 3 runs
for i in range(3):
    t = time.perf_counter()
    r = eng.tool_explore(Q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
    dt = (time.perf_counter() - t) * 1000
    print(f"run{i}: {dt:.1f}ms  files={len(r.get('files', []))}")

# wait for zoekt webserver readiness, then re-time to prove webserver path is fast
sup = None
try:
    from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
    sup = get_zoekt_supervisor(eng.repo_root).server
except Exception as e:  # noqa: BLE001
    print("no supervisor accessor:", repr(e))
import time as _t

for _ in range(160):
    _t.sleep(0.1)
    ev = getattr(sup, "_webserver_ready", None) if sup is not None else None
    if ev is not None and ev.is_set():
        break
print(
    "webserver_ready:",
    None if sup is None else getattr(getattr(sup, "_webserver_ready", None), "is_set", lambda: "?")(),
)
print("webserver_failed:", None if sup is None else getattr(sup, "_webserver_failed", "?"))
for i in range(5):
    t = time.perf_counter()
    r = eng.tool_explore(Q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
    dt = (time.perf_counter() - t) * 1000
    print(f"post-ready run{i}: {dt:.1f}ms  files={len(r.get('files', []))}")

# profile one run
pr = cProfile.Profile()
pr.enable()
eng.tool_explore(Q, max_files=10, auto_index=False, include_source=False, include_relationships=False)
pr.disable()
s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(30)
print(s.getvalue())
