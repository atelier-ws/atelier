#!/usr/bin/env bash
# Local E2E tests of the Pro purchase loop. Two modes:
#
#   make test-pro        (auto) fully automated — no browser, no Stripe account:
#                        hand-signed webhook -> plan-bridge worker -> shared
#                        local D1 -> landing /api/auth/me -> CLI entitlement.
#
#   make test-pro-live   (live) YOU drive the complete real flow on Stripe TEST
#                        mode: the script boots the dev stack, wires
#                        `stripe listen`, opens the browser, and polls until
#                        your test purchase lands in the plan bridge.
#
# Auto mode's only unreal hop is a seeded session (that hop is Google's login
# UI); live mode has none: real OAuth -> real Stripe checkout -> real webhook.
set -euo pipefail

MODE="${1:-auto}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LANDING="$ROOT/landing"
ISSUER="$ROOT/services/license-issuer"
STATE="$LANDING/.wrangler/flow-test-state"
EMAIL="devflow@example.com"
TOKEN="devflow-session-token"
ISSUER_PORT=18787
PY="${PYTHON:-python3}"

if [[ "$MODE" == "live" ]]; then
    LANDING_PORT=4321 # the dev GitHub/Google OAuth apps redirect to localhost:4321
else
    LANDING_PORT=14321 # away from live-dev (4321) and the atelier daemon (8787)
fi

log() { printf '\033[36m[pro]\033[0m %s\n' "$*"; }
fail() {
    printf '\033[31m[pro] FAIL:\033[0m %s\n' "$*"
    exit 1
}

cleanup() {
    pkill -f "wrangler dev --port $ISSUER_PORT" 2>/dev/null || true
    pkill -f "wrangler dev --port $LANDING_PORT" 2>/dev/null || true
    [[ -n "${STRIPE_PID:-}" ]] && kill "$STRIPE_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT

# 0. Prerequisites + fresh, isolated local state
if [[ "$MODE" == "live" ]]; then
    command -v stripe >/dev/null || fail "Stripe CLI not installed — https://stripe.com/docs/stripe-cli"
    WHSEC=$(stripe listen --print-secret 2>/dev/null) || fail "Stripe CLI not authenticated — run: stripe login"
    if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$LANDING_PORT" 2>/dev/null; then
        fail "port $LANDING_PORT is busy — stop the running landing dev first"
    fi
else
    WHSEC="whsec_devflowtest"
fi
cleanup
rm -rf "$STATE"

# 1. Local D1 schemas (+ seeded session in auto mode — seeded as plan 'free' on
#    purpose: proves the /api/auth/me plan-bridge sync, the buy-after-login path)
cd "$LANDING"
[[ -d dist ]] || npx astro build >/dev/null
log "applying local D1 schemas"
npx wrangler d1 execute atelier-licenses --local --persist-to "$STATE" \
    --file="$ISSUER/schema.sql" >/dev/null
if [[ "$MODE" == "live" ]]; then
    # Full auth schema: the real OAuth flow needs state + email-login tables too.
    npx wrangler d1 execute atelier-auth --local --persist-to "$STATE" \
        --file=migrations/0010_auth_users.sql >/dev/null
    npx wrangler d1 execute atelier-auth --local --persist-to "$STATE" \
        --command "ALTER TABLE auth_sessions ADD COLUMN device_id TEXT" >/dev/null
else
    npx wrangler d1 execute atelier-auth --local --persist-to "$STATE" --command "
CREATE TABLE IF NOT EXISTS auth_users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL, github_id TEXT, google_id TEXT, stripe_customer TEXT, plan TEXT NOT NULL DEFAULT 'free', created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS auth_sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, device_name TEXT, device_id TEXT, kind TEXT NOT NULL DEFAULT 'web', created_at TEXT NOT NULL DEFAULT (datetime('now')), expires_at TEXT NOT NULL, last_seen_at TEXT NOT NULL DEFAULT (datetime('now')));
INSERT OR REPLACE INTO auth_users (user_id, email, plan) VALUES ('u_devflow', '$EMAIL', 'free');
INSERT OR REPLACE INTO auth_sessions (token, user_id, device_name, device_id, kind, expires_at) VALUES ('$TOKEN', 'u_devflow', 'devflow', 'dev123', 'cli', datetime('now', '+1 day'));
" >/dev/null
fi

# 2. Boot both workers against the SAME persisted state (same D1 database_id
#    => same local DB, mirroring the shared database in production)
log "starting plan-bridge worker on :$ISSUER_PORT"
(
    cd "$ISSUER" && exec npx wrangler dev --port "$ISSUER_PORT" --inspector-port 19229 \
        --persist-to "$STATE" \
        --var "STRIPE_WEBHOOK_SECRET:$WHSEC" --var "SENDPULSE_API_SECRET:dev-dummy"
) >/tmp/devflow-issuer.log 2>&1 &
log "starting landing worker on :$LANDING_PORT"
(
    cd "$LANDING" && exec npx wrangler dev --port "$LANDING_PORT" --inspector-port 19230 --persist-to "$STATE"
) >/tmp/devflow-landing.log 2>&1 &

