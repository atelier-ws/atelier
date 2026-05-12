#!/usr/bin/env bash
# uninstall_codex.sh - Remove Atelier from Codex CLI
#
# Options:
#   --workspace DIR  Remove project-local artifacts from DIR instead of global user config
#   --dry-run        Print what would happen, touch nothing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/managed_context.sh"

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
    MARKETPLACE_JSON="${WORKSPACE}/.agents/plugins/marketplace.json"
    AGENTS_FILE="${WORKSPACE}/AGENTS.md"
    TASKS_DIR="${WORKSPACE}/.codex/tasks"
else
    CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
    MARKETPLACE_JSON="${HOME}/.agents/plugins/marketplace.json"
    AGENTS_FILE="${CODEX_HOME}/AGENTS.md"
    TASKS_DIR=""
fi

PLUGIN_DIR="${CODEX_HOME}/plugins/atelier"
PLUGIN_CACHE_DIR="${HOME}/.codex/plugins/cache/atelier"
AGENT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/integrations/codex/AGENTS.atelier.md"

info()  { echo "[atelier:uninstall:codex] $*"; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }

if [ -f "$MARKETPLACE_JSON" ]; then
    run "python3 -c '
import json
from pathlib import Path
path = Path(\"$MARKETPLACE_JSON\")
data = json.loads(path.read_text(encoding=\"utf-8\") or \"{}\")
plugins = [plugin for plugin in data.get(\"plugins\", []) if plugin.get(\"name\") != \"atelier\"]
if plugins:
    data[\"plugins\"] = plugins
    path.write_text(json.dumps(data, indent=2) + \"\\n\", encoding=\"utf-8\")
else:
    path.unlink()
'"
    info "Removed atelier marketplace entry from $MARKETPLACE_JSON"
fi

if [ -d "$PLUGIN_DIR" ]; then
    run "rm -rf '$PLUGIN_DIR'"
    info "Removed $PLUGIN_DIR"
fi

if [ -d "$PLUGIN_CACHE_DIR" ]; then
    run "rm -rf '$PLUGIN_CACHE_DIR'"
    info "Removed $PLUGIN_CACHE_DIR"
fi

if [ -f "$AGENTS_FILE" ]; then
    if $DRY_RUN; then
        if grep -q "$ATELIER_CODE_BLOCK_START" "$AGENTS_FILE" 2>/dev/null; then
            echo "  [dry-run] remove managed Atelier Codex instructions from $AGENTS_FILE"
        elif grep -q "atelier:code" "$AGENTS_FILE" 2>/dev/null; then
            echo "  [dry-run] inspect legacy Atelier Codex instructions in $AGENTS_FILE"
        fi
    else
        REMOVE_RESULT="$(atelier_remove_managed_block "$AGENTS_FILE" "false")"
        if [ "$REMOVE_RESULT" = "unchanged" ] && [ -f "$AGENTS_FILE" ]; then
            REMOVE_RESULT=$(python3 - <<PYEOF
from pathlib import Path

agents_path = Path("$AGENTS_FILE")
source_path = Path("$AGENT_SRC")
text = agents_path.read_text(encoding="utf-8")
source = source_path.read_text(encoding="utf-8").strip()

if text.strip() == source:
    agents_path.unlink()
    print("removed-legacy-exact")
elif "atelier:code" in text:
    print("legacy-unmanaged")
else:
    print("unchanged")
PYEOF
)
        fi
        case "$REMOVE_RESULT" in
            updated)
                info "Removed managed Atelier Codex instructions from $AGENTS_FILE"
                ;;
            removed|removed-legacy-exact)
                info "Removed $AGENTS_FILE"
                ;;
            legacy-unmanaged)
                info "Left legacy unmanaged Atelier Codex instructions in $AGENTS_FILE"
                info "Manual cleanup may be needed for pre-marker installs"
                ;;
        esac
    fi
fi

if [ -n "$TASKS_DIR" ] && [ -d "$TASKS_DIR" ]; then
    run "rm -rf '$TASKS_DIR'"
    info "Removed $TASKS_DIR"
fi

info "Done."
