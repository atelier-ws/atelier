#!/usr/bin/env bash
# verify_copilot.sh — Verify Atelier is installed in VS Code Copilot Chat
#
# Checks:
#   1. 'code' CLI on PATH (proxy for VS Code)
#   2. .vscode/mcp.json exists and contains atelier server entry
#   3. copilot-instructions.md mentions Atelier
#   4. atelier_mcp_stdio.sh exists and is executable
#
# Options:
#   --workspace DIR  (default: cwd)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE="${PWD}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workspace) WORKSPACE="$2"; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done

WORKSPACE="$(cd "$WORKSPACE" && pwd)"
FAIL=0

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; FAIL=1; }
skip() { echo "SKIP: $*"; }

echo "=== Atelier VS Code Copilot verification ==="

if ! command -v code &>/dev/null; then
    skip "'code' (VS Code) not on PATH"
    echo "=== SKIPPED (VS Code absent) ==="
    exit 0
fi
pass "VS Code found: $(code --version 2>/dev/null | head -1 || echo 'version unknown')"

MCP_JSON="${WORKSPACE}/.vscode/mcp.json"
if [ -f "$MCP_JSON" ]; then
    HAS=$(python3 -c "
import json
d = json.load(open('$MCP_JSON'))
servers = d.get('servers', d.get('mcpServers', {}))
print('yes' if 'atelier' in servers else 'no')
" 2>/dev/null || echo "error")
    if [ "$HAS" = "yes" ]; then
        pass ".vscode/mcp.json contains atelier server entry"
    else
        fail ".vscode/mcp.json missing atelier entry — run: make install-copilot"
    fi
else
    fail ".vscode/mcp.json missing — run: make install-copilot"
fi

INSTRUCTIONS="${WORKSPACE}/.github/copilot-instructions.md"
if [ -f "$INSTRUCTIONS" ] && grep -q -i "atelier" "$INSTRUCTIONS" 2>/dev/null; then
    pass "copilot-instructions.md references Atelier"
else
    fail "copilot-instructions.md missing or no Atelier reference — run: make install-copilot"
fi

WRAPPER="${ATELIER_REPO}/scripts/atelier_mcp_stdio.sh"
if [ -x "$WRAPPER" ]; then
    pass "atelier_mcp_stdio.sh exists and is executable"
else
    fail "atelier_mcp_stdio.sh missing or not executable: $WRAPPER"
fi

CHATMODE="${WORKSPACE}/.github/chatmodes/atelier.chatmode.md"
if [ -f "$CHATMODE" ]; then
    pass "Copilot chat mode installed: $CHATMODE"
else
    fail "Copilot chat mode missing: $CHATMODE — run: make install-copilot"
fi

if [ -x "${ATELIER_REPO}/bin/atelier-status" ]; then
    pass "bin/atelier-status helper exists"
else
    fail "bin/atelier-status missing or not executable"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "=== FAIL: one or more Copilot checks failed ==="
    exit 1
fi
echo "=== PASS: all Copilot checks passed ==="
