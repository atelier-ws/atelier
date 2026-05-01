#!/usr/bin/env bash
# install_claude.sh — Install Atelier into Claude Code
#
# What it does:
#   1. Validates the plugin package at integrations/claude/plugin/
#   2. Installs atelier@atelier (idempotent)
#   3. Merges the atelier MCP server entry into <workspace>/.mcp.json
#
# After this:
#   - `claude plugin list` shows  atelier@atelier  ✔ enabled
#   - /atelier:status, /atelier:context, /atelier:settings work in Claude Code
#   - atelier:code, atelier:explore, atelier:review, atelier:repair agents available
#   - MCP tools (atelier_get_reasoning_context, etc.) wired via .mcp.json
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print config snippets for manual install, touch nothing
#   --workspace DIR  Target workspace root (default: cwd)
#   --strict       Exit nonzero if 'claude' CLI not on PATH
#
# Requirements: bash, python3, claude CLI ≥ 2.1
# Skips gracefully if 'claude' CLI not found (unless --strict)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_DIR="${ATELIER_REPO}/integrations/claude/plugin"
INSTALL_SOURCE_DIR="${ATELIER_REPO}"
ATELIER_WRAPPER="${ATELIER_REPO}/scripts/atelier_mcp_stdio.sh"
PLUGIN_REF="atelier@atelier"

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

info()  { echo "[atelier:claude] $*"; }
warn()  { echo "[atelier:claude] WARN: $*" >&2; }

if ! command -v claude &>/dev/null; then
    if $STRICT; then
        echo "[atelier:claude] ERROR: 'claude' CLI not found on PATH. Install from https://claude.ai/download" >&2
        exit 1
    fi
    warn "'claude' CLI not found on PATH — SKIPPING Claude install."
    warn "Install Claude Code from https://claude.ai/download, then run: make install-claude"
    exit 2
fi

CLAUDE_VERSION="$(claude --version 2>/dev/null || echo 'unknown')"
info "Found Claude Code: $CLAUDE_VERSION"

