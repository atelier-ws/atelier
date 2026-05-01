#!/usr/bin/env bash
# Smoke-check the Gemini CLI ↔ Atelier MCP wiring.
# Non-destructive: only reads. Requires `gemini` on PATH.
set -euo pipefail

if ! command -v gemini >/dev/null 2>&1; then
  echo "gemini CLI not found on PATH — install from https://github.com/google-gemini/gemini-cli first" >&2
  exit 1
fi

echo "==> /mcp list"
LIST_OUT=$(gemini --prompt "/mcp list" 2>&1 || true)
echo "$LIST_OUT"

if echo "$LIST_OUT" | grep -q "atelier"; then
  echo "=== PASS: gemini is wired to atelier MCP ==="
else
  echo "=== FAIL: gemini not wired to atelier MCP ==="
  exit 1
fi
