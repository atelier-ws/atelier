#!/usr/bin/env bash
# uninstall_codex.sh — Remove Atelier from Codex CLI
#
# What it does:
#   1. Removes .codex/mcp.json entry
#   2. Removes .codex/skills/atelier/ directory
#   3. Removes AGENTS.atelier.md
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

info()  { echo "[atelier:uninstall:codex] $*"; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

# Remove .codex/mcp.json entry
CODEX_MCP="${WORKSPACE}/.codex/mcp.json"
if [ -f "$CODEX_MCP" ]; then
    if command -v python3 &> /dev/null; then
        run "python3 -c '
import json
import sys
path = \"$CODEX_MCP\"
try:
    with open(path, \"r\") as f:
        data = json.load(f)
    if \"mcpServers\" in data and \"atelier\" in data[\"mcpServers\"]:
        del data[\"mcpServers\"][\"atelier\"]
        with open(path, \"w\") as f:
            json.dump(data, f, indent=2)
        print(\"Removed atelier from .codex/mcp.json\")
except Exception as e:
    print(f\"Warning: {e}\", file=sys.stderr)
'"
    else
        echo "[atelier:uninstall:codex] WARN: python3 not found, skipping .codex/mcp.json cleanup"
    fi
fi

# Remove .codex/skills/atelier/ directory
CODEX_SKILLS="${WORKSPACE}/.codex/skills/atelier"
if [ -d "$CODEX_SKILLS" ]; then
    run "rm -rf '$CODEX_SKILLS'"
    info "Removed .codex/skills/atelier/"
fi

# Remove AGENTS.atelier.md
AGENTS_FILE="${WORKSPACE}/AGENTS.atelier.md"
if [ -f "$AGENTS_FILE" ]; then
    run "rm -f '$AGENTS_FILE'"
    info "Removed AGENTS.atelier.md"
fi

info "Done."