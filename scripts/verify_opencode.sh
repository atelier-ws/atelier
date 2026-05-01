#!/usr/bin/env bash
# verify_opencode.sh — Verify Atelier is installed in opencode
#
# Checks:
#   1. 'opencode' CLI on PATH
#   2. opencode.json or opencode.jsonc exists and contains atelier MCP entry
#   3. atelier_mcp_stdio.sh wrapper exists and executable
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

echo "=== Atelier opencode verification ==="

if ! command -v opencode &>/dev/null; then
    skip "'opencode' not on PATH — install from https://opencode.ai"
    echo "=== SKIPPED (opencode absent) ==="
    exit 0
fi
pass "opencode found: $(opencode --version 2>/dev/null || echo 'version unknown')"

# Find config file
OC_FILE=""
for f in "${WORKSPACE}/opencode.jsonc" "${WORKSPACE}/opencode.json"; do
    [ -f "$f" ] && OC_FILE="$f" && break
done

if [ -z "$OC_FILE" ]; then
    fail "opencode config not found (tried opencode.jsonc, opencode.json) — run: make install-opencode"
else
    HAS=$(python3 - <<PYEOF
import json, re
with open('$OC_FILE') as f:
    content = f.read()
stripped = re.sub(r'^\s*//.*', '', content, flags=re.M)
try:
    d = json.loads(stripped)
    print('yes' if 'atelier' in d.get('mcp', {}) else 'no')
except Exception:
    print('parse-error')
PYEOF
)
    if [ "$HAS" = "yes" ]; then
        pass "opencode config contains atelier MCP entry ($OC_FILE)"
    elif [ "$HAS" = "parse-error" ]; then
        fail "opencode config parse error: $OC_FILE"
    else
        fail "opencode config missing atelier entry — run: make install-opencode"
    fi

    DEFAULT_AGENT=$(python3 - <<PYEOF
import json, re
with open('$OC_FILE') as f:
    content = f.read()
stripped = re.sub(r'^\s*//.*', '', content, flags=re.M)
try:
    d = json.loads(stripped)
    print(d.get('default_agent', ''))
except Exception:
    print('')
PYEOF
)
    if [ "$DEFAULT_AGENT" = "atelier" ]; then
        pass "opencode default_agent = atelier"
    else
        fail "opencode default_agent is '$DEFAULT_AGENT' (expected 'atelier') — run: make install-opencode"
    fi
fi

# atelier agent file
AGENT_FILE="${WORKSPACE}/.opencode/agents/atelier.md"
if [ -f "$AGENT_FILE" ]; then
    pass "opencode atelier agent installed: $AGENT_FILE"
else
    fail "opencode atelier agent missing: $AGENT_FILE — run: make install-opencode"
fi

WRAPPER="${ATELIER_REPO}/scripts/atelier_mcp_stdio.sh"
if [ -x "$WRAPPER" ]; then
    pass "atelier_mcp_stdio.sh exists and is executable"
else
    fail "atelier_mcp_stdio.sh missing or not executable: $WRAPPER"
fi

if [ -x "${ATELIER_REPO}/bin/atelier-status" ]; then
    pass "bin/atelier-status helper exists"
else
    fail "bin/atelier-status missing or not executable"
fi

if [ "$FAIL" -ne 0 ]; then
    echo "=== FAIL: one or more opencode checks failed ==="
    exit 1
fi
echo "=== PASS: all opencode checks passed ==="
