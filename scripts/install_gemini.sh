#!/usr/bin/env bash
# install_gemini.sh — Install Atelier into Gemini CLI
#
# What it does:
#   Merges atelier MCP entry into ~/.gemini/settings.json
#   Uses absolute paths (required by Gemini CLI)
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print config snippet for manual install, touch nothing
#   --workspace DIR  Workspace root for ATELIER_WORKSPACE_ROOT (default: cwd)
#   --strict       Exit nonzero if 'gemini' CLI not on PATH

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
ATELIER_WRAPPER="${ATELIER_REPO}/scripts/atelier_mcp_stdio.sh"

DRY_RUN=false
PRINT_ONLY=false
STRICT=false
WORKSPACE="${PWD}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=true ;;
        --print-only) PRINT_ONLY=true ;;
        --strict)     STRICT=true ;;
        --workspace)  WORKSPACE="$2"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

WORKSPACE="$(cd "$WORKSPACE" && pwd)"

info()  { echo "[atelier:gemini] $*"; }
warn()  { echo "[atelier:gemini] WARN: $*" >&2; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }
backup_file() {
    local f="$1"
    if [ -f "$f" ]; then
        local bk="${f}.atelier-backup.$(date +%Y%m%dT%H%M%S)"
        run "cp '$f' '$bk'"
        info "backed up $f → $bk"
    fi
}

# ---- check CLI --------------------------------------------------------------
if ! command -v gemini &>/dev/null; then
    if $STRICT; then
        echo "[atelier:gemini] ERROR: 'gemini' CLI not found. Install from https://ai.google.dev/gemini-api/docs/gemini-cli" >&2
        exit 1
    fi
    warn "'gemini' CLI not found — SKIPPING."
    warn "Install Gemini CLI: npm install -g @google/generative-ai then run: make install-gemini"
    exit 2
fi
info "Found Gemini CLI: $(gemini --version 2>/dev/null || echo 'version unknown')"

# ---- print-only mode --------------------------------------------------------
if $PRINT_ONLY; then
    echo ""
    echo "=== Atelier Gemini CLI — Manual Install ==="
    echo ""
    echo "Merge into ~/.gemini/settings.json:"
    cat <<JSON
{
  "mcpServers": {
    "atelier": {
      "command": "${ATELIER_WRAPPER}",
      "args": [],
      "env": {
        "ATELIER_WORKSPACE_ROOT": "${WORKSPACE}",
        "ATELIER_STORE_ROOT": "${WORKSPACE}/.atelier"
      }
    }
  }
}
JSON
    echo ""
    echo "Note: Gemini CLI requires absolute paths. The paths above are resolved at install time."
    exit 0
fi

# ---- merge ~/.gemini/settings.json ------------------------------------------
GEMINI_DIR="${HOME}/.gemini"
SETTINGS="${GEMINI_DIR}/settings.json"
NEW_ENTRY=$(cat <<JSON
{
  "mcpServers": {
    "atelier": {
      "command": "${ATELIER_WRAPPER}",
      "args": [],
      "env": {
        "ATELIER_WORKSPACE_ROOT": "${WORKSPACE}",
        "ATELIER_STORE_ROOT": "${WORKSPACE}/.atelier"
      }
    }
  }
}
JSON
)

run "mkdir -p '$GEMINI_DIR'"

if [ -f "$SETTINGS" ]; then
    backup_file "$SETTINGS"
    if $DRY_RUN; then
        echo "  [dry-run] merge atelier into $SETTINGS"
    else
        python3 - <<PYEOF
import json
with open('$SETTINGS') as f:
    existing = json.load(f)
new_entry = json.loads('''$NEW_ENTRY''')
existing.setdefault("mcpServers", {}).update(new_entry["mcpServers"])
with open('$SETTINGS', 'w') as f:
    json.dump(existing, f, indent=2)
    f.write('\n')
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
CMD_DEST="${GEMINI_DIR}/commands/atelier"
if [ -d "$CMD_SRC" ]; then
    info "Installing custom commands → $CMD_DEST"
    run "mkdir -p '$CMD_DEST'"
    run "cp -f '$CMD_SRC'/*.toml '$CMD_DEST/'"
    info "commands installed: /atelier:status, /atelier:context"
