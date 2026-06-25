"""cg-index the 5 newly-provisioned repo checkouts (django already cg-indexed)."""

import glob
import subprocess
import time

CG = "/tmp/" + open("/tmp/cgdir.txt").read().strip() + "/dist/bin/codegraph.js"
print(f"[cg] using {CG}", flush=True)
for ws in sorted(glob.glob("/tmp/idx_ws_*/")):
    print(f"[cg] init+index {ws}", flush=True)
    subprocess.run(["node", CG, "init", ws, "--force"], capture_output=True, timeout=300)
    t0 = time.time()
    r = subprocess.run(["node", CG, "index", ws], capture_output=True, text=True, timeout=1800)
    if r.returncode == 0:
        print(f"[cg] indexed {ws} in {time.time() - t0:.0f}s", flush=True)
    else:
        print(f"[cg] FAILED {ws}: {(r.stderr or '')[-200:]}", flush=True)
print("[cg] ALL DONE", flush=True)
