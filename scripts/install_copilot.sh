#!/usr/bin/env bash
# install_copilot.sh — Install Atelier into VS Code Copilot Chat
#
# What it does:
#   1. Writes/merges .vscode/mcp.json with atelier server entry
#   2. Appends atelier context to .github/copilot-instructions.md
#   3. Merges Atelier task presets into .vscode/tasks.json
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print exact manual steps, touch nothing
#   --workspace DIR  Target workspace root (default: cwd)
#   --strict       Exit nonzero if 'code' CLI not on PATH
#
# Note: VS Code Copilot does not have a standalone CLI; 'code' (VS Code) is
# used as the proxy check. If 'code' is absent, gracefully skip.

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

info()  { echo "[atelier:copilot] $*"; }
warn()  { echo "[atelier:copilot] WARN: $*" >&2; }
run()   { $DRY_RUN && echo "  [dry-run] $*" || eval "$@"; }
backup_file() {
    local f="$1"
    if [ -f "$f" ]; then
        local bk="${f}.atelier-backup.$(date +%Y%m%dT%H%M%S)"
        run "cp '$f' '$bk'"
        info "backed up $f → $bk"
    fi
}

# ---- check VS Code ----------------------------------------------------------
if ! command -v code &>/dev/null; then
    if $STRICT; then
        echo "[atelier:copilot] ERROR: 'code' (VS Code) not found on PATH." >&2
        exit 1
    fi
    warn "'code' (VS Code) not found — SKIPPING."
    warn "Install VS Code from https://code.visualstudio.com then run: make install-copilot"
    exit 2
fi
info "Found VS Code: $(code --version 2>/dev/null | head -1 || echo 'version unknown')"

