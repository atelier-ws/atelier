#!/usr/bin/env bash
# install_cursor.sh - Install Atelier into Cursor IDE
#
# What it does:
#   Global mode: adds atelier to ~/.cursor/mcp.json.
#   Workspace mode (--workspace DIR): adds atelier to DIR/.cursor/mcp.json
#   and writes a rules file at DIR/.cursor/rules/atelier.mdc.
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print config snippet for manual install, touch nothing
#   --workspace DIR  Install project-local artifacts into DIR instead of global user config
#   --strict       Exit nonzero if cursor CLI not on PATH (heuristic: ~/.cursor exists)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
source "${SCRIPT_DIR}/lib/managed_context.sh"

DRY_RUN=false
PRINT_ONLY=false
STRICT=false
WORKSPACE=""
WORKSPACE_SET=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=true ;;
        --print-only) PRINT_ONLY=true ;;
        --strict)     STRICT=true ;;
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
fi

if $WORKSPACE_SET; then
    INSTALL_SCOPE="workspace"
    MCP_FILE="${WORKSPACE}/.cursor/mcp.json"
    RULES_DIR="${WORKSPACE}/.cursor/rules"
    RULES_FILE="${RULES_DIR}/atelier.mdc"
else
    INSTALL_SCOPE="global"
    MCP_FILE="${HOME}/.cursor/mcp.json"
    RULES_DIR=""
    RULES_FILE=""
fi

info()  { [[ "${ATELIER_VERBOSE:-0}" == "1" ]] && echo "[atelier:cursor] $*" || true; }
warn()  { echo "[atelier:cursor] WARN: $*" >&2; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }
backup_file() {
    local f="$1"
    if $WORKSPACE_SET; then
        return
    fi
    if [ -f "$f" ]; then
        local bk="${f}.atelier-backup.$(date +%Y%m%dT%H%M%S)"
        run "cp '$f' '$bk'"
        info "backed up $f -> $bk"
    fi
}

MCP_ENTRY=$(cat <<JSON
{
  "mcpServers": {
    "atelier": {
      "type": "stdio",
      "command": "atelier-mcp",
      "args": ["--host", "cursor"]
    }
  }
}
JSON
)

# ---- print-only mode --------------------------------------------------------
if $PRINT_ONLY; then
    echo ""
    echo "=== Atelier Cursor - Manual Install ==="
    echo ""
    echo "Scope: ${INSTALL_SCOPE}"
    echo "MCP config target: ${MCP_FILE}"
    echo ""
    echo "Merge/create config:"
    echo "$MCP_ENTRY"
    if $WORKSPACE_SET; then
        echo ""
        echo "Create rules file at ${RULES_FILE}:"
        echo "---"
        echo "description: Atelier reasoning context usage guide — when to use which tool"
        echo "alwaysApply: true"
        echo "---"
        echo ""
        echo "Use Atelier's \`context\` tool at the start of every task to retrieve"
        echo "relevant reasoning blocks. After completing a task, record a trace"
        echo "with the \`trace\` tool. On repeated failures, use the \`rescue\` tool"
        echo "to get recovery hints."
    fi
    exit 0
fi

# ---- check cursor installation ----------------------------------------------
if [ ! -d "${HOME}/.cursor" ] && ! $WORKSPACE_SET && [ ! -f "$MCP_FILE" ]; then
    if $STRICT; then
        echo "[atelier:cursor] ERROR: ~/.cursor not found. Is Cursor installed?" >&2
        exit 1
    fi
    warn "~/.cursor not found - SKIPPING. Install Cursor from https://cursor.com"
    echo "=== SKIPPED (Cursor not detected) ==="
    exit 0
fi
info "Found Cursor config dir"

# ---- merge MCP config -------------------------------------------------------
run "mkdir -p '$(dirname "$MCP_FILE")'"

if [ -f "$MCP_FILE" ]; then
    backup_file "$MCP_FILE"
    if $DRY_RUN; then
        echo "  [dry-run] merge atelier into $MCP_FILE"
    else
        python3 - <<PYEOF
import json
from pathlib import Path

path = Path('$MCP_FILE')
content = path.read_text(encoding='utf-8').strip()
if content:
    existing = json.loads(content)
else:
    existing = {}
existing.setdefault('mcpServers', {}).update({
    'atelier': {
        'type': 'stdio',
        'command': 'atelier-mcp',
        'args': ['--host', 'cursor'],
    }
})
path.write_text(json.dumps(existing, indent=2) + '\n', encoding='utf-8')
print("[atelier:cursor] merged atelier entry into $MCP_FILE")
PYEOF
    fi
else
    if $DRY_RUN; then
        echo "  [dry-run] create $MCP_FILE"
    else
        echo "$MCP_ENTRY" > "$MCP_FILE"
        info "created $MCP_FILE"
    fi
fi

# ---- write rules file (workspace only) --------------------------------------
if $WORKSPACE_SET; then
    RULES_CONTENT=$(cat <<RULES
---
description: Atelier reasoning context usage guide — when to use which tool
alwaysApply: true
---

Use Atelier's \`context\` tool at the start of every task to retrieve relevant
reasoning blocks. After completing a task, record a trace with the \`trace\` tool.
On repeated failures, use the \`rescue\` tool to get recovery hints.
Prefer Atelier tools over native \`Read\`, \`Grep\`, and \`Bash\` for code insight.
RULES
)

    if $DRY_RUN; then
        echo "  [dry-run] create $RULES_FILE"
    else
        run "mkdir -p '$RULES_DIR'"
        echo "$RULES_CONTENT" > "$RULES_FILE"
        info "created $RULES_FILE"
    fi
fi

if $DRY_RUN; then
    info "Dry run complete; skipped post-install verification because no files were written."
    exit 0
fi

# ---- post-install verification ---------------------------------------------
info "Running post-install verification..."
VFAIL=0
vpass() { info "PASS: $*"; }
vfail() { echo "[atelier:cursor] FAIL: $*" >&2; VFAIL=1; }

if [ -f "$MCP_FILE" ]; then
    HAS=$(python3 - <<PYEOF
import json
from pathlib import Path
try:
    d = json.loads(Path('$MCP_FILE').read_text(encoding='utf-8'))
    print('yes' if 'atelier' in d.get('mcpServers', {}) else 'no')
except Exception:
    print('parse-error')
PYEOF
)
    if [ "$HAS" = "yes" ]; then
        vpass "Cursor MCP config contains atelier entry ($MCP_FILE)"
    elif [ "$HAS" = "parse-error" ]; then
        vfail "Cursor MCP config parse error: $MCP_FILE"
    else
        vfail "Cursor MCP config missing atelier entry"
    fi
else
    vfail "Cursor MCP config not found: $MCP_FILE"
fi

if $WORKSPACE_SET && [ -n "$RULES_FILE" ]; then
    if [ -f "$RULES_FILE" ]; then
        vpass "Cursor rules file created: $RULES_FILE"
    else
        vfail "Cursor rules file missing: $RULES_FILE"
    fi
fi

if command -v atelier-mcp &>/dev/null; then
    vpass "atelier-mcp is available on PATH"
else
    vfail "atelier-mcp NOT found on PATH"
fi

if [ "$VFAIL" -ne 0 ]; then
    echo "[atelier:cursor] ERROR: post-install verification failed." >&2
    exit 1
fi
info "All post-install checks passed"

info "Done. Restart Cursor for MCP changes to take effect."
info "Tip: run 'atelier status' in any shell to see the runs dashboard."
