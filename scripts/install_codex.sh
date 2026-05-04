#!/usr/bin/env bash
# install_codex.sh — Install Atelier into Codex CLI
#
# What it does:
#   1. Copies skills into <workspace>/.codex/skills/atelier/
#   2. Writes/merges .codex/mcp.json with atelier MCP entry
#   3. Writes AGENTS.atelier.md to workspace root (context instructions)
#   4. Installs atelier-codex wrapper into <workspace>/bin/
#   5. Installs reusable task templates into <workspace>/.codex/tasks/
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print config snippets for manual install, touch nothing
#   --workspace DIR  Target workspace root (default: cwd)
#   --strict       Exit nonzero if 'codex' CLI not on PATH

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
    echo ""
    echo "1. Copy skills:"
    echo "   mkdir -p '${WORKSPACE}/.codex/skills/atelier'"
    echo "   cp -r '${ATELIER_REPO}/integrations/skills/.' '${WORKSPACE}/.codex/skills/atelier/'"
    echo ""
    echo "2. Write ${WORKSPACE}/.codex/mcp.json:"
    cat <<JSON
{
  "mcpServers": {
    "atelier": {
      "command": "${ATELIER_WRAPPER}",
      "args": [],
      "env": {
        "ATELIER_WORKSPACE_ROOT": "${WORKSPACE}"
      }
    }
  }
}
JSON
    echo ""
    echo "3. Copy AGENTS.atelier.md to your workspace root:"
    echo "   cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '${WORKSPACE}/AGENTS.atelier.md'"
    echo ""
    echo "4. Install wrapper + task templates:"
    echo "   cp '${ATELIER_REPO}/bin/atelier-codex' '${WORKSPACE}/bin/atelier-codex'"
    echo "   chmod +x '${WORKSPACE}/bin/atelier-codex'"
    echo "   cp '${ATELIER_REPO}/integrations/codex/tasks/'*.md '${WORKSPACE}/.codex/tasks/'"
    exit 0
fi

# ---- install skills ---------------------------------------------------------
SKILLS_DEST="${WORKSPACE}/.codex/skills/atelier"
SKILLS_SRC="${ATELIER_REPO}/integrations/skills"
info "Installing skills → $SKILLS_DEST"
run "mkdir -p '$SKILLS_DEST'"
run "cp -r '$SKILLS_SRC/.' '$SKILLS_DEST/'"
info "skills installed"

# ---- register MCP server using codex CLI ----------------------------------
# Codex CLI uses 'codex mcp add' instead of reading from mcp.json
if command -v codex &>/dev/null; then
    info "Registering MCP server with codex CLI..."
    # Check if already installed
    if codex mcp list 2>/dev/null | grep -q "^atelier "; then
        info "atelier MCP already registered"
    else
        run "codex mcp add atelier -- '${ATELIER_WRAPPER}' --env 'ATELIER_WORKSPACE_ROOT=${WORKSPACE}'"
        info "atelier MCP registered"
    fi
