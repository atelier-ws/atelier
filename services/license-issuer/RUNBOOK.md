# Atelier Pro — issuer + Stripe runbook

Exact steps to take Atelier Pro from code to a working purchase flow. Do the
whole thing in **Stripe test mode** first (test keys, a test webhook, a test
Payment Link, card `4242 4242 4242 4242`), verify end to end, then redo the
Stripe half in live mode.

> **Never commit the private signing key.** It lives only as a Cloudflare Worker
> secret (`LICENSE_PRIVATE_KEY`). The repo ships only the *public* key.

## A. Generate keys (one-time)

```bash
cd services/license-issuer
npm install
npm run keygen          # prints PRIVATE (pkcs8 b64) and PUBLIC (raw-32 b64)
```

Paste the **PUBLIC** key into two places (safe to commit):

- `src/atelier/core/capabilities/licensing/verify.py` →
  `_EMBEDDED_PUBLIC_KEY_B64 = "<public>"` (currently `""`)
- `services/license-issuer/wrangler.jsonc` → `"LICENSE_PUBLIC_KEY": "<public>"`

Keep the **PRIVATE** key for step B.

## B. Deploy the issuer Worker

```bash
npx wrangler login                                   # if not already
npx wrangler d1 create atelier-licenses              # copy database_id -> wrangler.jsonc
npm run db:init                                  # creates tables from schema.sql
# set SENDPULSE_API_ID in wrangler.jsonc (Account → API tab on sendpulse.com)
wrangler secret put LICENSE_PRIVATE_KEY          # paste the pkcs8 private from keygen
wrangler secret put SENDPULSE_API_SECRET         # from sendpulse.com → Account → API
npm run typecheck && npm run deploy              # note the Worker URL
curl https://<worker-url>/health                 # -> ok
curl https://<worker-url>/pubkey                 # -> matches your public key
```

## C. Stripe

1. **Product** "Atelier Pro" with two prices: **$19/mo** (recurring monthly) +
   **$190/yr** (recurring yearly).
2. On each price set **metadata** `plan=pro` and `term=monthly` / `term=annual`
   (the issuer reads `metadata.plan`/`term`; defaults to `pro`/`annual`).
3. **Payment Link** for the price(s) -> copy the link URL.
4. **Developers -> Webhooks -> Add endpoint**: URL
   `https://<worker-url>/stripe/webhook`, events (exactly these four):

   - `checkout.session.completed`
   - `invoice.paid`
   - `customer.subscription.deleted`
   - `charge.refunded`

   Copy the signing secret.
5. ```bash
   wrangler secret put STRIPE_WEBHOOK_SECRET     # paste signing secret
   npm run deploy
   ```

> Order matters: `STRIPE_WEBHOOK_SECRET` only exists after C4, so you deploy once
> in B without it, then re-deploy after C5.

## D. Point `atelier.ws/pro` at the Payment Link

In `landing/wrangler.toml`, under `[vars]`:

```toml
PRO_CHECKOUT_URL = "https://buy.stripe.com/<your-link>"
```

then `cd landing && wrangler deploy`. Now `/pro` -> 302 -> Stripe checkout
(instead of falling back to `/pricing`). The client's default upsell URL
(`https://atelier.ws/pro`) then forwards buyers straight to Stripe.

## E. Ship the client + end-to-end test

```bash
uv lock                                          # pin cryptography
make typecheck && make test
# buy via the Payment Link (test card 4242 4242 4242 4242)
#   -> email arrives with the license key
atelier license activate <key>
atelier license status                           # -> plan: pro, features listed
```

## What each piece does

| Piece                            | Role                                                                      |
| -------------------------------- | ------------------------------------------------------------------------- |
| `npm run keygen`               | Ed25519 keypair. Private -> Worker secret; public -> client + issuer var. |
| Issuer Worker (`src/index.ts`) | Verifies Stripe webhooks and routes device enrollment/refresh/removal.    |
| D1 `atelier-licenses`          | Licenses, three-device registry, and processed-event dedup.               |
| SendPulse                        | Delivers the license-key email.                                           |
| `PRO_CHECKOUT_URL` (landing)   | Redirects `atelier.ws/pro` to the Stripe Payment Link.                  |
| Client licensing package       | Device key storage, lease refresh, and local Ed25519 verification.         |

## Device lifecycle check

Activate the same purchase credential on three isolated test homes. A fourth
interactive activation must list all active devices and require removal of one
before continuing. The replacement must activate immediately. Confirm that the
stored lease has `kind=device`, a `refresh_at` approximately 30 days out, and an
expiry 7 days later (or earlier if the subscription itself ends).