# ---- print-only mode --------------------------------------------------------
if $PRINT_ONLY; then
    echo ""
    echo "=== Atelier VS Code Copilot — Manual Install Steps ==="
    echo ""
    echo "1. Create/merge ${WORKSPACE}/.vscode/mcp.json:"
    cat <<JSON
{
  "servers": {
    "atelier": {
      "type": "stdio",
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
    echo "2. Append to ${WORKSPACE}/.github/copilot-instructions.md:"
    echo "   (contents of ${ATELIER_REPO}/integrations/copilot/COPILOT_INSTRUCTIONS.atelier.md)"
    echo ""
    echo "3. Reload VS Code window: Ctrl+Shift+P → 'Developer: Reload Window'"
    echo "4. In Copilot Chat, verify: @atelier /atelier-status"
    exit 0
fi

# ---- write .vscode/mcp.json -------------------------------------------------
VSCODE_DIR="${WORKSPACE}/.vscode"
MCP_JSON="${VSCODE_DIR}/mcp.json"
NEW_ENTRY=$(cat <<JSON
{
  "servers": {
    "atelier": {
      "type": "stdio",
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

run "mkdir -p '$VSCODE_DIR'"

if [ -f "$MCP_JSON" ]; then
    backup_file "$MCP_JSON"
    if $DRY_RUN; then
        echo "  [dry-run] merge atelier into $MCP_JSON"
    else
        python3 - <<PYEOF
import json
with open('$MCP_JSON') as f:
    existing = json.load(f)
new_entry = json.loads('''$NEW_ENTRY''')
existing.setdefault("servers", {}).update(new_entry["servers"])
with open('$MCP_JSON', 'w') as f:
    json.dump(existing, f, indent=2)
    f.write('\n')
print("[atelier:copilot] merged atelier into $MCP_JSON")
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

# ---- append copilot instructions --------------------------------------------
GITHUB_DIR="${WORKSPACE}/.github"
INSTRUCTIONS="${GITHUB_DIR}/copilot-instructions.md"
ATELIER_INSTRUCTIONS="${ATELIER_REPO}/integrations/copilot/COPILOT_INSTRUCTIONS.atelier.md"

run "mkdir -p '$GITHUB_DIR'"

if [ -f "$INSTRUCTIONS" ]; then
    if grep -q "Atelier — Copilot Instructions" "$INSTRUCTIONS" 2>/dev/null; then
        info "copilot-instructions.md already contains Atelier section — skipping"
    else
        backup_file "$INSTRUCTIONS"
        if $DRY_RUN; then
            echo "  [dry-run] append Atelier section to $INSTRUCTIONS"
        else
            echo "" >> "$INSTRUCTIONS"
            cat "$ATELIER_INSTRUCTIONS" >> "$INSTRUCTIONS"
            info "appended Atelier instructions to $INSTRUCTIONS"
        fi
    fi
else
    run "cp '$ATELIER_INSTRUCTIONS' '$INSTRUCTIONS'"
    info "created $INSTRUCTIONS"
fi

# ---- install atelier chat mode ---------------------------------------------
CHATMODE_SRC="${ATELIER_REPO}/integrations/copilot/chatmodes/atelier.chatmode.md"
CHATMODE_DEST_DIR="${WORKSPACE}/.github/chatmodes"
CHATMODE_DEST="${CHATMODE_DEST_DIR}/atelier.chatmode.md"
if [ -f "$CHATMODE_SRC" ]; then
    run "mkdir -p '$CHATMODE_DEST_DIR'"
    if [ -f "$CHATMODE_DEST" ]; then
        info "$CHATMODE_DEST already exists — not overwriting"
    else
        run "cp '$CHATMODE_SRC' '$CHATMODE_DEST'"
        info "created chat mode: $CHATMODE_DEST (select 'atelier' in Copilot Chat dropdown)"
    fi
else
    warn "chat mode source missing: $CHATMODE_SRC"
fi

# ---- merge .vscode/tasks.json ----------------------------------------------
TASKS_SRC="${ATELIER_REPO}/integrations/copilot/tasks.json"
TASKS_DEST="${WORKSPACE}/.vscode/tasks.json"

if [ -f "$TASKS_SRC" ]; then
    if [ -f "$TASKS_DEST" ]; then
        backup_file "$TASKS_DEST"
        if $DRY_RUN; then
            echo "  [dry-run] merge Atelier task presets into $TASKS_DEST"
        else
            python3 - <<PYEOF
import json
from pathlib import Path

dest = Path('$TASKS_DEST')
src = Path('$TASKS_SRC')
existing = json.loads(dest.read_text(encoding='utf-8'))
incoming = json.loads(src.read_text(encoding='utf-8'))

existing.setdefault('version', '2.0.0')
existing_tasks = existing.setdefault('tasks', [])
existing_inputs = existing.setdefault('inputs', [])

existing_labels = {str(t.get('label')) for t in existing_tasks if isinstance(t, dict)}
for task in incoming.get('tasks', []):
    if task.get('label') not in existing_labels:
        existing_tasks.append(task)

existing_input_ids = {str(i.get('id')) for i in existing_inputs if isinstance(i, dict)}
for item in incoming.get('inputs', []):
    if item.get('id') not in existing_input_ids:
        existing_inputs.append(item)

dest.write_text(json.dumps(existing, indent=2) + '\n', encoding='utf-8')
print('[atelier:copilot] merged Atelier task presets into ' + str(dest))
PYEOF
        fi
    else
        run "cp '$TASKS_SRC' '$TASKS_DEST'"
        info "created VS Code tasks preset: $TASKS_DEST"
    fi
else
    warn "task preset source missing: $TASKS_SRC"
fi

# ── Post-install verification (replaces verify_copilot.sh) ──
info "Running post-install verification..."
VFAIL=0
vpass() { info "PASS: $*"; }
vfail() { echo "[atelier:copilot] FAIL: $*" >&2; VFAIL=1; }

MCP_JSON="${WORKSPACE}/.vscode/mcp.json"
if [ -f "$MCP_JSON" ]; then
    HAS=$(python3 -c "
import json
d = json.load(open('$MCP_JSON'))
servers = d.get('servers', d.get('mcpServers', {}))
print('yes' if 'atelier' in servers else 'no')
" 2>/dev/null || echo "error")
    if [ "$HAS" = "yes" ]; then
        vpass ".vscode/mcp.json contains atelier server entry"
    else
        vfail ".vscode/mcp.json missing atelier entry"
    fi
else
    vfail ".vscode/mcp.json missing"
fi

INSTRUCTIONS="${WORKSPACE}/.github/copilot-instructions.md"
if [ -f "$INSTRUCTIONS" ] && grep -q -i "atelier" "$INSTRUCTIONS" 2>/dev/null; then
    vpass "copilot-instructions.md references Atelier"
else
    vfail "copilot-instructions.md missing or no Atelier reference"
fi

if [ -x "${ATELIER_WRAPPER}" ]; then
    vpass "atelier_mcp_stdio.sh exists and is executable"
else
    vfail "atelier_mcp_stdio.sh missing or not executable: ${ATELIER_WRAPPER}"
fi

CHATMODE="${WORKSPACE}/.github/chatmodes/atelier.chatmode.md"
if [ -f "$CHATMODE" ]; then
    vpass "Copilot chat mode installed: $CHATMODE"
else
    vfail "Copilot chat mode missing: $CHATMODE"
fi

TASKS_JSON="${WORKSPACE}/.vscode/tasks.json"
if [ -f "$TASKS_JSON" ] && grep -q "Atelier: Check Plan" "$TASKS_JSON" 2>/dev/null; then
    vpass "Atelier VS Code task presets installed in .vscode/tasks.json"
else
    vfail ".vscode/tasks.json missing Atelier task presets"
fi

if [ -x "${ATELIER_REPO}/bin/atelier-status" ]; then
    vpass "bin/atelier-status helper exists"
else
    vfail "bin/atelier-status missing or not executable"
fi

if [ "$VFAIL" -ne 0 ]; then
    echo "[atelier:copilot] ERROR: post-install verification failed." >&2
    exit 1
fi
info "All post-install checks passed"

info "Done. Reload VS Code window — Atelier skills and tasks are available."
info "Tip: run 'atelier-status' in any shell to see current run state."
