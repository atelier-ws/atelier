#!/usr/bin/env python3
"""Chained benchmark sequencer -- runs three benchmarks back to back so they
never contend for CPU / API rate limits:

  Phase 0: wait for the running cg_full reps=5 run (pid CG_PID) to finish
  Phase 1: SWE-bench Verified curated-12, 3 reps, baseline + atelier (=atelier:auto)
  Phase 2: cg_full again, 3 reps, baseline + auto (=atelier:auto), judged

Each phase runs to completion before the next starts. The sequencer's own
progress goes to stdout (redirect it to a log at launch); each phase streams its
full output to its own log under reports/benchmark/codebench/.

Scratch/ops script -- safe to delete once the chain has finished.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import subprocess
import time

ROOT = "/home/pankaj/Projects/leanchain/atelier"
os.chdir(ROOT)

# The cg_full reps=5 run we wait on (Phase 0). Watched by pid so we never race a
# recycled pid: only counts as alive while the pid is STILL that cg run.
CG_PID = 2630189

REPORTS = pathlib.Path("reports/benchmark/codebench")
REPORTS.mkdir(parents=True, exist_ok=True)
DATA = pathlib.Path("benchmarks/codebench/data/verified.txt")


def cg_running() -> bool:
    try:
        cmd = pathlib.Path(f"/proc/{CG_PID}/cmdline").read_bytes().decode("utf-8", "replace")
    except FileNotFoundError:
        return False
    return "benchmarks.codebench.run" in cmd


def stamp() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%H:%M:%SZ")


def ts() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def run_phase(name: str, cmd: list[str], log: pathlib.Path) -> int:
    print(f"[seq {stamp()}] >>> {name} starting -> log={log}", flush=True)
    with open(log, "w") as lf:
        rc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT).returncode
    print(f"[seq {stamp()}] <<< {name} exited rc={rc}  log={log}", flush=True)
    return rc


# --- Phase 0: wait for the in-flight cg_full reps=5 -------------------------
print(f"[seq {stamp()}] waiting for cg_full pid {CG_PID} to finish...", flush=True)
while cg_running():
    time.sleep(60)
print(f"[seq {stamp()}] cg_full reps=5 finished", flush=True)

ids = DATA.read_text().split()
print(f"[seq {stamp()}] curated instances ({len(ids)}): {' '.join(ids)}", flush=True)

# --- Phase 1: SWE-bench curated-12 (atelier arm -> atelier:auto) ------------
swe_ts = ts()
swe_out = str((REPORTS / f"swe12_{swe_ts}").resolve())  # absolute: docker -v needs it
swe_log = REPORTS / f"swe12_{swe_ts}.log"
(REPORTS / "_swe_current_out.txt").write_text(swe_out + "\n")
(REPORTS / "_swe_current_log.txt").write_text(str(swe_log) + "\n")
swe_cmd = [
    "uv",
    "run",
    "--project",
    "benchmarks",
    "python",
    "-m",
    "benchmarks.codebench.multiswe_run",
    "--suite",
    "swe-bench-verified",
    "--instances",
    *ids,
    "-a",
    "baseline",
    "atelier",
    "--reps",
    "3",
    "--model",
    "claude-opus-4-8",
    "--jobs",
    "2",
    "--out",
    swe_out,
]
run_phase("SWE-bench curated-12 (3 reps, baseline + atelier:auto)", swe_cmd, swe_log)

# --- Phase 2: cg_full again with the autonomous arm ------------------------
cg_ts = ts()
cg_out = str((REPORTS / f"cg_full_auto_{cg_ts}").resolve())
cg_log = REPORTS / f"cg_full_auto_{cg_ts}.log"
(REPORTS / "_cg_auto_current_out.txt").write_text(cg_out + "\n")
(REPORTS / "_cg_auto_current_log.txt").write_text(str(cg_log) + "\n")
cg_cmd = [
    "uv",
    "run",
    "python",
    "-m",
    "benchmarks.codebench.run",
    "all",
    "--reps",
    "3",
    "-a",
    "baseline",
    "auto",
    "--model",
    "claude-sonnet-4-6",
    "--judge",
    "--jobs",
    "2",
    "--timeout",
    "1800",
    "--out",
    cg_out,
]
run_phase("cg_full (3 reps, baseline + auto)", cg_cmd, cg_log)

print(f"[seq {stamp()}] ALL PHASES DONE. swe_out={swe_out} cg_out={cg_out}", flush=True)
