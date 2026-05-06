#!/usr/bin/env bash
# install_gemini.sh - Install Atelier into Gemini CLI
#
# What it does:
#   Global mode: installs Gemini user settings, commands, and persona.
#   Workspace mode (--workspace DIR): installs project-local Gemini artifacts under DIR.
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print config snippet for manual install, touch nothing
#   --workspace DIR  Install project-local artifacts into DIR instead of global user config
#   --strict       Exit nonzero if 'gemini' CLI not on PATH

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
ATELIER_WRAPPER="${ATELIER_REPO}/scripts/atelier_mcp_stdio.sh"

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
    GEMINI_DIR="${WORKSPACE}/.gemini"
    GEMINI_MD_DEST="${WORKSPACE}/GEMINI.md"
else
    INSTALL_SCOPE="global"
    GEMINI_DIR="${HOME}/.gemini"
    GEMINI_MD_DEST="${GEMINI_DIR}/GEMINI.md"
fi
SETTINGS="${GEMINI_DIR}/settings.json"
CMD_DEST="${GEMINI_DIR}/commands/atelier"

info()  { echo "[atelier:gemini] $*"; }
warn()  { echo "[atelier:gemini] WARN: $*" >&2; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }
backup_file() {
    local f="$1"
    if [ -f "$f" ]; then
        local bk="${f}.atelier-backup.$(date +%Y%m%dT%H%M%S)"
        run "cp '$f' '$bk'"
        info "backed up $f -> $bk"
    fi
}

if $WORKSPACE_SET; then
    NEW_ENTRY=$(cat <<JSON
{
  "mcpServers": {
    "atelier": {
      "command": "${ATELIER_WRAPPER}",
      "args": [],
      "env": {
        "ATELIER_WORKSPACE_ROOT": "${WORKSPACE}",
        "ATELIER_ROOT": "${WORKSPACE}/.atelier"
      }
    }
  }
}
JSON
)
else
    NEW_ENTRY=$(cat <<JSON
{
  "mcpServers": {
    "atelier": {
      "command": "${ATELIER_WRAPPER}",
      "args": []
    }
  }
}
JSON
)
fi

# ---- print-only mode --------------------------------------------------------
if $PRINT_ONLY; then
    echo ""
    echo "=== Atelier Gemini CLI - Manual Install ==="
    echo ""
    echo "Scope: ${INSTALL_SCOPE}"
    echo "Settings target: ${SETTINGS}"
    echo "Commands target: ${CMD_DEST}"
    echo "Persona target: ${GEMINI_MD_DEST}"
    echo ""
    echo "Merge/create settings:"
    echo "$NEW_ENTRY"
    echo ""
    echo "Note: Gemini CLI requires absolute command paths. The path above is resolved at install time."
    exit 0
fi

# ---- check CLI --------------------------------------------------------------
if ! command -v gemini &>/dev/null; then
    if $STRICT; then
        echo "[atelier:gemini] ERROR: 'gemini' CLI not found. Install from https://ai.google.dev/gemini-api/docs/gemini-cli" >&2
        exit 1
    fi
    warn "'gemini' CLI not found - SKIPPING."
    warn "Install Gemini CLI, then run: make install-gemini"
    exit 2
fi
info "Found Gemini CLI: $(gemini --version 2>/dev/null || echo 'version unknown')"

# ---- merge Gemini settings --------------------------------------------------
run "mkdir -p '$GEMINI_DIR'"

if [ -f "$SETTINGS" ]; then
    backup_file "$SETTINGS"
    if $DRY_RUN; then
        echo "  [dry-run] merge atelier into $SETTINGS"
    else
        python3 - <<PYEOF
import json
from pathlib import Path

path = Path('$SETTINGS')
existing = json.loads(path.read_text(encoding='utf-8') or '{}')
new_entry = json.loads('''$NEW_ENTRY''')
existing.setdefault('mcpServers', {}).update(new_entry['mcpServers'])
path.write_text(json.dumps(existing, indent=2) + '\n', encoding='utf-8')
print("[atelier:gemini] merged atelier entry into $SETTINGS")
PYEOF
    fi
