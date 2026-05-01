#!/usr/bin/env bash
# uninstall_claude.sh — Remove Atelier from Claude Code
#
# What it does:
#   1. Removes atelier MCP server entry from workspace .mcp.json
#   2. Removes atelier plugin (atelier@atelier)
#   3. Removes AGENTS.atelier.md if present
#
# Options:
#   --workspace DIR  Target workspace root (default: cwd)
#   --dry-run       Print what would happen, touch nothing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

DRY_RUN=false
WORKSPACE="${PWD}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true ;;
        --workspace) WORKSPACE="$2"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

WORKSPACE="$(cd "$WORKSPACE" && pwd)"

info()  { echo "[atelier:uninstall:claude] $*"; }
warn()  { echo "[atelier:uninstall:claude] WARN: $*" >&2; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

# Remove MCP server entry from .mcp.json
MCP_JSON="${WORKSPACE}/.mcp.json"
if [ -f "$MCP_JSON" ]; then
    # Remove atelier MCP server entry using python
    if command -v python3 &> /dev/null; then
        run "python3 -c '
import json
import sys
path = \"$MCP_JSON\"
try:
    with open(path, \"r\") as f:
        data = json.load(f)
    if \"mcpServers\" in data and \"atelier\" in data[\"mcpServers\"]:
        del data[\"mcpServers\"][\"atelier\"]
        with open(path, \"w\") as f:
            json.dump(data, f, indent=2)
        print(\"Removed atelier from .mcp.json\")
except Exception as e:
    print(f\"Warning: {e}\", file=sys.stderr)
'"
    else
        warn "python3 not found, skipping .mcp.json cleanup"
    fi
fi

# Remove AGENTS.atelier.md
AGENTS_FILE="${WORKSPACE}/AGENTS.atelier.md"
if [ -f "$AGENTS_FILE" ]; then
    run "rm -f '$AGENTS_FILE'"
    info "Removed AGENTS.atelier.md"
fi

# Note: Removing the Claude plugin requires claude CLI which may not be available
# The user can manually remove it via: claude plugin remove atelier@atelier
info "Done. If atelier plugin is installed in Claude Code, run: claude plugin remove atelier@atelier"