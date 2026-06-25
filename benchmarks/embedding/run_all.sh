#!/usr/bin/env bash
set -euo pipefail
cd /home/pankaj/Projects/leanchain/atelier
LOG="benchmarks/embedding/data/multi_repo/run_all.log"
> "$LOG"
exec > >(tee -a "$LOG") 2>&1

echo "[$(date)] === START ==="

# BGE for remaining 2 repos
for repo in scikit-learn xarray; do
  if [ -f "benchmarks/embedding/data/multi_repo/results_${repo}.json" ]; then
    echo "[$(date)] BGE $repo: already done"
  else
    echo "[$(date)] BGE $repo: starting..."
    python benchmarks/embedding/bench_multi_repo.py --skip-qwen "$repo"
    echo "[$(date)] BGE $repo: done"
  fi
done

# Qwen for all 6 repos
for repo in django pytest astropy sympy scikit-learn xarray; do
  if [ -f "benchmarks/embedding/data/multi_repo/results_${repo}.json" ]; then
    # Check if qwen results are already in the file
    if python3 -c "import json; r=json.load(open('benchmarks/embedding/data/multi_repo/results_${repo}.json')); print('qwen' in r)" | grep -q True; then
      echo "[$(date)] Qwen $repo: already done"
      continue
    fi
  fi
  echo "[$(date)] Qwen $repo: starting..."
  python benchmarks/embedding/bench_multi_repo.py "$repo"
  echo "[$(date)] Qwen $repo: done"
done

# Final summary
echo ""
echo "============= FINAL SUMMARY ============="
python3 -c "
import json, pathlib, statistics
OUT = pathlib.Path('benchmarks/embedding/data/multi_repo')
metrics = ['hit@1','hit@5','hit@10','mrr@10','ndcg@10']
repos = ['django','pytest','astropy','sympy','scikit-learn','xarray']
print(f'{\"Repo\":14s}{\"Model\":8s}{\"\".join(f\"{m:>9s}\" for m in metrics)}')
print('-' * 67)
bge_all = {m:[] for m in metrics}
qwen_all = {m:[] for m in metrics}
for r in repos:
    rp = OUT / f'results_{r}.json'
    if not rp.exists(): continue
    d = json.load(open(rp))
    if 'bge' in d:
        vals = ''.join(f\"{d['bge'][m]:>8.1%}\" for m in metrics)
        print(f'{r:14s}{\"BGE\":8s}{vals}')
        for m in metrics: bge_all[m].append(d['bge'][m])
    if 'qwen' in d and 'error' not in d['qwen']:
        vals = ''.join(f\"{d['qwen'][m]:>8.1%}\" for m in metrics)
        print(f'{r:14s}{\"Qwen\":8s}{vals}')
        for m in metrics: qwen_all[m].append(d['qwen'][m])
if bge_all['hit@1']:
    vals = ''.join(f'{statistics.mean(bge_all[m]):>8.1%}' for m in metrics)
    print(f'{\"─── AVG ───\":14s}{\"BGE\":8s}{vals}')
if qwen_all['hit@1']:
    vals = ''.join(f'{statistics.mean(qwen_all[m]):>8.1%}' for m in metrics)
    print(f'{\"─── AVG ───\":14s}{\"Qwen\":8s}{vals}')
"

echo "[$(date)] === ALL DONE ==="