else
    # Fallback to mcp.json (older Codex versions)
    warn "codex CLI not found, falling back to mcp.json"
    CODEX_DIR="${WORKSPACE}/.codex"
    MCP_JSON="${CODEX_DIR}/mcp.json"
    NEW_ENTRY=$(cat <<JSON
{
  "mcpServers": {
    "atelier": {
      "command": "${ATELIER_WRAPPER}",
      "args": [],
      "env": {
        "ATELIER_WORKSPACE_ROOT": "${WORKSPACE}"
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
else
    if $DRY_RUN; then
        echo "  [dry-run] create $MCP_JSON"
    else
        echo "$NEW_ENTRY" > "$MCP_JSON"
        info "created $MCP_JSON"
    fi
fi
fi

# ---- AGENTS.atelier.md -------------------------------------------------------
AGENTS_FILE="${WORKSPACE}/AGENTS.atelier.md"
if [ ! -f "$AGENTS_FILE" ]; then
    run "cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '$AGENTS_FILE'"
    info "created AGENTS.atelier.md"
else
    info "AGENTS.atelier.md already exists — not overwriting"
fi

# ---- wrapper + task templates ---------------------------------------------
WRAPPER_SRC="${ATELIER_REPO}/bin/atelier-codex"
WRAPPER_DEST_DIR="${WORKSPACE}/bin"
WRAPPER_DEST="${WRAPPER_DEST_DIR}/atelier-codex"
if [ -f "$WRAPPER_SRC" ]; then
    if [ "$(realpath "$WRAPPER_SRC")" = "$(realpath "$WRAPPER_DEST")" ]; then
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
TASKS_DEST_DIR="${WORKSPACE}/.codex/tasks"
if [ -d "$TASKS_SRC_DIR" ]; then
    run "mkdir -p '$TASKS_DEST_DIR'"
    run "cp '$TASKS_SRC_DIR'/*.md '$TASKS_DEST_DIR/'"
    info "installed task templates: $TASKS_DEST_DIR"
else
    warn "task template directory missing: $TASKS_SRC_DIR"
fi

# ── Post-install verification (replaces verify_codex.sh) ──
info "Running post-install verification..."
VFAIL=0
vpass() { info "PASS: $*"; }
vfail() { echo "[atelier:codex] FAIL: $*" >&2; VFAIL=1; }

SKILLS_DIR="${WORKSPACE}/.codex/skills/atelier"
if [ -d "$SKILLS_DIR" ]; then
    COUNT=$(ls "$SKILLS_DIR" 2>/dev/null | wc -l)
    vpass "skills installed: $SKILLS_DIR ($COUNT items)"
else
    vfail "skills dir missing: $SKILLS_DIR"
fi

if command -v codex &>/dev/null; then
    if codex mcp list 2>/dev/null | grep -q "^atelier "; then
        vpass "atelier MCP server registered (via codex mcp list)"
    elif [ -f "${WORKSPACE}/.codex/mcp.json" ]; then
        HAS=$(python3 -c "
import json
d = json.load(open('${WORKSPACE}/.codex/mcp.json'))
servers = d.get('mcpServers', d.get('servers', {}))
print('yes' if 'atelier' in servers else 'no')
" 2>/dev/null || echo "error")
        if [ "$HAS" = "yes" ]; then
            vpass ".codex/mcp.json contains atelier server entry"
        else
            vfail ".codex/mcp.json missing atelier entry"
        fi
    else
        vfail "atelier MCP not registered"
    fi
else
    vpass "codex CLI not on PATH — skipping MCP registration check"
fi

if [ -x "${ATELIER_WRAPPER}" ]; then
    vpass "atelier_mcp_stdio.sh exists and is executable"
else
    vfail "atelier_mcp_stdio.sh missing or not executable: ${ATELIER_WRAPPER}"
fi

AGENTS_MD="${WORKSPACE}/AGENTS.atelier.md"
if [ -f "$AGENTS_MD" ] && grep -q "atelier:code" "$AGENTS_MD" 2>/dev/null; then
    vpass "AGENTS.atelier.md present with atelier:code persona"
else
    vfail "AGENTS.atelier.md missing or has no atelier:code persona"
fi

WRAPPER_BIN="${WORKSPACE}/bin/atelier-codex"
if [ -x "$WRAPPER_BIN" ]; then
    vpass "Codex preflight wrapper installed: $WRAPPER_BIN"
else
    vfail "Codex preflight wrapper missing or not executable: $WRAPPER_BIN"
fi

TASKS_DIR="${WORKSPACE}/.codex/tasks"
if [ -d "$TASKS_DIR" ] && [ -f "$TASKS_DIR/preflight.md" ]; then
    vpass "Codex task templates installed: $TASKS_DIR"
else
    vfail "Codex task templates missing in $TASKS_DIR"
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

info "Done. Restart Codex — /atelier:status, /atelier:context, etc. are available."
