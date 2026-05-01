#!/usr/bin/env bash
# verify_codex.sh — Verify Atelier is installed in Codex CLI
#
# Checks:
#   1. 'codex' CLI on PATH
#   2. .codex/skills/atelier/ exists in workspace
#   3. .codex/mcp.json contains atelier entry
#   4. atelier_mcp_stdio.sh exists and is executable
#
# Options:
#   --workspace DIR  Target workspace root (default: cwd)

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

echo "=== Atelier Codex verification ==="

if ! command -v codex &>/dev/null; then
    skip "'codex' CLI not on PATH — install from https://github.com/openai/codex"
    echo "=== SKIPPED (codex CLI absent) ==="
    exit 0
fi
pass "codex CLI found: $(codex --version 2>/dev/null || echo 'version unknown')"

SKILLS_DIR="${WORKSPACE}/.codex/skills/atelier"
if [ -d "$SKILLS_DIR" ]; then
    COUNT=$(ls "$SKILLS_DIR" | wc -l)
    pass "skills installed: $SKILLS_DIR ($COUNT items)"
else
    fail "skills dir missing: $SKILLS_DIR — run: make install-codex"
fi

MCP_JSON="${WORKSPACE}/.codex/mcp.json"
if [ -f "$MCP_JSON" ]; then
    HAS=$(python3 -c "
import json, sys
d = json.load(open('$MCP_JSON'))
servers = d.get('mcpServers', d.get('servers', {}))
print('yes' if 'atelier' in servers else 'no')
" 2>/dev/null || echo "error")
    if [ "$HAS" = "yes" ]; then
        pass ".codex/mcp.json contains atelier server entry"
    else
        fail ".codex/mcp.json missing atelier entry — run: make install-codex"
    fi
else
    fail ".codex/mcp.json missing — run: make install-codex"
fi

WRAPPER="${ATELIER_REPO}/scripts/atelier_mcp_stdio.sh"
if [ -x "$WRAPPER" ]; then
    pass "atelier_mcp_stdio.sh exists and is executable"
else
    fail "atelier_mcp_stdio.sh missing or not executable: $WRAPPER"
fi

# atelier persona file (workspace-local AGENTS.atelier.md)
AGENTS_MD="${WORKSPACE}/AGENTS.atelier.md"
if [ -f "$AGENTS_MD" ] && grep -q "atelier:code" "$AGENTS_MD" 2>/dev/null; then
    pass "AGENTS.atelier.md present with atelier:code persona"
else
    fail "AGENTS.atelier.md missing or has no atelier:code persona — run: make install-codex"
fi

if [ -x "${ATELIER_REPO}/bin/atelier-status" ]; then
    pass "bin/atelier-status helper exists"
else
    fail "bin/atelier-status missing or not executable"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "=== FAIL: one or more Codex checks failed ==="
    exit 1
fi
echo "=== PASS: all Codex checks passed ==="
