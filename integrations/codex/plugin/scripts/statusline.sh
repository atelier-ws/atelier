#!/usr/bin/env bash
# statusline.sh -- Codex command-backed statusline for Atelier.
#
# Codex runs this with the statusline JSON on stdin and renders stdout as the
# footer. We merge host-provided context (model / context% / cost) with
# Atelier's per-session savings line (`atelier savings --line`, host-aware via
# ATELIER_STATUS_HOST=codex). Every host field is best-effort: the exact
# tui.status_line input schema is Codex-version-dependent, so unknown fields are
# simply omitted and the Atelier savings segment always renders.
set -uo pipefail

input="$(cat 2>/dev/null || true)"

MODEL=""
SESSION_ID=""
COST=""
CTX_PCT=""
if command -v jq >/dev/null 2>&1 && [ -n "$input" ]; then
  parsed="$(printf '%s' "$input" | jq -r '
    [ (.model.name // .model_display_name // .model // .modelName // ""),
      (.session_id // .sessionId // .thread_id // .threadId // ""),
      (.cost.total_usd // .total_cost_usd // .cost // ""),
      (.context.used_percent // .context_used_percent // .tokens_used_percent // "")
    ] | @tsv' 2>/dev/null || true)"
  IFS=$'\t' read -r MODEL SESSION_ID COST CTX_PCT <<<"$parsed"
fi

export ATELIER_STATUS_HOST="codex"
export ATELIER_STATUS_SESSION_ID="${SESSION_ID:-${CODEX_SESSION_ID:-}}"
if [ -n "${CODEX_WORKSPACE_ROOT:-}" ]; then
  export CLAUDE_WORKSPACE_ROOT="${CODEX_WORKSPACE_ROOT}"
fi

SAVED_LINE=""
ATELIER_BIN="$(command -v atelier 2>/dev/null || true)"
if [ -n "$ATELIER_BIN" ]; then
  SAVED_LINE="$("$ATELIER_BIN" savings --line 2>/dev/null || true)"
fi
if [ -z "$SAVED_LINE" ]; then
  SAVED_LINE="$(uv run --quiet atelier savings --line 2>/dev/null || true)"
fi

SAVED_USD=""
SAVED_CTX=""
SAVED_CALLS=""
STATUS_TEXT=""
ROUTING_USD=""
IFS="|" read -r SAVED_USD SAVED_CTX SAVED_CALLS STATUS_TEXT ROUTING_USD _REST <<<"${SAVED_LINE:-}"
SAVED_USD="${SAVED_USD:-\$0.000}"
SAVED_CTX="${SAVED_CTX:-0}"
SAVED_CALLS="${SAVED_CALLS:-0}"

line="atelier"
[ -n "${MODEL:-}" ] && line="$line | ${MODEL}"
[ -n "${CTX_PCT:-}" ] && line="$line | ctx ${CTX_PCT}%"
if [ -n "${COST:-}" ]; then
  cost_fmt="$(printf '%.3f' "${COST}" 2>/dev/null || printf '%s' "${COST}")"
  line="$line | ↑ \$${cost_fmt}"
fi
if [ "${SAVED_USD}" != "\$0.000" ]; then
  line="$line | ↓ ${SAVED_USD}(${SAVED_CTX})"
fi
if [ "${SAVED_CALLS:-0}" != "0" ]; then
  line="$line | ${SAVED_CALLS} saved"
fi
[ -n "${STATUS_TEXT:-}" ] && line="$line | ${STATUS_TEXT}"

printf '%b\n' "$line"
