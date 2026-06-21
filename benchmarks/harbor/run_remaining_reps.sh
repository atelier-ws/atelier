#!/usr/bin/env bash
# Drive the remaining TB-2.1 reps for the base-vs-Atelier comparison.
#
# Sequence (interleaved so each base/atelier PAIR completes together, giving an
# incrementally-complete comparison if interrupted):
#   base_rep1, rep2, base_rep2, rep3, base_rep3, rep4, base_rep4, rep5, base_rep5
# (Atelier rep1 already done at benchmarks/jobs/final/rep1.)
#
# IDEMPOTENT + RE-LAUNCHABLE: a rep already at 89/89 is skipped; a partially-done
# rep is resumed from its existing job dir. Safe to re-run after any interruption.
# Locked config: -n 9, agent-timeout-multiplier 6, model opus-4-8, root+IS_SANDBOX,
# two-subscription token pool (3 on _1 / 6 on _2). 'off' arm drops plugin+prewarm.
set -u
cd /home/pankaj/Projects/leanchain/atelier
set -a; . benchmarks/harbor/.env; set +a
LOG=/tmp/tb21_driver.log
MOUNTS='[{"type":"bind","source":"/home/pankaj/Projects/leanchain/atelier","target":"/atelier","read_only":true},{"type":"bind","source":"/tmp/avbuild/atelier-bundle.tar.gz","target":"/atelier-bundle.tar.gz","read_only":true}]'
AIP=benchmarks.harbor.atelier_agent:AtelierClaudeCodeHarborAgent

say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
cleanup(){
  docker ps --format '{{.ID}} {{.Names}}' | grep -E '__.*-(main|agent|tests)-' | awk '{print $1}' | xargs -r docker stop >/dev/null 2>&1
  docker network prune -f >/dev/null 2>&1
}
graded(){ find "$1" -name reward.txt 2>/dev/null | wc -l; }

run_rep(){
  local label="$1"; local extra="$2"
  local outdir="benchmarks/jobs/final/$label"
  local jd; jd=$(ls -dt "$outdir"/*/ 2>/dev/null | head -1)
  if [ -n "$jd" ] && [ "$(graded "$jd")" -ge 89 ]; then
    say "SKIP $label (already $(graded "$jd")/89 at $jd)"; return
  fi
  if [ -n "$jd" ] && [ -f "${jd}config.json" ]; then
    say "RESUME-existing $label at $jd ($(graded "$jd")/89)"
  else
    cleanup
    say "START $label fresh (extra='$extra')"
    set -a; . benchmarks/harbor/.env; set +a
    uv run --no-sync harbor run -d terminal-bench/terminal-bench-2-1 \
      --agent-import-path "$AIP" --mounts "$MOUNTS" \
      -k 1 -n 9 -r 2 --agent-timeout-multiplier 6 $extra \
      -o "$outdir" -y >>"$LOG" 2>&1
    jd=$(ls -dt "$outdir"/*/ 2>/dev/null | head -1)
  fi
  say "$label after-run graded=$(graded "$jd")/89 jd=$jd"
  local attempt=0
  while [ -n "$jd" ] && [ "$(graded "$jd")" -lt 89 ] && [ "$attempt" -lt 8 ]; do
    attempt=$((attempt+1))
    say "$label resume #$attempt (graded=$(graded "$jd")/89) -- sleeping 600s for rate window"
    sleep 600
    cleanup
    set -a; . benchmarks/harbor/.env; set +a
    uv run --no-sync harbor job resume -p "$jd" >>"$LOG" 2>&1 || true
  done
  say "DONE $label graded=$(graded "$jd")/89"
}

# Wait out the in-flight Atelier rep1 so cleanup never kills its last trials.
if kill -0 3872437 2>/dev/null; then
  say "waiting for Atelier rep1 (pid 3872437) to finish before starting..."
  while kill -0 3872437 2>/dev/null; do sleep 60; done
fi
say "=== driver start: 9 reps remaining ==="

REPS=(
  "base_rep1|--ak bench_mode=off"
  "rep2|"
  "base_rep2|--ak bench_mode=off"
  "rep3|"
  "base_rep3|--ak bench_mode=off"
  "rep4|"
  "base_rep4|--ak bench_mode=off"
  "rep5|"
  "base_rep5|--ak bench_mode=off"
)
for entry in "${REPS[@]}"; do
  label="${entry%%|*}"; extra="${entry#*|}"
  run_rep "$label" "$extra"
done
cleanup
say "=== ALL REMAINING REPS COMPLETE ==="
