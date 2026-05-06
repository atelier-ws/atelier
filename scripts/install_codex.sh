#!/usr/bin/env bash
# install_codex.sh — Install Atelier into Codex CLI
#
# What it does:
#   Global mode: installs Codex skills/instructions under ~/.codex and registers MCP.
#   Workspace mode (--workspace DIR): installs project-local Codex artifacts under DIR.
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print config snippets for manual install, touch nothing
#   --workspace DIR  Install project-local artifacts into DIR instead of global user config
#   --strict       Exit nonzero if 'codex' CLI not on PATH

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

CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
if $WORKSPACE_SET; then
    INSTALL_SCOPE="workspace"
    SKILLS_DEST="${WORKSPACE}/.codex/skills/atelier"
    AGENTS_FILE="${WORKSPACE}/AGENTS.md"
    WRAPPER_DEST_DIR="${WORKSPACE}/bin"
    TASKS_DEST_DIR="${WORKSPACE}/.codex/tasks"
    MCP_JSON="${WORKSPACE}/.codex/mcp.json"
else
    INSTALL_SCOPE="global"
    SKILLS_DEST="${CODEX_HOME}/skills/atelier"
    AGENTS_FILE="${CODEX_HOME}/AGENTS.md"
    WRAPPER_DEST_DIR="${HOME}/.local/bin"
    TASKS_DEST_DIR=""
    MCP_JSON=""
fi

info()  { echo "[atelier:codex] $*"; }
warn()  { echo "[atelier:codex] WARN: $*" >&2; }
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
if ! command -v codex &>/dev/null; then
    if $STRICT; then
        echo "[atelier:codex] ERROR: 'codex' CLI not found. Install from https://github.com/openai/codex" >&2
        exit 1
    fi
    warn "'codex' CLI not found — SKIPPING. Install from https://github.com/openai/codex"
    exit 2
fi
info "Found Codex: $(codex --version 2>/dev/null || echo 'version unknown')"

# ---- print-only mode --------------------------------------------------------
if $PRINT_ONLY; then
    echo ""
    echo "=== Atelier Codex — Manual Install Steps ==="
    echo "Scope: ${INSTALL_SCOPE}"
    echo ""
    echo "1. Copy skills:"
    echo "   mkdir -p '${SKILLS_DEST}'"
    echo "   cp -r '${ATELIER_REPO}/integrations/skills/.' '${SKILLS_DEST}/'"
    echo ""
    if $WORKSPACE_SET; then
        echo "2. Write ${MCP_JSON}:"
        cat <<JSON
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
    else
        echo "2. Register the global MCP server:"
        echo "   codex mcp add atelier -- '${ATELIER_WRAPPER}'"
    fi
    echo ""
    echo "3. Install Codex instructions:"
    echo "   cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '${AGENTS_FILE}'"
    echo ""
    echo "4. Install wrapper:"
    echo "   mkdir -p '${WRAPPER_DEST_DIR}'"
    echo "   cp '${ATELIER_REPO}/bin/atelier-codex' '${WRAPPER_DEST_DIR}/atelier-codex'"
    echo "   chmod +x '${WRAPPER_DEST_DIR}/atelier-codex'"
    if $WORKSPACE_SET; then
        echo ""
        echo "5. Install task templates:"
        echo "   mkdir -p '${TASKS_DEST_DIR}'"
        echo "   cp '${ATELIER_REPO}/integrations/codex/tasks/'*.md '${TASKS_DEST_DIR}/'"
    fi
    exit 0
fi

# ---- install skills ---------------------------------------------------------
SKILLS_SRC="${ATELIER_REPO}/integrations/skills"
info "Installing skills → $SKILLS_DEST"
run "mkdir -p '$SKILLS_DEST'"
run "cp -r '$SKILLS_SRC/.' '$SKILLS_DEST/'"
info "skills installed"

# ---- register MCP server ----------------------------------------------------
if $WORKSPACE_SET; then
    CODEX_DIR="${WORKSPACE}/.codex"
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
    run "mkdir -p '$CODEX_DIR'"
    if [ -f "$MCP_JSON" ]; then
        backup_file "$MCP_JSON"
        if $DRY_RUN; then
            echo "  [dry-run] merge atelier entry into $MCP_JSON"
        else
            python3 - <<PYEOF
import json
with open('$MCP_JSON') as f:
    existing = json.load(f)
new_entry = json.loads('''$NEW_ENTRY''')
existing.setdefault("mcpServers", {}).update(new_entry["mcpServers"])
with open('$MCP_JSON', 'w') as f:
    json.dump(existing, f, indent=2)
    f.write('\n')
print("[atelier:codex] merged atelier entry into $MCP_JSON")
PYEOF
        fi
    elif $DRY_RUN; then
        echo "  [dry-run] create $MCP_JSON"
    else
        echo "$NEW_ENTRY" > "$MCP_JSON"
        info "created $MCP_JSON"
    fi
