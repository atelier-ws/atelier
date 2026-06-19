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

# Activate the project's conda env (SWE-bench images ship a `testbed` env) for
# BOTH arms so shells run the project interpreter. Claude Code's Bash sources
# .bashrc (env active); the Atelier shell tool's `bash -c` subprocesses do NOT
# source .bashrc -- but non-interactive bash reads $BASH_ENV before running a
# -c command. So we (a) activate in this entry shell, which `claude` and the
# Atelier MCP server inherit, and (b) point $BASH_ENV at an activation snippet
# so every Atelier `bash -c` re-activates even if inheritance is lost. Without
# this the atelier arm burns turns rediscovering the interpreter. Identical for
# both arms keeps the comparison fair and matches production, where claude is
# launched from the user's already-activated shell.
_act=/tmp/codebench_activate.sh
: >"$_act"
for _cs in /opt/miniconda3/etc/profile.d/conda.sh /opt/conda/etc/profile.d/conda.sh; do
  if [ -f "$_cs" ]; then
    # Snippet is idempotent and cheap: re-activation is skipped once active.
    printf '[ "$CONDA_DEFAULT_ENV" = testbed ] || { . %s; conda activate testbed 2>/dev/null || true; }\n' "$_cs" >"$_act"
    . "$_cs"; conda activate testbed 2>/dev/null || true
    break
  fi
done
export BASH_ENV="$_act"

ARM="${CODEBENCH_ARM:-baseline}"
MODEL="${CODEBENCH_MODEL:-sonnet}"

# Atelier arm: build the code index before the timed agent run (setup, not graded).
# A failed/missing prewarm means the timed run pays a cold index build, so surface
# it on stderr instead of being silently slow.
if [ "$ARM" = "atelier" ]; then
  if atelier code index --repo-root "$REPO" >/tmp/atelier-index.log 2>&1; then
    echo "atelier code index: prewarm OK" >&2
  else
    echo "WARNING: atelier code index prewarm FAILED; timed run will pay cold-index cost:" >&2
    tail -n 5 /tmp/atelier-index.log >&2 || true
  fi
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
