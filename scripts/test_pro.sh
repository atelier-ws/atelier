#!/usr/bin/env bash
# End-to-end dev-mode test of the paid flow, fully local (no real Stripe, no prod):
#
#   signed Stripe webhook -> plan-bridge worker -> shared local D1 (miniflare)
#   -> landing /api/auth/me plan sync -> CLI entitlement (licensing.status())
#
# The OAuth browser step is simulated by seeding a session row directly (that
# hop is Google's UI; everything after it is exercised for real). Run with:
#   make test-pro
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LANDING="$ROOT/landing"
ISSUER="$ROOT/services/license-issuer"
STATE="$LANDING/.wrangler/flow-test-state" # shared miniflare state: same D1 database_id => same local DB
EMAIL="devflow@example.com"
TOKEN="devflow-session-token"
WHSEC="whsec_devflowtest"
# High ports: 4321 collides with a live `npm run dev`, 8787 with the Atelier
# service daemon (also a FastAPI /health responder — do not probe-share it).
LANDING_PORT=14321
ISSUER_PORT=18787
PY="${PYTHON:-python3}"

log() { printf '\033[36m[pro]\033[0m %s\n' "$*"; }
fail() {
    printf '\033[31m[pro] FAIL:\033[0m %s\n' "$*"
    exit 1
}

cleanup() {
    pkill -f "wrangler dev --port $ISSUER_PORT" 2>/dev/null || true
    pkill -f "wrangler dev --port $LANDING_PORT" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT

# 0. Fresh, isolated local state for a deterministic run
cleanup
rm -rf "$STATE"

# 1. Local D1 schemas + seeded auth session (plan starts 'free' on purpose:
#    proves the /api/auth/me plan-bridge sync, i.e. the buy-after-login path).
cd "$LANDING"
[[ -d dist ]] || npx astro build >/dev/null
log "applying local D1 schemas"
npx wrangler d1 execute atelier-licenses --local --persist-to "$STATE" \
    --file="$ISSUER/schema.sql" >/dev/null
npx wrangler d1 execute atelier-auth --local --persist-to "$STATE" --command "
CREATE TABLE IF NOT EXISTS auth_users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL, github_id TEXT, google_id TEXT, stripe_customer TEXT, plan TEXT NOT NULL DEFAULT 'free', created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS auth_sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, device_name TEXT, device_id TEXT, kind TEXT NOT NULL DEFAULT 'web', created_at TEXT NOT NULL DEFAULT (datetime('now')), expires_at TEXT NOT NULL, last_seen_at TEXT NOT NULL DEFAULT (datetime('now')));
INSERT OR REPLACE INTO auth_users (user_id, email, plan) VALUES ('u_devflow', '$EMAIL', 'free');
INSERT OR REPLACE INTO auth_sessions (token, user_id, device_name, device_id, kind, expires_at) VALUES ('$TOKEN', 'u_devflow', 'devflow', 'dev123', 'cli', datetime('now', '+1 day'));
" >/dev/null

# 2. Boot both workers against the SAME persisted state
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

# 3. Simulate the purchase: a correctly signed checkout.session.completed
BODY='{"id":"evt_devflow_1","type":"checkout.session.completed","data":{"object":{"mode":"subscription","customer":"cus_devflow","customer_details":{"email":"'"$EMAIL"'"},"metadata":{"plan":"pro","term":"monthly"}}}}'
TS=$(date +%s)
SIG=$("$PY" -c "import hmac, hashlib, sys; print(hmac.new(sys.argv[1].encode(), f'{sys.argv[2]}.{sys.argv[3]}'.encode(), hashlib.sha256).hexdigest())" "$WHSEC" "$TS" "$BODY")
RESP=$(curl -s -X POST "http://127.0.0.1:$ISSUER_PORT/stripe/webhook" \
    -H "Stripe-Signature: t=$TS,v1=$SIG" -H "Content-Type: application/json" \
    --data-binary "$BODY")
[[ "$RESP" == "ok" ]] || fail "webhook returned '$RESP' (/tmp/devflow-issuer.log)"
log "webhook accepted -> plan row written"

# 4. Landing reads the plan through the shared D1 and syncs the account
ME=$(curl -s "http://127.0.0.1:$LANDING_PORT/api/auth/me" -H "Authorization: Bearer $TOKEN")
echo "$ME" | grep -q '"plan":"pro"' || fail "/api/auth/me did not report pro: $ME"
log "/api/auth/me -> plan: pro"

# 5. CLI entitlement resolves pro against the dev auth base
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
