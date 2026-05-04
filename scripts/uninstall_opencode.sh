#!/usr/bin/env bash
# uninstall_opencode.sh — Remove Atelier from opencode
#
# What it does:
#   1. Removes opencode MCP config entry for atelier
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

info()  { echo "[atelier:uninstall:opencode] $*"; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

# Check common opencode MCP config locations
OPENCODE_MCP=""
for loc in "$WORKSPACE/.opencode/mcp.json" "$HOME/.opencode/mcp.json"; do
    if [ -f "$loc" ]; then
        OPENCODE_MCP="$loc"
        break
    fi
done

if [ -n "$OPENCODE_MCP" ] && [ -f "$OPENCODE_MCP" ]; then
    if command -v python3 &> /dev/null; then
        run "python3 -c '
import json
import sys
path = \"$OPENCODE_MCP\"
try:
    with open(path, \"r\") as f:
        data = json.load(f)
    modified = False
    if \"mcpServers\" in data and \"atelier\" in data[\"mcpServers\"]:
        del data[\"mcpServers\"][\"atelier\"]
        modified = True
    if modified:
        with open(path, \"w\") as f:
            json.dump(data, f, indent=2)
        print(\"Removed atelier from opencode mcp config\")
except Exception as e:
    print(f\"Warning: {e}\", file=sys.stderr)
'"
    else
        echo "[atelier:uninstall:opencode] WARN: python3 not found, skipping opencode mcp cleanup"
    fi
else
    info "No opencode MCP config found, skipping."
fi

# Also clean up opencode.jsonc in workspace root
OPENCODE_JSONC="${WORKSPACE}/opencode.jsonc"
if [ -f "$OPENCODE_JSONC" ] && grep -q "atelier" "$OPENCODE_JSONC" 2>/dev/null; then
    info "Removing atelier from $OPENCODE_JSONC..."
    # Backup first
    run "cp '$OPENCODE_JSONC' '${OPENCODE_JSONC}.atelier-backup.$(date +%Y%m%dT%H%M%S)'"
    # Simple approach: remove the entire file and let install recreate it
    run "rm -f '$OPENCODE_JSONC'"
    info "Removed opencode.jsonc (will be recreated on install)"
fi

# Remove .opencode/agents/atelier.md if exists
if [ -f "${WORKSPACE}/.opencode/agents/atelier.md" ]; then
    run "rm -f '${WORKSPACE}/.opencode/agents/atelier.md'"
    info "Removed .opencode/agents/atelier.md"
fi

info "Done."