fi

# ---- install GEMINI.md context (atelier persona) ----------------------------
# Atelier persona is agent-specific configuration, not project configuration.
# Install it to ~/.gemini/GEMINI.md (global context) so it applies to all
# Gemini CLI sessions for this user, without polluting the project repo.
GEMINI_MD_SRC="${ATELIER_REPO}/integrations/gemini/GEMINI.atelier.md"
GLOBAL_GEMINI_MD="${HOME}/.gemini/GEMINI.md"

mkdir -p "${HOME}/.gemini"

if [ -f "$GEMINI_MD_SRC" ]; then
    if [ ! -f "$GLOBAL_GEMINI_MD" ]; then
        run "cp '$GEMINI_MD_SRC' '$GLOBAL_GEMINI_MD'"
        info "created $GLOBAL_GEMINI_MD (atelier persona — global context)"
    else
        # Check if atelier persona is already present
        if grep -q "atelier:code" "$GLOBAL_GEMINI_MD" 2>/dev/null; then
            info "$GLOBAL_GEMINI_MD already contains atelier persona — not overwriting"
        else
            run "cat '$GEMINI_MD_SRC' >> '$GLOBAL_GEMINI_MD'"
            info "appended atelier persona to $GLOBAL_GEMINI_MD"
        fi
    fi
else
    warn "atelier persona source missing: $GEMINI_MD_SRC"
fi

# ── Post-install verification (replaces verify_gemini.sh) ──
info "Running post-install verification..."
VFAIL=0
vpass() { info "PASS: $*"; }
vfail() { echo "[atelier:gemini] FAIL: $*" >&2; VFAIL=1; }

SETTINGS_FILE="${HOME}/.gemini/settings.json"
if [ ! -f "$SETTINGS_FILE" ]; then
    vfail "missing ${SETTINGS_FILE}"
else
    HAS=$(python3 - <<PYEOF
import json
try:
    d = json.load(open('$SETTINGS_FILE'))
    print('yes' if 'atelier' in d.get('mcpServers', {}) else 'no')
except Exception:
    print('parse-error')
PYEOF
)
    if [ "$HAS" = "yes" ]; then
        vpass "settings.json contains atelier MCP entry"
    elif [ "$HAS" = "parse-error" ]; then
        vfail "settings.json parse error: $SETTINGS_FILE"
    else
        vfail "settings.json missing atelier MCP entry"
    fi

    WRAPPER=$(python3 - <<PYEOF
import json
try:
    d = json.load(open('$SETTINGS_FILE'))
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

CMD_DIR="${HOME}/.gemini/commands/atelier"
if [ -d "$CMD_DIR" ] && [ -f "$CMD_DIR/status.toml" ] && [ -f "$CMD_DIR/context.toml" ]; then
    vpass "Gemini custom commands installed: $CMD_DIR"
else
    vfail "Gemini custom commands missing in $CMD_DIR"
fi

GEMINI_MD="${HOME}/.gemini/GEMINI.md"
if [ -f "$GEMINI_MD" ] && grep -q "atelier:code" "$GEMINI_MD" 2>/dev/null; then
    vpass "global GEMINI context installed: $GEMINI_MD (contains atelier:code persona)"
else
    vfail "global GEMINI context missing or no atelier:code persona: $GEMINI_MD"
fi

if [ "$VFAIL" -ne 0 ]; then
    echo "[atelier:gemini] ERROR: post-install verification failed." >&2
    exit 1
fi
info "All post-install checks passed"

info "Done. Restart Gemini CLI — /atelier:status, /atelier:context are available."
info "Note: Gemini CLI uses absolute paths — do not move atelier after installing."
info "Tip: run 'atelier-status' in any shell to see current run state."
