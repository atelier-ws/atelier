#!/usr/bin/env bash
# uninstall_gemini.sh — Remove Atelier from Gemini CLI
#
# What it does:
#   1. Removes atelier entry from .gemini/settings.json
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

info()  { echo "[atelier:uninstall:gemini] $*"; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

# Check common gemini settings locations
GEMINI_SETTINGS=""
for loc in "$WORKSPACE/.gemini/settings.json" "$HOME/.gemini/settings.json"; do
    if [ -f "$loc" ]; then
        GEMINI_SETTINGS="$loc"
        break
    fi
done

if [ -n "$GEMINI_SETTINGS" ] && [ -f "$GEMINI_SETTINGS" ]; then
    if command -v python3 &> /dev/null; then
        run "python3 -c '
import json
import sys
path = \"$GEMINI_SETTINGS\"
try:
    with open(path, \"r\") as f:
        data = json.load(f)
    modified = False
    # Check for mcpServers
    if \"mcpServers\" in data and \"atelier\" in data[\"mcpServers\"]:
        del data[\"mcpServers\"][\"atelier\"]
        modified = True
    # Check for tools or other possible locations
    if \"tools\" in data and isinstance(data[\"tools\"], list):
        data[\"tools\"] = [t for t in data[\"tools\"] if t != \"atelier\"]
        modified = True
    if modified:
        with open(path, \"w\") as f:
            json.dump(data, f, indent=2)
        print(\"Removed atelier from .gemini/settings.json\")
except Exception as e:
    print(f\"Warning: {e}\", file=sys.stderr)
'"
    else
        echo "[atelier:uninstall:gemini] WARN: python3 not found, skipping .gemini/settings.json cleanup"
    fi
else
    info "No .gemini/settings.json found, skipping."
fi

info "Done."