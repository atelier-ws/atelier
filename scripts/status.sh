#!/usr/bin/env bash
# status.sh — Show Atelier installation status across all agent CLIs
#
# Options:
#   --workspace DIR  Target workspace root (default: cwd)
#   --json          Output in JSON format

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKSPACE="${PWD}"
JSON=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --json) JSON=true ;;
        --workspace) WORKSPACE="$2"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

WORKSPACE="$(cd "$WORKSPACE" && pwd)"

# Helper to check if command exists
has_cmd() { command -v "$1" &> /dev/null; }

# Check runtime store
check_runtime() {
    local status="❌ not initialized"
    local initialized=false
    
    if [ -d "${WORKSPACE}/.atelier" ]; then
        status="✅ exists"
        # Check for ledger.json or atelier.db (SQLite)
        if [ -f "${WORKSPACE}/.atelier/ledger.json" ] || [ -f "${WORKSPACE}/.atelier/atelier.db" ]; then
            status="✅ initialized"
            initialized=true
        else
            status="⚠️  exists but not initialized"
        fi
    fi
    echo "$status"
    echo "$initialized"
}

# Check CLI symlink
check_symlink() {
    if [ -L "${HOME}/.local/bin/atelier-status" ]; then
        echo "✅ linked to ~/.local/bin"
    else
        echo "❌ not linked"
    fi
}

# Check Claude Code
check_claude() {
    if ! has_cmd claude; then
        echo "⚠️  CLI not found"
        return
    fi
    if claude plugin list 2>/dev/null | grep -q "atelier"; then
        echo "✅ installed"
    else
        echo "⚠️  CLI found but plugin not installed"
    fi
}

# Check Codex
check_codex() {
    if ! has_cmd codex; then
        echo "⚠️  CLI not found"
        return
    fi
    if [ -d "${WORKSPACE}/.codex/skills/atelier" ]; then
        echo "✅ installed"
    else
        echo "⚠️  CLI found but skills not installed"
    fi
}

# Check opencode
check_opencode() {
    if ! has_cmd opencode; then
        echo "⚠️  CLI not found"
        return
    fi
    # Check .opencode/mcp.json or opencode.jsonc
    if grep -q "atelier" "${HOME}/.opencode/mcp.json" 2>/dev/null || \
       grep -q "atelier" "${WORKSPACE}/.opencode/mcp.json" 2>/dev/null || \
       grep -q "atelier" "${WORKSPACE}/opencode.jsonc" 2>/dev/null; then
        echo "✅ installed"
    else
        echo "⚠️  CLI found but MCP not configured"
    fi
}

# Check VS Code Copilot
check_copilot() {
    if ! has_cmd code; then
        echo "⚠️  CLI not found"
        return
    fi
    if [ -f "${WORKSPACE}/.vscode/mcp.json" ] && grep -q "atelier" "${WORKSPACE}/.vscode/mcp.json"; then
        echo "✅ installed"
    else
        echo "⚠️  CLI found but MCP not configured"
    fi
}

# Check Gemini CLI
check_gemini() {
    if ! has_cmd gemini; then
        echo "⚠️  CLI not found"
        return
    fi
    if grep -q "atelier" "${HOME}/.gemini/settings.json" 2>/dev/null || \
       grep -q "atelier" "${WORKSPACE}/.gemini/settings.json" 2>/dev/null; then
        echo "✅ installed"
    else
        echo "⚠️  CLI found but MCP not configured"
    fi
}

# Get latest run info
get_latest_run() {
    if [ -d "${WORKSPACE}/.atelier/runs" ]; then
        bash "${ATELIER_REPO}/bin/atelier-status" --root "${WORKSPACE}/.atelier" 2>/dev/null || echo "(no runs yet)"
    else
        echo "(no runs yet)"
    fi
}

# Print status
if [ "$JSON" = true ]; then
    # JSON output
    RUNTIME=$(check_runtime)
    echo "{}" | python3 -c "
import json, sys
print(json.dumps({
    'runtime': '$RUNTIME',
    'symlink': '$(check_symlink)',
    'claude': '$(check_claude)',
    'codex': '$(check_codex)',
    'opencode': '$(check_copilot)',
    'copilot': '$(check_copilot)',
    'gemini': '$(check_gemini)'
}))
"
else
    # Human-readable output
    echo "=== Atelier Status ==="
    echo ""
    echo "Runtime Store:"
    echo "  .atelier/       $(check_runtime | head -1)"
    echo ""
    echo "CLI Symlink:"
    echo "  $(check_symlink)"
    echo ""
    echo "Agent CLI Installations:"
    echo "  Claude Code     $(check_claude)"
    echo "  Codex           $(check_codex)"
    echo "  opencode        $(check_opencode)"
    echo "  Copilot         $(check_copilot)"
    echo "  Gemini          $(check_gemini)"
    echo ""
    echo "Latest Run:"
    echo "  $(get_latest_run)"
fi