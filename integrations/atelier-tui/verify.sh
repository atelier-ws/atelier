#!/usr/bin/env bash
# verify.sh — quick smoke-test for atelier-tui host integration
set -euo pipefail

PASS=0; FAIL=0
check() {
    if eval "$2" >/dev/null 2>&1; then
        echo "  ✓ $1"; PASS=$((PASS+1))
    else
        echo "  ✗ $1"; FAIL=$((FAIL+1))
    fi
}

check "atelier CLI on PATH"       "command -v atelier"
check "atelier-tui binary exists" "command -v atelier-tui || test -f ~/.atelier/bin/atelier-tui"
check "tui-backend command works" "atelier tui-backend --help"
check "MCP config exists"         "test -f ~/.atelier/tui/.mcp.json"
check "AGENTS.md installed"       "test -f ~/.atelier/tui/AGENTS.md"

echo ""
echo "Passed: $PASS  Failed: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
