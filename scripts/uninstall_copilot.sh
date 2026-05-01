#!/usr/bin/env bash
# uninstall_copilot.sh — Remove Atelier from VS Code Copilot
#
# What it does:
#   1. Removes atelier entry from .vscode/mcp.json
#   2. Removes atelier context from .github/copilot-instructions.md
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

info()  { echo "[atelier:uninstall:copilot] $*"; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

# Remove MCP server entry from .vscode/mcp.json
VSCODE_MCP="${WORKSPACE}/.vscode/mcp.json"
if [ -f "$VSCODE_MCP" ]; then
    if command -v python3 &> /dev/null; then
        run "python3 -c '
import json
import sys
path = \"$VSCODE_MCP\"
try:
    with open(path, \"r\") as f:
        data = json.load(f)
    if \"mcpServers\" in data and \"atelier\" in data[\"mcpServers\"]:
        del data[\"mcpServers\"][\"atelier\"]
        with open(path, \"w\") as f:
            json.dump(data, f, indent=2)
        print(\"Removed atelier from .vscode/mcp.json\")
except Exception as e:
    print(f\"Warning: {e}\", file=sys.stderr)
'"
    else
        echo "[atelier:uninstall:copilot] WARN: python3 not found, skipping .vscode/mcp.json cleanup"
    fi
fi

# Remove atelier context from .github/copilot-instructions.md
COPILOT_INSTR="${WORKSPACE}/.github/copilot-instructions.md"
if [ -f "$COPILOT_INSTR" ]; then
    # Check if it contains atelier content and remove it
    if grep -q "atelier" "$COPILOT_INSTR" 2>/dev/null; then
        # Remove the atelier section (between "<!-- atelier:" and "-->")
        run "python3 -c '
import re
path = \"$COPILOT_INSTR\"
try:
    with open(path, \"r\") as f:
        content = f.read()
    # Remove atelier comments and content
    new_content = re.sub(r\"<!--\s*atelier:[^-->]*-->\", \"\", content)
    new_content = re.sub(r\"<!--\s*atelier[\s\S]*?-->\", \"\", new_content)
    # Clean up extra blank lines
    new_content = re.sub(r\"\n{3,}\", \"\n\", new_content)
    with open(path, \"w\") as f:
        f.write(new_content.strip() + \"\n\")
    print(\"Removed atelier section from .github/copilot-instructions.md\")
except Exception as e:
    print(f\"Warning: {e}\", file=sys.stderr)
'"
    fi
fi

info "Done."