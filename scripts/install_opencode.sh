#!/usr/bin/env bash
# install_opencode.sh — Install Atelier into opencode
#
# What it does:
#   Merges atelier MCP entry into <workspace>/opencode.jsonc (or creates it)
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print config snippet for manual install, touch nothing
#   --workspace DIR  Target workspace root (default: cwd)
#   --strict       Exit nonzero if 'opencode' CLI not on PATH

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

info()  { echo "[atelier:opencode] $*"; }
warn()  { echo "[atelier:opencode] WARN: $*" >&2; }
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
if ! command -v opencode &>/dev/null; then
    if $STRICT; then
        echo "[atelier:opencode] ERROR: 'opencode' not found. Install from https://opencode.ai" >&2
        exit 1
    fi
    warn "'opencode' not found — SKIPPING. Install from https://opencode.ai"
    exit 2
fi
info "Found opencode: $(opencode --version 2>/dev/null || echo 'version unknown')"

# ---- print-only mode --------------------------------------------------------
if $PRINT_ONLY; then
    echo ""
    echo "=== Atelier opencode — Manual Install ==="
    echo ""
    echo "Merge into ${WORKSPACE}/opencode.jsonc (or create it):"
    cat <<JSON
{
  "mcp": {
    "atelier": {
      "type": "local",
      "command": ["${ATELIER_WRAPPER}"],
      "environment": {
        "ATELIER_WORKSPACE_ROOT": "${WORKSPACE}"
      }
    }
  }
}
JSON
    exit 0
fi

# ---- merge opencode.jsonc ---------------------------------------------------
# opencode reads both opencode.json and opencode.jsonc; prefer .jsonc if present
if [ -f "${WORKSPACE}/opencode.jsonc" ]; then
    OC_FILE="${WORKSPACE}/opencode.jsonc"
elif [ -f "${WORKSPACE}/opencode.json" ]; then
    OC_FILE="${WORKSPACE}/opencode.json"
else
    OC_FILE="${WORKSPACE}/opencode.jsonc"
fi

NEW_ENTRY=$(cat <<JSON
{
  "default_agent": "atelier",
  "mcp": {
    "atelier": {
      "type": "local",
      "command": ["${ATELIER_WRAPPER}"],
      "environment": {
        "ATELIER_WORKSPACE_ROOT": "${WORKSPACE}"
      }
    }
  }
}
JSON
)

if [ -f "$OC_FILE" ]; then
    backup_file "$OC_FILE"
    if $DRY_RUN; then
        echo "  [dry-run] merge atelier into $OC_FILE"
    else
        python3 - <<PYEOF
import json
with open('$OC_FILE') as f:
    content = f.read().strip()
# opencode uses JSON5/JSONC — strip // line comments for parsing
import re
stripped = re.sub(r'^\s*//.*', '', content, flags=re.M)
existing = json.loads(stripped) if stripped.strip() else {}
new_entry = json.loads('''$NEW_ENTRY''')
existing.setdefault("mcp", {}).update(new_entry["mcp"])
existing.setdefault("default_agent", new_entry["default_agent"])
with open('$OC_FILE', 'w') as f:
    json.dump(existing, f, indent=2)
    f.write('\n')
print("[atelier:opencode] merged atelier entry into $OC_FILE")
PYEOF
    fi
else
    if $DRY_RUN; then
        echo "  [dry-run] create $OC_FILE"
    else
        echo "$NEW_ENTRY" > "$OC_FILE"
        info "created $OC_FILE"
    fi
fi

# ---- install opencode atelier agent (workspace-local) -----------------------
AGENT_SRC="${ATELIER_REPO}/integrations/opencode/agents/atelier.md"
AGENT_DEST_DIR="${WORKSPACE}/.opencode/agents"
if [ -f "$AGENT_SRC" ]; then
    run "mkdir -p '$AGENT_DEST_DIR'"
    run "cp -f '$AGENT_SRC' '$AGENT_DEST_DIR/atelier.md'"
    info "atelier agent installed → $AGENT_DEST_DIR/atelier.md"
else
    warn "agent source missing: $AGENT_SRC"
fi

# ── Post-install verification (replaces verify_opencode.sh) ──
info "Running post-install verification..."
VFAIL=0
vpass() { info "PASS: $*"; }
vfail() { echo "[atelier:opencode] FAIL: $*" >&2; VFAIL=1; }

# Find config file
OC_FILE=""
for f in "${WORKSPACE}/opencode.jsonc" "${WORKSPACE}/opencode.json"; do
    [ -f "$f" ] && OC_FILE="$f" && break
done

if [ -z "$OC_FILE" ]; then
    vfail "opencode config not found (tried opencode.jsonc, opencode.json)"
else
    HAS=$(python3 - <<PYEOF
import json, re
with open('$OC_FILE') as f:
    content = f.read()
stripped = re.sub(r'^\s*//.*', '', content, flags=re.M)
try:
    d = json.loads(stripped)
    print('yes' if 'atelier' in d.get('mcp', {}) else 'no')
except Exception:
    print('parse-error')
PYEOF
)
    if [ "$HAS" = "yes" ]; then
        vpass "opencode config contains atelier MCP entry ($OC_FILE)"
    elif [ "$HAS" = "parse-error" ]; then
        vfail "opencode config parse error: $OC_FILE"
    else
        vfail "opencode config missing atelier entry"
    fi

    DEFAULT_AGENT=$(python3 - <<PYEOF
import json, re
with open('$OC_FILE') as f:
    content = f.read()
stripped = re.sub(r'^\s*//.*', '', content, flags=re.M)
try:
    d = json.loads(stripped)
    print(d.get('default_agent', ''))
except Exception:
    print('')
PYEOF
)
    if [ "$DEFAULT_AGENT" = "atelier" ]; then
        vpass "opencode default_agent = atelier"
    else
        vfail "opencode default_agent is '$DEFAULT_AGENT' (expected 'atelier')"
    fi
fi

AGENT_FILE="${WORKSPACE}/.opencode/agents/atelier.md"
if [ -f "$AGENT_FILE" ]; then
    vpass "opencode atelier agent installed: $AGENT_FILE"
else
    vfail "opencode atelier agent missing: $AGENT_FILE"
fi

if [ -x "${ATELIER_WRAPPER}" ]; then
    vpass "atelier_mcp_stdio.sh exists and is executable"
else
    vfail "atelier_mcp_stdio.sh missing or not executable: ${ATELIER_WRAPPER}"
fi

if [ -x "${ATELIER_REPO}/bin/atelier-status" ]; then
    vpass "bin/atelier-status helper exists"
else
    vfail "bin/atelier-status missing or not executable"
fi

if [ "$VFAIL" -ne 0 ]; then
    echo "[atelier:opencode] ERROR: post-install verification failed." >&2
    exit 1
fi
info "All post-install checks passed"

info "Done. Restart opencode — /atelier:status, /atelier:context are available."
info "Tip: run 'atelier-status' in any shell to see current run state."
