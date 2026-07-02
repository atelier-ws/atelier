#!/usr/bin/env bash
# Pre-upload integrity gate: flag agent-phase references to Terminal-Bench
# solution sources in trial logs and ATIF trajectories.
#
# Why an audit and not a firewall: TB-2.1 tasks are network_mode=public and
# legitimately fetch from github.com / huggingface.co / povray.org etc. during
# the agent phase (e.g. mteb-leaderboard clones a GitHub repo), so hostname-
# level egress blocking -- container /etc/hosts, host iptables, or DNS -- cannot
# express the real policy ("GitHub minus the terminal-bench solutions repo").
# The compliant control is behavioral (web tools disabled, tbench.ai/harbor
# hosts-blocked in-container) plus this pre-upload audit, mirroring the
# leaderboard's own dynamic trajectory review.
#
#   bash benchmarks/harbor/audit_egress.sh <job-dir> [...]
# Exits 1 when any trial references a solution source -- review hits by hand
# before `harbor upload`.
set -u
[ $# -ge 1 ] || { echo "usage: $0 <job-dir> [...]"; exit 2; }
PAT='tbench\.ai|harborframework\.com|laude-institute|terminal[-_]bench'
fail=0
for dir in "$@"; do
  found=0
  while IFS= read -r f; do
    # Task files legitimately contain the TB canary string ("terminal-bench-canary
    # GUID ..."); only surviving, non-canary references need human review.
    ctx=$(grep -oEi ".{0,60}($PAT).{0,60}" "$f" 2>/dev/null | grep -vi 'canary' | head -5)
    if [ -n "$ctx" ]; then
      [ "$found" -eq 0 ] && echo "SOLUTION-SOURCE REFERENCES in $dir:"
      found=1; fail=1
      echo "  $f"
      printf '%s\n' "$ctx" | sed 's/^/    | /'
    fi
  done < <(grep -rEli "$PAT" "$dir" --include='claude-run.json' --include='trajectory.json' 2>/dev/null)
  [ "$found" -eq 0 ] && echo "clean: $dir"
done
exit "$fail"
