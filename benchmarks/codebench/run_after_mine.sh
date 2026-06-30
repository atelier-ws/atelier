#!/usr/bin/env bash
# run_after_mine.sh — waits for the miner (PID $1), then:
#   1. Runs the remaining embedder sweep
#   2. Picks the best embedder by definition MRR
#   3. Runs eval retrieval side-by-side: lexical+zoekt vs lexical+zoekt+semantic
#
# Usage:
#   bash benchmarks/codebench/run_after_mine.sh 493902

set -euo pipefail
cd "$(dirname "$0")/../.."

MINER_PID="${1:-}"
if [[ -z "$MINER_PID" ]]; then
  echo "Usage: $0 <miner-pid>" >&2
  exit 1
fi

echo "[pipeline] Waiting for miner PID $MINER_PID to finish..."
while kill -0 "$MINER_PID" 2>/dev/null; do
  PAIRS=$(python3.14 -c "
import json, sys
try:
  d=json.load(open('benchmarks/codebench/data/bench_pairs_semantic_gold.json'))
  print(d.get('n_total',0))
except: print(0)
" 2>/dev/null)
  echo "  [$(date '+%H:%M')] miner running — gold pairs so far: $PAIRS"
  sleep 120
done
echo "[pipeline] Miner done."

# ── 1. Embedder sweep (skip already-done ones) ────────────────────────────
echo
echo "[pipeline] Running embedder sweep (remaining models)..."
python3.14 benchmarks/codebench/run_embedder_sweep.py \
  --skip "BGE-Code-v1\|Nomic-embed-code\|SFR-Embedding-Code-400M\|Qwen3-Embedding-0.6B"

# ── 2. Pick best embedder from history ───────────────────────────────────
echo
echo "[pipeline] Finding best embedder..."
BEST=$(python3.14 - <<'PYEOF'
import json
lines = [l for l in open('reports/benchmark/embedder_mrr_history.jsonl') if l.strip()]
runs = [json.loads(l) for l in lines]
# score = avg MRR across all gold kinds
def score(r):
    golds = r.get('golds', {})
    vals = [g.get('mrr', 0) for g in golds.values() if isinstance(g, dict)]
    return sum(vals) / len(vals) if vals else 0
best = max(runs, key=score)
pin = best.get('embedder', '')
# map embedder name to ATELIER_CODE_EMBEDDER pin
if 'bge' in pin: print('bge')
elif 'nomic' in pin and '768' in pin: print('nomic'); import os; os.environ['ATELIER_NOMIC_DIM']='768'
elif 'nomic' in pin: print('nomic')
else: print('hf')
PYEOF
)
echo "[pipeline] Best embedder pin: $BEST"

# ── 3. Retrieval eval: side-by-side comparison ───────────────────────────
echo
echo "[pipeline] Running retrieval eval: lexical+zoekt vs lexical+zoekt+semantic..."
ATELIER_CODE_EMBEDDER="$BEST" \
  uv run atelier eval retrieval \
    --channel lexical+zoekt \
    --channel lexical+zoekt+semantic \
    --full \
    --csv reports/benchmark/retrieval_semantic_comparison.csv

echo
echo "[pipeline] Done. CSV at reports/benchmark/retrieval_semantic_comparison.csv"
