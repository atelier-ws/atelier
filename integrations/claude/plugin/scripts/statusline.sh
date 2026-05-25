#!/usr/bin/env bash
# Atelier statusLine script for Claude Code.
# Prints one compact row that fits inside Claude's native agent frame:
#   atelier | Sonnet ... · ctx ... · ...

set -u
input=$(cat)
PLUGIN_LABEL="atelier"

if command -v jq >/dev/null 2>&1; then
  # IFS=$'\t' so spaces in fields like model display_name (e.g. "Opus 4.7")
  # don't cause field-shift that corrupts SESSION_ID (the trailing variable
  # otherwise swallows all remaining whitespace + tab + real id).
  IFS=$'\t' read -r MODEL PCT COST DUR_MS IN_TOK OUT_TOK CACHE_R CACHE_W SESSION_ID MODEL_ID <<<"$(printf '%s' "$input" | jq -r '
    [
      # MODEL = display_name for the UI label ("Opus 4.7")
      (.model.display_name // .model.id // "claude"),
      (.context_window.used_percentage // 0),
      (.cost.total_cost_usd // 0),
      (.cost.total_duration_ms // 0),
      (.context_window.current_usage.input_tokens // 0),
      (.context_window.current_usage.output_tokens // 0),
      (.context_window.current_usage.cache_read_input_tokens // 0),
      (.context_window.current_usage.cache_creation_input_tokens // 0),
      (.session_id // ""),
      # MODEL_ID = canonical id ("claude-opus-4-7") for pricing lookups
      (.model.id // .model.display_name // "")
    ] | @tsv
  ' 2>/dev/null)"
  else
  read_field() {
    python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1] or '{}')
    keys = sys.argv[2].split('.')
    v = d
    for k in keys:
        if isinstance(v, dict):
            v = v.get(k)
        else:
            v = None
            break
    if v is None:
        v = sys.argv[3]
    print(v)
except Exception:
    print(sys.argv[3])
" "$input" "$1" "$2"
  }
  MODEL=$(read_field "model.display_name" "$(read_field "model.id" "claude")")
  MODEL_ID=$(read_field "model.id" "$MODEL")
  PCT=$(read_field "context_window.used_percentage" "0")
  COST=$(read_field "cost.total_cost_usd" "0")
  DUR_MS=$(read_field "cost.total_duration_ms" "0")
  IN_TOK=$(read_field "context_window.current_usage.input_tokens" "0")
  OUT_TOK=$(read_field "context_window.current_usage.output_tokens" "0")
  CACHE_R=$(read_field "context_window.current_usage.cache_read_input_tokens" "0")
  CACHE_W=$(read_field "context_window.current_usage.cache_creation_input_tokens" "0")
  SESSION_ID=$(read_field "session_id" "")
fi

PCT_INT=${PCT%%.*}
[ -z "$PCT_INT" ] && PCT_INT=0
DUR_MS_INT=${DUR_MS%%.*}
[ -z "$DUR_MS_INT" ] && DUR_MS_INT=0
COST_FMT=$(printf '$%.3f' "$COST" 2>/dev/null || echo "\$0.000")
MINS=$(( DUR_MS_INT / 60000 ))
SECS=$(( (DUR_MS_INT % 60000) / 1000 ))

fmt_tok() {
  # Humanize token counts: 999 → 999, 2_164_000 → 2.1M, 695_000 → 695k.
  # The 1M threshold avoids the "2164k" eyesore.
  local n=$1
  if [ "$n" -ge 1000000 ] 2>/dev/null; then
    # one decimal place: integer division on (n*10/1_000_000) then split
    local scaled=$(( n * 10 / 1000000 ))
    printf '%d.%dM' $(( scaled / 10 )) $(( scaled % 10 ))
  elif [ "$n" -ge 1000 ] 2>/dev/null; then
    printf '%dk' $(( n / 1000 ))
  else
    printf '%d' "$n"
  fi
  }

CACHE_F=$(fmt_tok "${CACHE_R:-0}")
CACHE_WF=$(fmt_tok "${CACHE_W:-0}")

ATELIER_STATUS_ROOT="${ATELIER_ROOT:-${ATELIER_STORE_ROOT:-${HOME}/.atelier}}"
export ATELIER_STATUS_ROOT
# savings_summary.py reads ATELIER_ROOT (not ATELIER_STATUS_ROOT) — keep them in sync
export ATELIER_ROOT="${ATELIER_STATUS_ROOT}"
export ATELIER_STATUS_SESSION_ID="${SESSION_ID:-}"
# Pass canonical model id (preferred) then display name as fallback so
# pricing lookups hit the LiteLLM catalog even when only a display name is
# available from Claude Code's context_window payload.
export ATELIER_STATUS_MODEL="${MODEL_ID:-${MODEL:-}}"
export ATELIER_STATUS_MODEL_DISPLAY="${MODEL:-}"
ATELIER_PY="$(bash "$(dirname "${BASH_SOURCE[0]}")/_atelier_python.sh" 2>/dev/null)"
ATELIER_PY="${ATELIER_PY:-python3}"

# Compute savings using the unified savings_summary module.
# Derive the `atelier` CLI from the same bin dir as ATELIER_PY (avoids -m
# failure when the package lacks __main__.py in some install layouts).
_ATELIER_BIN="$(dirname "${ATELIER_PY}")/atelier"
if [ -x "${_ATELIER_BIN}" ]; then
  SAVED_LINE=$("${_ATELIER_BIN}" savings-line 2>/dev/null)
fi
if [ -z "${SAVED_LINE:-}" ]; then
  SAVED_LINE=$(uv run --quiet atelier savings-line 2>/dev/null)
fi
IFS='|' read -r SAVED_USD SAVED_CTX SAVED_CALLS STATUS_TEXT ROUTING_USD <<EOF
$SAVED_LINE
EOF
[ -z "$SAVED_USD" ] && SAVED_USD="\$0.000"
[ -z "$SAVED_CTX" ] && SAVED_CTX="0"
[ -z "$SAVED_CALLS" ] && SAVED_CALLS="0"
[ -z "$ROUTING_USD" ] && ROUTING_USD="\$0.000"

# Persist real API cost so the Stop hook can use it instead of estimating.
# The Stop hook payload from Claude Code never includes the total cost, so we
# cache it here (written after every assistant turn) and read it there.
# Sanitize SESSION_ID: only allow [A-Za-z0-9-_]. Belt-and-suspenders against
# any future parsing regression that could embed a tab/whitespace.
SESSION_ID_CLEAN=$(printf '%s' "${SESSION_ID:-}" | tr -cd 'A-Za-z0-9-_')
if [ -n "${SESSION_ID_CLEAN}" ] && [ "${COST:-0}" != "0" ]; then
  SESSION_ID="$SESSION_ID_CLEAN"
fi
if [ -n "${SESSION_ID:-}" ] && [ "${COST:-0}" != "0" ]; then
  _COST_DIR="${ATELIER_STATUS_ROOT}/session_costs"
  mkdir -p "$_COST_DIR" 2>/dev/null
  printf '%s' "$COST" > "${_COST_DIR}/${SESSION_ID}.txt" 2>/dev/null || true
fi

if [ -n "${ATELIER_NO_COLOR:-}" ]; then
  C_BRAND=""; C_PIPE=""; C_DIM=""; C_GREEN=""; C_RESET=""
else
  C_BRAND=$'\033[1;38;2;168;85;247m'
  C_PIPE=$'\033[2;38;2;200;200;200m'
  C_DIM=$'\033[2;38;2;200;200;200m'
  C_GREEN=$'\033[1;38;2;72;199;116m'
  C_RESET=$'\033[0m'
fi

SEP="${C_DIM}·${C_RESET}"
PIPE="${C_PIPE}|${C_RESET}"

# Build cache write segment only when non-zero (new tokens written to cache)
if [ "${CACHE_W:-0}" -gt 0 ] 2>/dev/null; then
  CACHE_NEW_SEG="+${CACHE_WF}"
else
  CACHE_NEW_SEG=""
fi

# Calls-saved counter intentionally not shown in the statusline.
# Until the calibration store from tests/benchmarks/ feeds equivalent_calls,
# the per-tool "calls saved" number is a guessed multiplier and showing it
# next to a real dollar figure misleads. Tokens-saved (chars-of-context not
# loaded) is measurable today.
SAVED_CALLS_SEG=""
if [ -n "${STATUS_TEXT:-}" ]; then
  STATUS_SEG=" ${SEP} ${STATUS_TEXT}"
else
  STATUS_SEG=""
fi

if [ "$ROUTING_USD" != "\$0.000" ]; then
  ROUTING_SEG=" ${SEP} routing: ${ROUTING_USD}"
else
  ROUTING_SEG=""
fi

printf '%s%s%s %s %s%s ctx %s%% cache %s%s %s %s ↓ %s%s(%s)%s%s %s %dm%02ds\n' \
  "$C_BRAND" "$PLUGIN_LABEL" "$C_RESET" \
  "$PIPE" "$MODEL" "$STATUS_SEG" "$PCT_INT" \
  "$CACHE_F" "$CACHE_NEW_SEG" \
  "$PIPE" "$COST_FMT" \
  "$C_GREEN" "$SAVED_USD" "$SAVED_CTX" "$C_RESET" \
  "$ROUTING_SEG" \
  "$PIPE" "$MINS" "$SECS"
