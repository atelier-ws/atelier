#!/usr/bin/env bash
# uninstall_codex.sh - Remove Atelier from Codex CLI
#
# Options:
#   --workspace DIR  Remove project-local artifacts from DIR instead of global user config
#   --dry-run        Print what would happen, touch nothing

set -euo pipefail

DRY_RUN=false
WORKSPACE=""
WORKSPACE_SET=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --workspace)
            if [ $# -lt 2 ]; then
                echo "Missing value for --workspace" >&2
                exit 1
            fi
            WORKSPACE="$2"
            WORKSPACE_SET=true
            shift
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

if $WORKSPACE_SET; then
    WORKSPACE="$(cd "$WORKSPACE" && pwd)"
    CODEX_HOME="${WORKSPACE}/.codex"
    AGENTS_FILE="${WORKSPACE}/AGENTS.md"
    WRAPPER_FILE="${WORKSPACE}/bin/atelier-codex"
    TASKS_DIR="${WORKSPACE}/.codex/tasks"
    MCP_JSON="${WORKSPACE}/.codex/mcp.json"
else
    CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
    AGENTS_FILE="${CODEX_HOME}/AGENTS.md"
    WRAPPER_FILE="${HOME}/.local/bin/atelier-codex"
    TASKS_DIR=""
    MCP_JSON=""
fi

info()  { echo "[atelier:uninstall:codex] $*"; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

if $WORKSPACE_SET; then
    if [ -f "$MCP_JSON" ]; then
        run "python3 -c '
import json
from pathlib import Path
path = Path(\"$MCP_JSON\")
data = json.loads(path.read_text(encoding=\"utf-8\") or \"{}\")
servers = data.get(\"mcpServers\", {})
servers.pop(\"atelier\", None)
path.write_text(json.dumps(data, indent=2) + \"\\n\", encoding=\"utf-8\")
'"
        info "Removed atelier MCP entry from $MCP_JSON"
    fi
elif command -v codex &>/dev/null && codex mcp list 2>/dev/null | grep -q "^atelier "; then
    run "codex mcp remove atelier"
    info "Removed atelier MCP server via codex CLI"
fi

CODEX_SKILLS="${CODEX_HOME}/skills/atelier"
if [ -d "$CODEX_SKILLS" ]; then
    run "rm -rf '$CODEX_SKILLS'"
    info "Removed $CODEX_SKILLS"
fi

if [ -f "$AGENTS_FILE" ] && grep -q "atelier:code" "$AGENTS_FILE" 2>/dev/null; then
    run "rm -f '$AGENTS_FILE'"
    info "Removed $AGENTS_FILE"
fi

if [ -f "$WRAPPER_FILE" ]; then
    run "rm -f '$WRAPPER_FILE'"
    info "Removed $WRAPPER_FILE"
fi

if [ -n "$TASKS_DIR" ] && [ -d "$TASKS_DIR" ]; then
    run "rm -rf '$TASKS_DIR'"
    info "Removed $TASKS_DIR"
fi

info "Done."
