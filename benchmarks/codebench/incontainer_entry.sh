#!/usr/bin/env bash
# In-container entrypoint for CodeBench Multi-SWE-bench runs (option A).
#
# Bind-mounted read-only at /mnt/run.sh. The agent edits the repo in place; the
# resulting git diff is emitted between the DIFF markers for the host to
# capture. claude's --output-format json receipt is printed before the markers.
#
# Inputs (env): CODEBENCH_ARM (baseline|atelier), CODEBENCH_MODEL,
# CODEBENCH_MAX_TURNS, CODEBENCH_AGENT (optional persona), CODEBENCH_REPO_DIR
# (optional; auto-discovered from the first .git dir otherwise).
set -uo pipefail

REPO="${CODEBENCH_REPO_DIR:-}"
if [ -z "$REPO" ]; then
  g="$(find / -maxdepth 6 -type d -name .git 2>/dev/null | head -1)"
  REPO="$(dirname "$g")"
fi
cd "$REPO" || { echo "no repo dir found" >&2; exit 3; }

ARM="${CODEBENCH_ARM:-baseline}"
MODEL="${CODEBENCH_MODEL:-sonnet}"

# Atelier arm: build the code index before the timed agent run (setup, not graded).
if [ "$ARM" = "atelier" ]; then
  atelier code index --repo-root "$REPO" >/tmp/atelier-index.log 2>&1 || true
fi

prompt="$(cat /mnt/prompt.txt)"
args=(-p "$prompt" --model "$MODEL" --output-format json --permission-mode bypassPermissions)
[ -n "${CODEBENCH_MAX_TURNS:-}" ] && args+=(--max-turns "$CODEBENCH_MAX_TURNS")
if [ "$ARM" = "atelier" ]; then
  args+=(--plugin-dir /mnt/plugin)
else
  args+=(--mcp-config '{"mcpServers":{}}' --strict-mcp-config)
fi
[ -n "${CODEBENCH_AGENT:-}" ] && args+=(--agent "$CODEBENCH_AGENT")

claude "${args[@]}"

echo "<<<CODEBENCH_DIFF_BEGIN>>>"
git -C "$REPO" add -A 2>/dev/null
git -C "$REPO" diff --cached HEAD
echo "<<<CODEBENCH_DIFF_END>>>"