if $PRINT_ONLY; then
    echo ""
    echo "=== Atelier Claude Code — Install Steps ==="
    echo ""
    echo "Step 1 — Register the local Atelier source (from repo root):"
    echo "  claude plugin marketplace add '${INSTALL_SOURCE_DIR}'"
    echo "  # This reads .claude-plugin/marketplace.json (name=atelier)"
    echo ""
    echo "Step 2 — Install the plugin:"
    echo "  claude plugin install ${PLUGIN_REF}"
    echo ""
    echo "Step 3 — Verify:"
    echo "  claude plugin list   # should show ${PLUGIN_REF} ✔ enabled"
    echo ""
    echo "Step 4 — Register MCP server in ${WORKSPACE}/.mcp.json:"
    cat <<JSON
{
  "mcpServers": {
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
    echo "After install, in Claude Code: /atelier:status"
    exit 0
fi

if $DRY_RUN; then
    echo "  [dry-run] claude plugin validate ${PLUGIN_DIR}"
else
    info "Validating plugin package at ${PLUGIN_DIR}"
    if ! claude plugin validate "${PLUGIN_DIR}" 2>&1 | grep -q "Validation passed"; then
        echo "[atelier:claude] ERROR: Plugin validation failed. Run: claude plugin validate ${PLUGIN_DIR}" >&2
        exit 1
    fi
    info "Plugin package valid"
fi

if $DRY_RUN; then
    echo "  [dry-run] claude plugin marketplace add '${INSTALL_SOURCE_DIR}'"
else
    info "Registering local Claude plugin source at ${PLUGIN_DIR}"
    INSTALL_SOURCE_OUT="$(claude plugin marketplace add "${PLUGIN_DIR}" 2>&1 || true)"
    if echo "$INSTALL_SOURCE_OUT" | grep -q "already on disk"; then
        info "Claude plugin source 'atelier' already registered"
    elif echo "$INSTALL_SOURCE_OUT" | grep -q "Successfully added"; then
        info "Claude plugin source 'atelier' registered"
    else
        echo "[atelier:claude] ERROR: plugin source add failed: $INSTALL_SOURCE_OUT" >&2
        exit 1
    fi
fi

if $DRY_RUN; then
    echo "  [dry-run] reinstall ${PLUGIN_REF}"
else
    info "Installing/updating plugin ${PLUGIN_REF}"
    claude plugin uninstall "${PLUGIN_REF}" 2>/dev/null || true
    INSTALL_OUT="$(claude plugin install "${PLUGIN_REF}" 2>&1 || true)"
    if echo "$INSTALL_OUT" | grep -qiE "Successfully installed|Installed"; then
        info "Plugin ${PLUGIN_REF} installed"
    else
        echo "[atelier:claude] ERROR: plugin install failed: $INSTALL_OUT" >&2
        exit 1
    fi
fi

MCP_JSON="${WORKSPACE}/.mcp.json"
NEW_ENTRY=$(cat <<JSON
{
  "mcpServers": {
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

if $DRY_RUN; then
    echo "  [dry-run] merge atelier entry into ${MCP_JSON}"
elif [ ! -f "${MCP_JSON}" ]; then
    info "Creating ${MCP_JSON} with atelier entry"
    echo "${NEW_ENTRY}" > "${MCP_JSON}"
else
    HAS=$(python3 -c "
import json
d = json.load(open('${MCP_JSON}'))
servers = d.get('mcpServers', {})
print('yes' if 'atelier' in servers else 'no')
" 2>/dev/null || echo "error")
    if [ "$HAS" = "yes" ]; then
        info "atelier entry already in ${MCP_JSON}"
    else
        info "Merging atelier entry into ${MCP_JSON}"
        python3 -c "
import json
with open('${MCP_JSON}') as f:
    d = json.load(f)
d.setdefault('mcpServers', {})['atelier'] = {
    'type': 'stdio',
    'command': '${ATELIER_WRAPPER}',
    'args': [],
    'env': {'ATELIER_WORKSPACE_ROOT': '${WORKSPACE}'}
}
with open('${MCP_JSON}', 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
"
        info "atelier entry merged into ${MCP_JSON}"
    fi
fi

# ── Step 4: inject CLAUDE_WORKSPACE_ROOT into .claude/settings.local.json ──
# The plugin's atelier-mcp-wrapper.js resolves the binary via:
#   $ATELIER_VENV, $CLAUDE_WORKSPACE_ROOT/atelier/.venv, or PATH.
# Setting CLAUDE_WORKSPACE_ROOT in settings.local.json is the workspace-scoped
# way to provide it without touching the user's shell profile.
CLAUDE_SETTINGS_DIR="${WORKSPACE}/.claude"
CLAUDE_LOCAL_SETTINGS="${CLAUDE_SETTINGS_DIR}/settings.local.json"

if $DRY_RUN; then
    echo "  [dry-run] merge CLAUDE_WORKSPACE_ROOT into ${CLAUDE_LOCAL_SETTINGS}"
else
    mkdir -p "${CLAUDE_SETTINGS_DIR}"
    if [ ! -f "${CLAUDE_LOCAL_SETTINGS}" ]; then
        info "Creating ${CLAUDE_LOCAL_SETTINGS} with env.CLAUDE_WORKSPACE_ROOT"
        echo "{}" > "${CLAUDE_LOCAL_SETTINGS}"
    fi
    HAS_ENV=$(python3 -c "
import json
d = json.load(open('${CLAUDE_LOCAL_SETTINGS}'))
existing = d.get('env', {}).get('CLAUDE_WORKSPACE_ROOT', '')
print(existing)
" 2>/dev/null || echo "")
    if [ "${HAS_ENV}" = "${WORKSPACE}" ]; then
        info "CLAUDE_WORKSPACE_ROOT already set correctly in ${CLAUDE_LOCAL_SETTINGS}"
    else
        info "Setting CLAUDE_WORKSPACE_ROOT=${WORKSPACE} in ${CLAUDE_LOCAL_SETTINGS}"
        python3 -c "
import json
with open('${CLAUDE_LOCAL_SETTINGS}') as f:
    d = json.load(f)
d.setdefault('env', {})['CLAUDE_WORKSPACE_ROOT'] = '${WORKSPACE}'
with open('${CLAUDE_LOCAL_SETTINGS}', 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
"
        info "CLAUDE_WORKSPACE_ROOT written — restart Claude Code for it to take effect"
    fi
fi

# ── Step 5: inject Atelier loop PreToolUse hook into .claude/settings.json ──
# Fires before every Edit/Write call and injects a systemMessage reminding the
# agent to run get_reasoning_context → check_plan before editing.
# This is the enforcement mechanism for the Atelier standing loop.
CLAUDE_SETTINGS="${CLAUDE_SETTINGS_DIR}/settings.json"

if $DRY_RUN; then
    echo "  [dry-run] merge PreToolUse Atelier loop hook into ${CLAUDE_SETTINGS}"
else
    if [ ! -f "${CLAUDE_SETTINGS}" ]; then
        info "Creating ${CLAUDE_SETTINGS}"
        echo "{}" > "${CLAUDE_SETTINGS}"
    fi
    HOOK_SCRIPT=$(mktemp /tmp/atelier_hook_XXXXXX.py)
    cat > "${HOOK_SCRIPT}" << 'PYEOF'
import json, sys

path = sys.argv[1]
# Command that injects a reminder into Claude's context before every Edit/Write.
hook_command = "echo '{\"systemMessage\": \"\\u26a0 Atelier loop required: call get_reasoning_context \\u2192 check_plan before editing.\"}'"

with open(path) as f:
    d = json.load(f)

hooks = d.setdefault("hooks", {})
pre_tool_use = hooks.setdefault("PreToolUse", [])

matcher = "Edit|Write"
for entry in pre_tool_use:
    if entry.get("matcher") == matcher:
        for h in entry.get("hooks", []):
            if h.get("type") == "command" and "Atelier loop required" in h.get("command", ""):
                print("[atelier:claude] Atelier loop PreToolUse hook already present")
                sys.exit(0)

pre_tool_use.append({
    "matcher": matcher,
    "hooks": [{"type": "command", "command": hook_command}]
})

with open(path, "w") as f:
    json.dump(d, f, indent=2)
    f.write("\n")
print("[atelier:claude] Atelier loop PreToolUse hook merged into " + path)
PYEOF
    python3 "${HOOK_SCRIPT}" "${CLAUDE_SETTINGS}"
    rm -f "${HOOK_SCRIPT}"
fi

info "Done. Start Claude Code in your workspace. Skills and agents are available."
info "  /atelier:status  — show run ledger"
info "  /atelier:context — show environment context"
info "  Agents: atelier:code, atelier:explore, atelier:review, atelier:repair"
