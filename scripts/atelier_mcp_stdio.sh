#!/usr/bin/env bash
# atelier_mcp_stdio.sh — Stable MCP stdio wrapper for all agent hosts
#
# Usage: referenced directly in MCP host configs as the "command" field.
#
# Behaviour:
#   1. Locates the atelier repo root from this script's own location
#      (works regardless of which directory the host spawns the process from)
#   2. Sets ATELIER_ROOT to <workspace>/.atelier if not already set
#   3. Runs: uv run python -m atelier.gateway.adapters.mcp_server
#   4. All log/debug output → stderr ONLY (never contaminates MCP JSON-RPC stdout)
#
# Environment variables honoured:
#   ATELIER_ROOT              — override store root (default: <workspace>/.atelier)
#   ATELIER_WORKSPACE_ROOT    — override workspace root (default: cwd at exec time)
#   ATELIER_STORE_ROOT        — explicit store root override (takes precedence over ATELIER_ROOT)
#
# This script intentionally never writes non-JSON to stdout.

set -euo pipefail

# --- locate atelier repo root (parent of scripts/) --------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATELIER_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- workspace root (provided by host or fallback to cwd) -------------------
if [ -z "${ATELIER_WORKSPACE_ROOT:-}" ]; then
    export ATELIER_WORKSPACE_ROOT="${PWD}"
fi

# --- store root -------------------------------------------------------------
# Default to the atelier repo's own .atelier/ — derived from this script's
# location so the MCP server always writes to the right place regardless of
# what ATELIER_WORKSPACE_ROOT the host injects.
if [ -z "${ATELIER_STORE_ROOT:-}" ] && [ -z "${ATELIER_ROOT:-}" ]; then
    export ATELIER_ROOT="${ATELIER_REPO}/.atelier"
fi

# --- diagnostics → stderr only (never stdout) ------------------------------
>&2 echo "[atelier-mcp] repo=$ATELIER_REPO workspace=${ATELIER_WORKSPACE_ROOT} root=${ATELIER_ROOT:-${ATELIER_STORE_ROOT:-unset}}"

# --- exec MCP server --------------------------------------------------------
cd "$ATELIER_REPO"
exec uv run python -m atelier.gateway.adapters.mcp_server "$@"
