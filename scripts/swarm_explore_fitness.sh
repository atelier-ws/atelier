#!/usr/bin/env bash
# Fitness command for explore-ranking swarm.
# Outputs benchmark cost_usd as a float; exits 1 if the task wasn't solved correctly.
# Run from the worktree root.
set -euo pipefail

# Swarm worktrees don't share git-ignored .env files from the main repo.
# Symlink them in so the benchmark container gets the right credentials.
MAIN_REPO="/home/pankaj/Projects/leanchain/atelier"
for rel in benchmarks/codebench/.env benchmarks/.env .env; do
    src="$MAIN_REPO/$rel"
    dst="$(pwd)/$rel"
    if [ -f "$src" ] && [ ! -e "$dst" ]; then
        ln -sf "$src" "$dst"
    fi
done

OUTDIR=$(mktemp -d /tmp/swarm_bench_XXXXXX)
trap 'rm -rf "$OUTDIR"' EXIT

CODEBENCH_CODE_EMBEDDER=null CODEBENCH_MAX_REQUESTS=150 \
  uv run --with swebench python -m benchmarks.codebench.multiswe_run \
  --suite swe-bench-verified \
  --instances django__django-12155 \
  -a atelier --reps 1 --model claude-opus-4-8 \
  --out "$OUTDIR" \
  2>"/tmp/swarm_bench_$$.log"

# results.jsonl has cost_usd and correct fields
RESULT=$(cat "$OUTDIR/results.jsonl")
COST=$(echo "$RESULT" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(f'{d[\"cost_usd\"]:.4f}')")
CORRECT=$(echo "$RESULT" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d[\"correct\"])")

echo "$COST"
[[ "$CORRECT" == "True" ]] || exit 1
