"""Run the full-set MRR ablation matrix; append each cell's result as it finishes.
Progress is pollable: completed cells -> /tmp/abl_res.txt, live progress -> /tmp/abl_prog.log
"""

import os
import subprocess
import time

ROOT = "/home/pankaj/Projects/leanchain/atelier"
HARNESS = "benchmarks/codebench/fitness_explore_mrr.py"
RES = "/tmp/abl_res.txt"
PROG = "/tmp/abl_prog.log"

CELLS = [
    ("1-baseline (A off, B off, zoekt off)", {"ABLATE_A": "1", "ABLATE_B": "1"}),
    ("2-A only (tokenization)", {"ABLATE_B": "1"}),
    ("3-B only (AND channel)", {"ABLATE_A": "1"}),
    ("4-A+B", {}),
    ("5-A+B + zoekt", {"PATH": os.environ["PATH"] + ":" + os.path.expanduser("~/go/bin")}),
]


def main() -> None:
    open(RES, "w").close()
    open(PROG, "w").close()
    t0 = time.perf_counter()
    for label, extra in CELLS:
        with open(PROG, "a") as p:
            p.write(f"\n===== {label} (elapsed {time.perf_counter() - t0:.0f}s) =====\n")
        # Single-worker: the pooled (thread/process) harness stalls ~120 explores in
        # (test-infra issue, not an engine slow path); single-worker runs clean.
        env = {**os.environ, "PYTHONPATH": "src:.", "FITNESS_WORKERS": "1", **extra}
        with open(PROG, "a") as p:
            out = subprocess.run(
                [".venv/bin/python3", HARNESS], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=p, text=True
            )
        with open(RES, "a") as f:
            f.write(f"{label}: {out.stdout.strip()}\n")
    with open(RES, "a") as f:
        f.write(f"DONE in {time.perf_counter() - t0:.0f}s\n")


if __name__ == "__main__":
    main()