else
    if $DRY_RUN; then
        echo "  [dry-run] create $SETTINGS"
    else
        echo "$NEW_ENTRY" > "$SETTINGS"
        info "created $SETTINGS"
    fi
fi

# ---- install custom slash commands -----------------------------------------
CMD_SRC="${ATELIER_REPO}/integrations/gemini/commands/atelier"
if [ -d "$CMD_SRC" ]; then
    info "Installing custom commands -> $CMD_DEST"
    run "mkdir -p '$CMD_DEST'"
    run "cp -f '$CMD_SRC'/*.toml '$CMD_DEST/'"
    info "commands installed: /atelier:status, /atelier:context"
else
    warn "Gemini commands source missing: $CMD_SRC"
fi

# ---- install GEMINI.md context ---------------------------------------------
GEMINI_MD_SRC="${ATELIER_REPO}/integrations/gemini/GEMINI.atelier.md"
if [ -f "$GEMINI_MD_SRC" ]; then
    run "mkdir -p '$(dirname "$GEMINI_MD_DEST")'"
    if [ ! -f "$GEMINI_MD_DEST" ]; then
        run "cp '$GEMINI_MD_SRC' '$GEMINI_MD_DEST'"
        info "created $GEMINI_MD_DEST"
    elif grep -q "atelier:code" "$GEMINI_MD_DEST" 2>/dev/null; then
        info "$GEMINI_MD_DEST already contains atelier persona - not overwriting"
    else
        backup_file "$GEMINI_MD_DEST"
        run "cat '$GEMINI_MD_SRC' >> '$GEMINI_MD_DEST'"
        info "appended atelier persona to $GEMINI_MD_DEST"
    fi
else
    warn "atelier persona source missing: $GEMINI_MD_SRC"
fi

if $DRY_RUN; then
    info "Dry run complete; skipped post-install verification because no files were written."
    exit 0
fi

# ---- post-install verification ---------------------------------------------
info "Running post-install verification..."
VFAIL=0
vpass() { info "PASS: $*"; }
vfail() { echo "[atelier:gemini] FAIL: $*" >&2; VFAIL=1; }

if [ ! -f "$SETTINGS" ]; then
    vfail "missing $SETTINGS"
else
    HAS=$(python3 - <<PYEOF
import json
try:
    d = json.load(open('$SETTINGS'))
    print('yes' if 'atelier' in d.get('mcpServers', {}) else 'no')
except Exception:
    print('parse-error')
PYEOF
)
    if [ "$HAS" = "yes" ]; then
        vpass "$SETTINGS contains atelier MCP entry"
    elif [ "$HAS" = "parse-error" ]; then
        vfail "$SETTINGS parse error"
    else
        vfail "$SETTINGS missing atelier MCP entry"
    fi

    WRAPPER=$(python3 - <<PYEOF
import json
try:
    d = json.load(open('$SETTINGS'))
    print(d.get('mcpServers', {}).get('atelier', {}).get('command', ''))
except Exception:
    print('')
PYEOF
)
    if [ -n "$WRAPPER" ] && [ -x "$WRAPPER" ]; then
        vpass "atelier wrapper command is executable: $WRAPPER"
    else
        vfail "atelier wrapper command missing or not executable in settings.json"
    fi
fi

if [ -d "$CMD_DEST" ] && [ -f "$CMD_DEST/status.toml" ] && [ -f "$CMD_DEST/context.toml" ]; then
    vpass "Gemini custom commands installed: $CMD_DEST"
else
    vfail "Gemini custom commands missing in $CMD_DEST"
fi

if [ -f "$GEMINI_MD_DEST" ] && grep -q "atelier:code" "$GEMINI_MD_DEST" 2>/dev/null; then
        vpass "GEMINI context installed: $GEMINI_MD_DEST"
else
    vfail "GEMINI context missing or no atelier:code persona: $GEMINI_MD_DEST"
fi

if [ "$VFAIL" -ne 0 ]; then
    echo "[atelier:gemini] ERROR: post-install verification failed." >&2
    exit 1
fi
info "All post-install checks passed"

info "Done. Restart Gemini CLI - /atelier:status, /atelier:context are available."
info "Note: Gemini CLI uses absolute paths - do not move atelier after installing."
info "Tip: run 'atelier-status' in any shell to see current run state."
