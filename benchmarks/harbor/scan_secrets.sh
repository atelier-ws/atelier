#!/usr/bin/env bash
# Pre-upload gate: fail if any credential value from benchmarks/harbor/.env (or
# a generic Anthropic token prefix) appears anywhere in a job directory. Run
# against every job dir BEFORE `harbor upload` -- uploaded jobs become public.
#   bash benchmarks/harbor/scan_secrets.sh benchmarks/jobs/final/rep1/<job> [...]
set -u
cd "$(dirname "$0")/../.."
[ $# -ge 1 ] || { echo "usage: $0 <job-dir> [...]"; exit 2; }
pats=$(mktemp)
trap 'rm -f "$pats"' EXIT
while IFS='=' read -r k v; do
  case "$k" in ''|\#*) continue ;; esac
  v="${v%\"}"; v="${v#\"}"
  [ "${#v}" -ge 16 ] && printf '%s\n' "$v" >> "$pats"
done < benchmarks/harbor/.env
printf 'sk-ant-\n' >> "$pats"
fail=0
for dir in "$@"; do
  hits=$(grep -rlFf "$pats" "$dir" 2>/dev/null)
  if [ -n "$hits" ]; then
    echo "SECRETS FOUND in $dir:"; echo "$hits"; fail=1
  else
    echo "clean: $dir"
  fi
done
exit "$fail"
