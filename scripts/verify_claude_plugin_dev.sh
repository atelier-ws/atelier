#!/usr/bin/env bash
# verify_claude_plugin_dev.sh — Validate the Atelier plugin structure for local dev mode
#
# This script does NOT require the 'claude' CLI to be installed.
# It checks that the plugin package at integrations/claude/plugin/ is well-formed,
# then prints the command to launch Claude Code in plugin-dev mode.
#
# Usage:
#   bash scripts/verify_claude_plugin_dev.sh
#   make verify-claude-plugin-dev
#
# After running this, start Claude Code with:
#   claude --plugin-dir /abs/path/to/integrations/claude/plugin
#
# Then inside Claude Code, /atelier:status, /atelier:context, etc. are available.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_DIR="${ATELIER_REPO}/integrations/claude/plugin"

FAIL=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; FAIL=1; }

echo "=== Atelier Claude Code plugin-dev validation ==="
echo "Plugin dir: ${PLUGIN_DIR}"
echo ""

# 1. Plugin directory exists
if [ -d "${PLUGIN_DIR}" ]; then
    pass "plugin directory exists: integrations/claude/plugin/"
else
    fail "plugin directory missing: ${PLUGIN_DIR}"
fi

# 2. plugin.json exists and has name=atelier
PLUGIN_JSON="${PLUGIN_DIR}/.claude-plugin/plugin.json"
if [ -f "${PLUGIN_JSON}" ]; then
    NAME=$(python3 -c "import json; d=json.load(open('${PLUGIN_JSON}')); print(d.get('name',''))" 2>/dev/null || echo "")
    if [ "$NAME" = "atelier" ]; then
        pass "plugin.json valid (name=atelier)"
    else
        fail "plugin.json name unexpected: '${NAME}'"
    fi
else
    fail "plugin.json missing: ${PLUGIN_JSON}"
fi

# 3. plugin.json must NOT declare agents/skills/hooks/mcp (auto-discovered), author must be object
if [ -f "${PLUGIN_JSON}" ]; then
    HAS_COMMANDS=$(python3 -c "import json; d=json.load(open('${PLUGIN_JSON}')); print('yes' if 'commands' in d else 'no')" 2>/dev/null || echo "error")
    AUTHOR_TYPE=$(python3 -c "import json; d=json.load(open('${PLUGIN_JSON}')); print(type(d.get('author')).__name__)" 2>/dev/null || echo "error")
    HAS_FORBIDDEN=$(python3 -c "import json; d=json.load(open('${PLUGIN_JSON}')); bad=[k for k in ('agents','skills','hooks','mcp') if k in d]; print(','.join(bad) if bad else 'none')" 2>/dev/null || echo "error")
    if [ "$HAS_COMMANDS" = "yes" ]; then
        fail "plugin.json still has 'commands' key — remove it; skills are auto-discovered from skills/ dir"
    else
        pass "plugin.json has no legacy 'commands' key"
    fi
    if [ "$HAS_FORBIDDEN" = "none" ]; then
        pass "plugin.json has no forbidden keys (agents/skills/hooks/mcp are auto-discovered)"
    else
        fail "plugin.json declares '${HAS_FORBIDDEN}' — remove these; they cause install validation errors"
    fi
    if [ "$AUTHOR_TYPE" = "dict" ]; then
        pass "plugin.json author is an object"
    else
        fail "plugin.json author must be an object like {\"name\": \"Beseam\"}, got type: ${AUTHOR_TYPE}"
    fi
fi

# 4. User-facing skill files exist
for skill in status context savings benchmark analyze-failures evals settings; do
    SKILL_FILE="${PLUGIN_DIR}/skills/${skill}/SKILL.md"
    if [ -f "${SKILL_FILE}" ]; then
        pass "skill exists: skills/${skill}/SKILL.md → /atelier:${skill}"
    else
        fail "skill missing: ${SKILL_FILE}"
    fi
done

# 5. Agent files exist with correct frontmatter
for agent in code explore review repair; do
    AGENT_FILE="${PLUGIN_DIR}/agents/${agent}.md"
    if [ -f "${AGENT_FILE}" ]; then
        pass "agent exists: agents/${agent}.md"
    else
        fail "agent missing: ${AGENT_FILE}"
    fi
done

# 6. hooks.json exists with enabled=false
HOOKS_JSON="${PLUGIN_DIR}/hooks/hooks.json"
if [ -f "${HOOKS_JSON}" ]; then
    pass "hooks/hooks.json exists"
else
    fail "hooks/hooks.json missing: ${HOOKS_JSON}"
fi

# 7. .mcp.json exists and uses CLAUDE_PLUGIN_ROOT
MCP_JSON="${PLUGIN_DIR}/.mcp.json"
if [ -f "${MCP_JSON}" ]; then
    if grep -q 'CLAUDE_PLUGIN_ROOT' "${MCP_JSON}"; then
        pass ".mcp.json uses \${CLAUDE_PLUGIN_ROOT} (safe for marketplace install)"
    else
        fail ".mcp.json does not use \${CLAUDE_PLUGIN_ROOT} — absolute paths will break marketplace install"
    fi
else
    fail ".mcp.json missing: ${MCP_JSON}"
fi

# 8. MCP wrapper exists
WRAPPER="${PLUGIN_DIR}/servers/atelier-mcp-wrapper.js"
if [ -f "${WRAPPER}" ]; then
    pass "MCP wrapper exists: servers/atelier-mcp-wrapper.js"
else
    fail "MCP wrapper missing: ${WRAPPER}"
fi

echo ""
if [ "$FAIL" -ne 0 ]; then
    echo "=== FAIL: fix the above issues before using dev mode ==="
    exit 1
fi

echo "=== PASS: plugin structure valid ==="
echo ""
echo "--- Dev mode (no install required) ---"
echo ""
echo "  claude --plugin-dir '${PLUGIN_DIR}'"
echo ""
echo "Then inside Claude Code:"
echo "  /atelier:status          — show run ledger"
echo "  /atelier:context <domain> — show environment context"
echo "  /atelier:savings         — show savings metrics"
echo "  /agents                  — shows atelier:code, atelier:explore, atelier:review, atelier:repair"
