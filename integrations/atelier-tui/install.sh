#!/usr/bin/env bash
# install.sh — Install Atelier into atelier-tui
#
# What it does:
#   1. Detects/copies the atelier-tui binary.
#   2. Writes MCP config to ~/.atelier/tui/.mcp.json
#   3. Writes AGENTS.md to ~/.atelier/tui/AGENTS.md
#   4. Writes settings.json to ~/.atelier/tui/settings.json
#
# Options:
#   --dry-run      Print what would happen, touch nothing
#   --print-only   Print config snippets for manual install, touch nothing
#   --strict       Exit nonzero if atelier-tui binary not found
#   --workspace DIR Install into DIR instead of ~/.atelier/tui

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"

DRY_RUN=false
PRINT_ONLY=false
STRICT=false
TARGET_DIR="${HOME}/.atelier/tui"
BIN_DIR="${HOME}/.atelier/bin"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=true ;;
        --print-only) PRINT_ONLY=true ;;
        --strict)     STRICT=true ;;
        --workspace)  shift; TARGET_DIR="$1" ;;
        *) ;;
    esac
    shift
done

info() { [[ "${ATELIER_VERBOSE:-0}" == "1" ]] && echo "[atelier:tui] $*" || true; }
warn() { echo "[atelier:tui] WARN: $*" >&2; }

_do() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] $*"
    else
        eval "$@"
    fi
}

MCP_TEMPLATE="${SCRIPT_DIR}/mcp.template.json"
AGENTS_SRC="${SCRIPT_DIR}/AGENTS.atelier.md"
SETTINGS_SRC="${SCRIPT_DIR}/settings.json"

MCP_DEST="${TARGET_DIR}/.mcp.json"
AGENTS_DEST="${TARGET_DIR}/AGENTS.md"
SETTINGS_DEST="${TARGET_DIR}/settings.json"
BIN_DEST="${BIN_DIR}/atelier-workspace"

# ---- detect atelier-tui binary ---------------------------------------------
BIN_SRC=""
BIN_STATUS="already in PATH"
if command -v atelier-workspace >/dev/null 2>&1; then
    BIN_SRC="$(command -v atelier-workspace)"
    BIN_STATUS="already in PATH"
elif command -v atelier-tui >/dev/null 2>&1; then
    BIN_SRC="$(command -v atelier-tui)"
    BIN_STATUS="already in PATH"
elif [[ -x "${ATELIER_REPO}/crates/atelier-tui/target/release/atelier-workspace" ]]; then
    BIN_SRC="${ATELIER_REPO}/crates/atelier-tui/target/release/atelier-workspace"
    BIN_STATUS="${BIN_DEST}"
elif [[ -x "${ATELIER_REPO}/crates/atelier-tui/target/release/atelier-tui" ]]; then
    BIN_SRC="${ATELIER_REPO}/crates/atelier-tui/target/release/atelier-tui"
    BIN_STATUS="${BIN_DEST}"
elif [[ -x "${HOME}/.atelier/bin/atelier-workspace" ]]; then
    BIN_SRC="${HOME}/.atelier/bin/atelier-workspace"
    BIN_STATUS="already in PATH"
fi

if [[ -z "$BIN_SRC" ]]; then
    if $STRICT; then
        echo "[atelier:tui] ERROR: atelier-tui binary not found." >&2
        echo "  Build it with: cd crates/atelier-tui && cargo build --release" >&2
        exit 1
    fi
    warn "atelier-tui binary not found; config will still be installed."
    BIN_STATUS="not found — build with: cd crates/atelier-tui && cargo build --release"
fi

# ---- print-only mode --------------------------------------------------------
if $PRINT_ONLY; then
    echo ""
    echo "=== Atelier atelier-tui — Manual Install ==="
    echo ""
    echo "MCP config target: ${MCP_DEST}"
    echo "Agents target:     ${AGENTS_DEST}"
    echo "Settings target:   ${SETTINGS_DEST}"
    echo ""
    echo "MCP config (~/.atelier/tui/.mcp.json):"
    cat "$MCP_TEMPLATE"
    exit 0
fi

# ---- install config files ---------------------------------------------------
_do "mkdir -p '${TARGET_DIR}'"

# MCP config: substitute ATELIER_WORKSPACE_ROOT placeholder with current value.
WORKSPACE_ROOT="${ATELIER_WORKSPACE_ROOT:-}"
if $DRY_RUN; then
    echo "[dry-run] write ${MCP_DEST}"
else
    sed "s|\${ATELIER_WORKSPACE_ROOT:-}|${WORKSPACE_ROOT}|g" "$MCP_TEMPLATE" > "$MCP_DEST"
    info "wrote ${MCP_DEST}"
fi

_do "cp -f '${AGENTS_SRC}' '${AGENTS_DEST}'"
_do "cp -f '${SETTINGS_SRC}' '${SETTINGS_DEST}'"

# ---- copy binary if found locally in crates --------------------------------
if [[ -n "$BIN_SRC" && "$BIN_SRC" == "${ATELIER_REPO}/crates/"* ]]; then
    _do "mkdir -p '${BIN_DIR}'"
    _do "cp -f '${BIN_SRC}' '${BIN_DEST}'"
    _do "chmod +x '${BIN_DEST}'"
    info "installed binary -> ${BIN_DEST}"
fi

# ---- success summary --------------------------------------------------------
echo "atelier-tui host installed:"
echo "  MCP config:  ${MCP_DEST}"
echo "  Agents:      ${AGENTS_DEST}"
echo "  Settings:    ${SETTINGS_DEST}"
echo "  Binary:      ${BIN_STATUS}"
echo ""
echo "Run: atelier-tui"
