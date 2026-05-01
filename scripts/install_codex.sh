#!/usr/bin/env bash
# install_codex.sh — Install Atelier into Codex CLI
#
# What it does:
#   1. Copies skills into <workspace>/.codex/skills/atelier/
#   2. Writes/merges .codex/mcp.json with atelier MCP entry
#   3. Writes AGENTS.atelier.md to workspace root (context instructions)
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
    exit 0
fi

# ---- install skills ---------------------------------------------------------
SKILLS_DEST="${WORKSPACE}/.codex/skills/atelier"
SKILLS_SRC="${ATELIER_REPO}/integrations/skills"
info "Installing skills → $SKILLS_DEST"
run "mkdir -p '$SKILLS_DEST'"
run "cp -r '$SKILLS_SRC/.' '$SKILLS_DEST/'"
info "skills installed"

# ---- merge .codex/mcp.json --------------------------------------------------
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

# ---- AGENTS.atelier.md -------------------------------------------------------
AGENTS_FILE="${WORKSPACE}/AGENTS.atelier.md"
if [ ! -f "$AGENTS_FILE" ]; then
    run "cp '${ATELIER_REPO}/integrations/codex/AGENTS.atelier.md' '$AGENTS_FILE'"
    info "created AGENTS.atelier.md"
else
    info "AGENTS.atelier.md already exists — not overwriting"
fi

info "Done. Restart Codex and verify: make verify-codex"
