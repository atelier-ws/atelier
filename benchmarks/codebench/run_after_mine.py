"""Post-mine pipeline: wait for miner, run embedder sweep, run retrieval eval.

Usage:
    python3.14 benchmarks/codebench/run_after_mine.py --miner-pid 493902
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--miner-pid", type=int, required=True)
args = ap.parse_args()

ROOT = Path(__file__).parents[2]
HISTORY = ROOT / "reports/benchmark/embedder_mrr_history.jsonl"
GOLD = ROOT / "benchmarks/codebench/data/bench_pairs_semantic_gold.json"
CSV_OUT = ROOT / "reports/benchmark/retrieval_semantic_comparison.csv"


def _pairs() -> int:
    try:
        return json.load(open(GOLD)).get("n_total", 0)
    except Exception:  # broad catch: file missing / JSON error
        return 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


# ── 1. Wait for miner ────────────────────────────────────────────────────────
print(f"[pipeline] waiting for miner PID {args.miner_pid}...", flush=True)
while _alive(args.miner_pid):
    t = time.strftime("%H:%M")
    print(f"  [{t}] miner running — gold pairs so far: {_pairs()}", flush=True)
    time.sleep(120)
print(f"[pipeline] miner done. gold pairs: {_pairs()}", flush=True)


def _run(cmd: list[str], env: dict | None = None) -> None:
    e = dict(os.environ)
    if env:
        e.update(env)
    print(f"\n[pipeline] $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, env=e, check=True, cwd=ROOT)


# ── 2. Remaining embedder sweep ──────────────────────────────────────────────
# BGE, Nomic 3584d, Nomic 768d, SFR, Qwen 0.6B already done before the kill
_ALREADY_DONE = "BGE-Code-v1|Nomic-embed-code|SFR-Embedding-Code-400M|Qwen3-Embedding-0.6B"
_run(
    [
        sys.executable,
        "benchmarks/codebench/run_embedder_sweep.py",
        "--skip",
        _ALREADY_DONE,
    ]
)

# ── 3. Best embedder ─────────────────────────────────────────────────────────────
runs = [json.loads(ln) for ln in HISTORY.read_text().splitlines() if ln.strip()]


def _score(r: dict) -> float:
    golds = r.get("golds", {})
    vals = [g.get("mrr", 0) for g in golds.values() if isinstance(g, dict)]
    return sum(vals) / len(vals) if vals else 0.0


best_run = max(runs, key=_score)
best_emb = best_run.get("embedder", "")
extra_env: dict[str, str] = {}
if "bge" in best_emb:
    pin = "bge"
elif "nomic" in best_emb and "768" in best_emb:
    pin = "nomic"
    extra_env["ATELIER_NOMIC_DIM"] = "768"
elif "nomic" in best_emb:
    pin = "nomic"
elif "SFR" in best_emb or "Salesforce" in best_emb:
    pin = "hf"
    extra_env["ATELIER_CODE_EMBED_MODEL"] = "Salesforce/SFR-Embedding-Code-400M_R"
elif "Qwen" in best_emb:
    pin = "hf"
    model = "Qwen/Qwen3-Embedding-4B" if "4B" in best_emb else "Qwen/Qwen3-Embedding-0.6B"
    extra_env["ATELIER_CODE_EMBED_MODEL"] = model
elif "Jina" in best_emb or "jina" in best_emb:
    pin = "hf"
    extra_env["ATELIER_CODE_EMBED_MODEL"] = "jinaai/jina-embeddings-v3"
    extra_env["ATELIER_HF_QUERY_PREFIX"] = "Represent this sentence for searching relevant passages: "
elif "GTE" in best_emb or "gte" in best_emb:
    pin = "hf"
    extra_env["ATELIER_CODE_EMBED_MODEL"] = "Alibaba-NLP/gte-Qwen2-7B-instruct"
    extra_env["ATELIER_HF_QUERY_PREFIX"] = (
        "Instruct: Given a code search query, retrieve the most relevant code snippet.\nQuery: "
    )
else:
    pin = "nomic"  # safe default

print(f"\n[pipeline] best embedder: {best_emb}  (score={_score(best_run):.4f})  pin={pin}", flush=True)

# ── 4. Retrieval eval ─────────────────────────────────────────────────────────────
_run(
    [
        "uv",
        "run",
        "atelier",
        "eval",
        "retrieval",
        "--channel",
        "lexical+zoekt",
        "--channel",
        "lexical+zoekt+semantic",
        "--full",
        "--csv",
        str(CSV_OUT),
    ],
    env={"ATELIER_CODE_EMBEDDER": pin, **extra_env},
)

print(f"\n[pipeline] ✔ done. CSV: {CSV_OUT}", flush=True)
