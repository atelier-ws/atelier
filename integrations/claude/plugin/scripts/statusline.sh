#!/usr/bin/env bash
# Atelier statusLine script for Claude Code.
# Prints one compact row that fits inside Claude's native agent frame:
#   atelier | Sonnet ... · ctx ... · ...

set -u
input=$(cat)
PLUGIN_LABEL="atelier"

if command -v jq >/dev/null 2>&1; then
  MODEL=$(printf '%s' "$input" | jq -r '.model.display_name // .model.id // "claude"' 2>/dev/null)
  PCT=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // 0' 2>/dev/null)
  COST=$(printf '%s' "$input" | jq -r '.cost.total_cost_usd // 0' 2>/dev/null)
  DUR_MS=$(printf '%s' "$input" | jq -r '.cost.total_duration_ms // 0' 2>/dev/null)
  IN_TOK=$(printf '%s' "$input" | jq -r '.context_window.current_usage.input_tokens // 0' 2>/dev/null)
  OUT_TOK=$(printf '%s' "$input" | jq -r '.context_window.current_usage.output_tokens // 0' 2>/dev/null)
  CACHE_R=$(printf '%s' "$input" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0' 2>/dev/null)
  CACHE_W=$(printf '%s' "$input" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0' 2>/dev/null)
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
  MODEL=$(read_field "model.display_name" "claude")
  PCT=$(read_field "context_window.used_percentage" "0")
  COST=$(read_field "cost.total_cost_usd" "0")
  DUR_MS=$(read_field "cost.total_duration_ms" "0")
  IN_TOK=$(read_field "context_window.current_usage.input_tokens" "0")
  OUT_TOK=$(read_field "context_window.current_usage.output_tokens" "0")
  CACHE_R=$(read_field "context_window.current_usage.cache_read_input_tokens" "0")
  CACHE_W=$(read_field "context_window.current_usage.cache_creation_input_tokens" "0")
fi

PCT_INT=${PCT%%.*}
[ -z "$PCT_INT" ] && PCT_INT=0
DUR_MS_INT=${DUR_MS%%.*}
[ -z "$DUR_MS_INT" ] && DUR_MS_INT=0
COST_FMT=$(printf '$%.3f' "$COST" 2>/dev/null || echo "\$0.000")
MINS=$(( DUR_MS_INT / 60000 ))
SECS=$(( (DUR_MS_INT % 60000) / 1000 ))

fmt_tok() {
  local n=$1
  if [ "$n" -ge 1000 ] 2>/dev/null; then
    printf '%dk' $(( n / 1000 ))
  else
    printf '%d' "$n"
  fi
}

IN_F=$(fmt_tok "${IN_TOK:-0}")
OUT_F=$(fmt_tok "${OUT_TOK:-0}")
CACHE_F=$(fmt_tok "${CACHE_R:-0}")
CACHE_WF=$(fmt_tok "${CACHE_W:-0}")

ATELIER_ROOT="${ATELIER_STORE_ROOT:-${PWD}/.atelier}"
SAVED_LINE=$(python3 - "$ATELIER_ROOT" 2>/dev/null <<'PYEOF'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
hist = root / "cost_history.json"
saved_usd = 0.0
ctx_saved = 0
if hist.is_file():
    try:
        d = json.loads(hist.read_text())
        for op in (d.get("operations") or {}).values():
            calls = op.get("calls") or []
            if not calls:
                continue
            base = float(calls[0].get("cost_usd", 0.0))
            for c in calls[1:]:
                saved_usd += max(0.0, base - float(c.get("cost_usd", 0.0)))
                ctx_saved += int(c.get("cache_read_tokens", 0) or 0)
    except Exception:
        pass
def k(n: int) -> str:
    return f"{n//1000}k" if n >= 1000 else str(n)
print(f"${saved_usd:.3f}|{k(ctx_saved)}")
PYEOF
)
SAVED_USD="${SAVED_LINE%|*}"
SAVED_CTX="${SAVED_LINE#*|}"
[ -z "$SAVED_USD" ] && SAVED_USD="\$0.000"
[ -z "$SAVED_CTX" ] && SAVED_CTX="0"

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
  CACHE_NEW_SEG=" +${CACHE_WF}"
else
  CACHE_NEW_SEG=""
fi

printf '%s%s%s %s %s %s ctx %s%% %s cache %s%s %s %s %s saved %s%s%s (ctx %s%s%s) %s %dm%02ds\n' \
  "$C_BRAND" "$PLUGIN_LABEL" "$C_RESET" \
  "$PIPE" "$MODEL" "$SEP" "$PCT_INT" \
  "$SEP" "$CACHE_F" "$CACHE_NEW_SEG" \
  "$SEP" "$COST_FMT" "$SEP" \
  "$C_GREEN" "$SAVED_USD" "$C_RESET" "$C_GREEN" "$SAVED_CTX" "$C_RESET" \
  "$SEP" "$MINS" "$SECS"
