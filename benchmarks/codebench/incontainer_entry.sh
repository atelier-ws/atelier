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

# Pin the workspace root so the live MCP server's code-index repo_id is
# deterministic and matches the index pre-built below. Without this the MCP
# server resolves its root from CLAUDE_WORKSPACE_ROOT/cwd, which can differ from
# the prewarm's --repo-root -> a different repo_id -> the MCP reads an EMPTY
# index -> grep returns nothing -> the agent wastes turns over-searching.
export ATELIER_WORKSPACE_ROOT="$REPO"

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

# Atelier arm: build the FULL code index BEFORE the timed agent run (setup, not
# graded). The live MCP server only READS this index -- it must never build on
# the tool-call path. A forced full rebuild (--reindex) avoids incremental-on-
# fresh edge cases; we then HARD-FAIL on an empty index so a broken build aborts
# the run (which --resume retries) instead of silently degrading: an empty index
# makes grep return nothing, and the agent burns turns falling back to shell.
if [ "$ARM" = "atelier" ]; then
  idx_json="$(atelier code index --repo-root "$REPO" --reindex --json 2>/tmp/atelier-index.log)"
  files_indexed="$(printf '%s' "$idx_json" | grep -o '"files_indexed"[^,}]*' | grep -o '[0-9][0-9]*' | head -1)"
  files_indexed="${files_indexed:-0}"
  if [ "$files_indexed" -gt 0 ] 2>/dev/null; then
    echo "atelier code index: prewarm OK ($files_indexed files)" >&2
  else
    echo "FATAL: atelier code index built 0 files for $REPO -- aborting so the run is retried instead of over-searching on an empty index." >&2
    tail -n 20 /tmp/atelier-index.log >&2 || true
    exit 4
  fi

  # Prewarm Zoekt trigram index. atelier code index already ran SCIP.
  # Zoekt's host-binary mode builds its index synchronously on first
  # ensure_started(); we trigger it here so the MCP server's first search
  # call returns results immediately instead of paying the build cost on the
  # tool-call path. Failure is non-fatal: search falls back to SQLite FTS5.
  if command -v zoekt-index >/dev/null 2>&1; then
    atelier zoekt up 2>/tmp/atelier-zoekt.log \
      && echo "atelier zoekt up: prewarm OK" >&2 \
      || { echo "[warn] atelier zoekt up failed -- falling back to FTS5" >&2; tail -n 5 /tmp/atelier-zoekt.log >&2 || true; }
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

# Hermetic benchmark, BOTH arms: deny web + agent-orchestration tools at the CLI,
# independent of persona config. WebSearch/WebFetch are server-side (run on
# Anthropic's infra), so the mitmproxy egress guard never sees them -- they are
# the answer-fetch contamination vector that an autonomous agent will otherwise
# use to pull a SWE-bench task's public gold PR. Denying here also removes the
# tool schemas from every request (token trim). Based on the harbor list
# (benchmarks/harbor/atelier_agent.py::_DISALLOWED_TOOLS), plus EnterPlanMode --
# a real tool as of claude 2.1.185, so denying ExitPlanMode alone still lets the
# agent enter plan mode and plan instead of execute. The flag is variadic, so it
# MUST stay last in args. Denying a tool an arm doesn't have is a harmless no-op
# (e.g. baseline has no mcp__* tools).
args+=(--disallowedTools AskUserQuestion EnterPlanMode ExitPlanMode WebFetch WebSearch mcp__atelier__web_fetch mcp__plugin_atelier_atelier__web_fetch Workflow ScheduleWakeup)

claude "${args[@]}"

echo "<<<CODEBENCH_DIFF_BEGIN>>>"
git -C "$REPO" add -A 2>/dev/null
git -C "$REPO" diff --cached HEAD
echo "<<<CODEBENCH_DIFF_END>>>"
