#!/usr/bin/env bash
# uninstall_gemini.sh - Remove Atelier from Gemini CLI
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
    GEMINI_DIR="${WORKSPACE}/.gemini"
    GEMINI_MD="${WORKSPACE}/GEMINI.md"
else
    GEMINI_DIR="${HOME}/.gemini"
    GEMINI_MD="${GEMINI_DIR}/GEMINI.md"
fi
SETTINGS="${GEMINI_DIR}/settings.json"
CMD_DIR="${GEMINI_DIR}/commands/atelier"

info()  { echo "[atelier:uninstall:gemini] $*"; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

if [ -f "$SETTINGS" ] && grep -q "atelier" "$SETTINGS" 2>/dev/null; then
    run "python3 -c '
import json
from pathlib import Path
path = Path(\"$SETTINGS\")
data = json.loads(path.read_text(encoding=\"utf-8\") or \"{}\")
data.get(\"mcpServers\", {}).pop(\"atelier\", None)
path.write_text(json.dumps(data, indent=2) + \"\\n\", encoding=\"utf-8\")
'"
    info "Removed atelier MCP entry from $SETTINGS"
fi

if [ -d "$CMD_DIR" ]; then
    run "rm -rf '$CMD_DIR'"
    info "Removed $CMD_DIR"
fi

if [ -f "$GEMINI_MD" ] && grep -q "atelier:code" "$GEMINI_MD" 2>/dev/null; then
    run "cp '$GEMINI_MD' '${GEMINI_MD}.atelier-backup.$(date +%Y%m%dT%H%M%S)'"
    run "python3 -c '
from pathlib import Path
path = Path(\"$GEMINI_MD\")
content = path.read_text(encoding=\"utf-8\")
marker = \"# Atelier\"
if marker in content:
    content = content[:content.find(marker)].rstrip()
path.write_text((content + \"\\n\") if content else \"\", encoding=\"utf-8\")
'"
    info "Removed Atelier persona from $GEMINI_MD"
fi

info "Done."
