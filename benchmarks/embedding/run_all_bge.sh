#!/usr/bin/env bash
# Run BGE benchmark sequentially on all 6 repos
# Usage: bash run_all_bge.sh

set -e
cd /home/pankaj/Projects/leanchain/atelier
LOG="benchmarks/embedding/data/multi_repo/run_log.txt"
> "$LOG"

for repo in django pytest astropy sympy scikit-learn xarray; do
  echo "[$(date)] === $repo ===" | tee -a "$LOG"
  python benchmarks/embedding/bench_multi_repo.py --skip-qwen "$repo" 2>&1 | tee -a "$LOG"
  echo "[$(date)] === $repo done ===" | tee -a "$LOG"
done

echo "[$(date)] ALL DONE" | tee -a "$LOG"