for i in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$ISSUER_PORT/health" >/dev/null 2>&1 && break
    [[ $i == 60 ]] && fail "plan-bridge dev server did not start (/tmp/devflow-issuer.log)"
    sleep 1
done
for i in $(seq 1 60); do
    [[ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$LANDING_PORT/api/auth/me")" == "401" ]] && break
    [[ $i == 60 ]] && fail "landing dev server did not start (/tmp/devflow-landing.log)"
    sleep 1
done
log "both workers up"

if [[ "$MODE" == "live" ]]; then
    # ── LIVE: you drive the real flow; the script watches the plan bridge ──
    log "starting stripe listen (test mode) -> :$ISSUER_PORT"
    stripe listen --forward-to "localhost:$ISSUER_PORT/stripe/webhook" \
        >/tmp/devflow-stripe.log 2>&1 &
    STRIPE_PID=$!
    URL="http://localhost:$LANDING_PORT/account"
    (xdg-open "$URL" >/dev/null 2>&1 || open "$URL" >/dev/null 2>&1) || true
    log "── YOUR TURN ───────────────────────────────────────────────"
    log "  browser: $URL"
    log "  1. Sign in (GitHub / Google / email link)"
    log "  2. Click 'Upgrade monthly' — Stripe TEST checkout opens"
    log "  3. Pay with card 4242 4242 4242 4242 · any future expiry · any CVC"
    log "  (the success page points at prod and will say 'not confirmed' —"
    log "   ignore it; the poll below is the real assertion)"
    log "────────────────────────────────────────────────────────────"
    log "waiting for the purchase webhook (up to 15 min, Ctrl-C to abort)..."
    for i in $(seq 1 180); do
        PLAN=$(npx wrangler d1 execute atelier-licenses --local --persist-to "$STATE" \
            --command "SELECT plan FROM licenses ORDER BY updated_at DESC LIMIT 1" --json 2>/dev/null |
            "$PY" -c "import sys,json; r=json.load(sys.stdin)[0]['results']; print(r[0]['plan'] if r else '')" 2>/dev/null || true)
        if [[ "$PLAN" == "pro" || "$PLAN" == "enterprise" ]]; then
            log "plan row recorded: $PLAN"
            break
        fi
        [[ $i == 180 ]] && fail "no purchase after 15 min (/tmp/devflow-stripe.log, /tmp/devflow-issuer.log)"
        sleep 5
    done
    log "refresh the account page — it should now show PRO"
    log "optional CLI check:  uv run atelier login --dev && uv run atelier status --auth"
    log "  (afterwards run 'uv run atelier logout' to reset the dev auth base)"
    printf '\033[36m[pro]\033[0m press Enter to shut the dev stack down... '
    read -r _
    log "PASS: real OAuth -> Stripe test checkout -> webhook -> plan bridge all green"
    exit 0
fi

# ── AUTO: simulate the purchase with a correctly signed webhook ──
BODY='{"id":"evt_devflow_1","type":"checkout.session.completed","data":{"object":{"mode":"subscription","customer":"cus_devflow","customer_details":{"email":"'"$EMAIL"'"},"metadata":{"plan":"pro","term":"monthly"}}}}'
TS=$(date +%s)
SIG=$("$PY" -c "import hmac, hashlib, sys; print(hmac.new(sys.argv[1].encode(), f'{sys.argv[2]}.{sys.argv[3]}'.encode(), hashlib.sha256).hexdigest())" "$WHSEC" "$TS" "$BODY")
RESP=$(curl -s -X POST "http://127.0.0.1:$ISSUER_PORT/stripe/webhook" \
    -H "Stripe-Signature: t=$TS,v1=$SIG" -H "Content-Type: application/json" \
    --data-binary "$BODY")
[[ "$RESP" == "ok" ]] || fail "webhook returned '$RESP' (/tmp/devflow-issuer.log)"
log "webhook accepted -> plan row written"

ME=$(curl -s "http://127.0.0.1:$LANDING_PORT/api/auth/me" -H "Authorization: Bearer $TOKEN")
echo "$ME" | grep -q '"plan":"pro"' || fail "/api/auth/me did not report pro: $ME"
log "/api/auth/me -> plan: pro"

CLIROOT=$(mktemp -d)
printf 'http://127.0.0.1:%s' "$LANDING_PORT" >"$CLIROOT/auth_base"
cd "$ROOT"
OUT=$(ATELIER_ROOT="$CLIROOT" ATELIER_AUTH_TOKEN="$TOKEN" uv run python -c "
from atelier.core.capabilities import licensing
st = licensing.status()
print(st.plan, st.valid)")
[[ "$OUT" == "pro True" ]] || fail "CLI entitlement check: got '$OUT'"
log "CLI licensing.status() -> plan: pro"
rm -rf "$CLIROOT"

log "PASS: webhook -> D1 -> /api/auth/me -> CLI entitlement all green"