else
    info "Registering MCP server with codex CLI..."
    if codex mcp list 2>/dev/null | grep -q "^atelier "; then
        info "atelier MCP already registered"
    else
        run "codex mcp add atelier -- '${ATELIER_WRAPPER}'"
        info "atelier MCP registered"
    fi
fi

# ---- AGENTS.md --------------------------------------------------------------
if [ ! -f "$AGENTS_FILE" ]; then
    run "mkdir -p '$(dirname "$AGENTS_FILE")'"
    run "cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '$AGENTS_FILE'"
    info "created $AGENTS_FILE"
else
    info "$AGENTS_FILE already exists — not overwriting"
    info "manually copy if needed: cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '$AGENTS_FILE'"
fi

# ---- wrapper + task templates ---------------------------------------------
WRAPPER_SRC="${ATELIER_REPO}/bin/atelier-codex"
WRAPPER_DEST="${WRAPPER_DEST_DIR}/atelier-codex"
if [ -f "$WRAPPER_SRC" ]; then
    if [ -e "$WRAPPER_DEST" ] && [ "$(realpath "$WRAPPER_SRC")" = "$(realpath "$WRAPPER_DEST")" ]; then
        info "wrapper already in place: $WRAPPER_DEST"
    else
        run "mkdir -p '$WRAPPER_DEST_DIR'"
        run "cp '$WRAPPER_SRC' '$WRAPPER_DEST'"
        run "chmod +x '$WRAPPER_DEST'"
        info "installed wrapper: $WRAPPER_DEST"
    fi
else
    warn "wrapper source missing: $WRAPPER_SRC"
fi

TASKS_SRC_DIR="${ATELIER_REPO}/integrations/codex/tasks"
if $WORKSPACE_SET && [ -d "$TASKS_SRC_DIR" ]; then
    run "mkdir -p '$TASKS_DEST_DIR'"
    run "cp '$TASKS_SRC_DIR'/*.md '$TASKS_DEST_DIR/'"
    info "installed task templates: $TASKS_DEST_DIR"
elif $WORKSPACE_SET; then
    warn "task template directory missing: $TASKS_SRC_DIR"
fi

if $DRY_RUN; then
    info "Dry run complete; skipping post-install verification."
    exit 0
fi

# ── Post-install verification ------------------------------------------------
info "Running post-install verification..."
VFAIL=0
vpass() { info "PASS: $*"; }
vfail() { echo "[atelier:codex] FAIL: $*" >&2; VFAIL=1; }

if [ -d "$SKILLS_DEST" ]; then
    COUNT=$(ls "$SKILLS_DEST" 2>/dev/null | wc -l)
    vpass "skills installed: $SKILLS_DEST ($COUNT items)"
else
    vfail "skills dir missing: $SKILLS_DEST"
fi

if $WORKSPACE_SET; then
    if [ -f "$MCP_JSON" ]; then
        HAS=$(python3 -c "
import json
d = json.load(open('${MCP_JSON}'))
servers = d.get('mcpServers', d.get('servers', {}))
print('yes' if 'atelier' in servers else 'no')
" 2>/dev/null || echo "error")
        [ "$HAS" = "yes" ] && vpass "$MCP_JSON contains atelier server entry" || vfail "$MCP_JSON missing atelier entry"
    else
        vfail "workspace MCP config missing: $MCP_JSON"
    fi
elif codex mcp list 2>/dev/null | grep -q "^atelier "; then
    vpass "atelier MCP server registered (via codex mcp list)"
else
    vfail "atelier MCP not registered"
fi

if [ -x "${ATELIER_WRAPPER}" ]; then
    vpass "atelier_mcp_stdio.sh exists and is executable"
else
    vfail "atelier_mcp_stdio.sh missing or not executable: ${ATELIER_WRAPPER}"
fi

if [ -f "$AGENTS_FILE" ] && grep -q "atelier:code" "$AGENTS_FILE" 2>/dev/null; then
    vpass "AGENTS.md present with atelier:code persona: $AGENTS_FILE"
else
    vfail "AGENTS.md missing or has no atelier:code persona: $AGENTS_FILE"
fi

if [ -x "$WRAPPER_DEST" ]; then
    vpass "Codex preflight wrapper installed: $WRAPPER_DEST"
else
    vfail "Codex preflight wrapper missing or not executable: $WRAPPER_DEST"
fi

if $WORKSPACE_SET; then
    if [ -d "$TASKS_DEST_DIR" ] && [ -f "$TASKS_DEST_DIR/preflight.md" ]; then
        vpass "Codex task templates installed: $TASKS_DEST_DIR"
    else
        vfail "Codex task templates missing in $TASKS_DEST_DIR"
    fi
fi

if [ -x "${ATELIER_REPO}/bin/atelier-status" ]; then
    vpass "bin/atelier-status helper exists"
else
    vfail "bin/atelier-status missing or not executable"
fi

if [ "$VFAIL" -ne 0 ]; then
    echo "[atelier:codex] ERROR: post-install verification failed." >&2
    exit 1
fi
info "All post-install checks passed"

info "Done. Restart Codex — Atelier skills and MCP tools are available."
