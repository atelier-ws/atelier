#!/usr/bin/env bash
# verify_atelier_mcp_stdio.sh — MCP stdio protocol smoke test
#
# Sends JSON-RPC messages over stdin/stdout to atelier-mcp and asserts:
#   1. tools/list returns the 5 expected tools
#   2. check_plan with a bad Shopify URL-handle plan returns status=blocked
#   3. get_reasoning_context returns context without error
#   4. rescue_failure returns a result without error
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Atelier MCP stdio verification ==="

TMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TMP_ROOT"' EXIT
export ATELIER_ROOT="$TMP_ROOT"
uv run atelier init --seed >/dev/null

# Build the JSON-RPC batch
MESSAGES=$(cat <<'JSONRPC'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"verify-script","version":"1"},"capabilities":{}}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"check_plan","arguments":{"task":"Update Shopify product via handle","domain":"beseam.shopify.publish","plan":["Parse product handle from the PDP URL","Look up product by handle","Update description","Publish"],"files":[],"tools":["shopify.product.update"]}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_reasoning_context","arguments":{"task":"Update Shopify product metafields","domain":"beseam.shopify.publish","tools":["shopify.update_metafield"]}}}
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"rescue_failure","arguments":{"task":"fix test","error":"AssertionError: expected 200 got 500","attempt":1,"context":"pytest run"}}}
JSONRPC
)

PY_SCRIPT=$(mktemp)
cat <<'EOF' > "$PY_SCRIPT"
import sys, json

lines = [l.strip() for l in sys.stdin.read().strip().split("\n") if l.strip()]
responses = {}
for line in lines:
    try:
        msg = json.loads(line)
        if "id" in msg:
            responses[msg["id"]] = msg
    except Exception:
        pass

# 1. tools/list
assert 2 in responses, "No tools/list response"
tools_result = responses[2].get("result", {})
tool_names = {t["name"] for t in tools_result.get("tools", [])}
required = {"check_plan", "get_reasoning_context", "rescue_failure", "run_rubric_gate", "record_trace"}
missing = required - tool_names
assert not missing, f"Missing tools: {missing}"
print(f"PASS tools/list: {sorted(tool_names)}")

# 2. check_plan with bad Shopify URL-handle plan → blocked
assert 3 in responses, "No check_plan response"
cp_result = responses[3].get("result", {})
cp_content = cp_result.get("content", [{}])
cp_text = cp_content[0].get("text", "") if cp_content else ""
cp_data = json.loads(cp_text) if cp_text else {}
status = cp_data.get("status", "")
assert status == "blocked", f"Expected status=blocked, got status={status!r}. Full: {cp_data}"
print(f"PASS check_plan bad plan: status={status}")

# 3. get_reasoning_context → no error
assert 4 in responses, "No get_reasoning_context response"
ctx_result = responses[4].get("result", {})
assert "error" not in responses[4], f"Unexpected error: {responses[4].get('error')}"
print("PASS get_reasoning_context: no error")

# 4. rescue_failure → no error
assert 5 in responses, "No rescue_failure response"
assert "error" not in responses[5], f"Unexpected error: {responses[5].get('error')}"
print("PASS rescue_failure: no error")

print("=== PASS: all MCP stdio checks passed ===")
EOF

echo "$MESSAGES" | uv run atelier-mcp | python3 "$PY_SCRIPT"
rm "$PY_SCRIPT"
