# Atelier license issuer (Cloudflare Worker)

The paid loop, end to end: **Stripe checkout → signed purchase credential →
stored in D1 → emailed to the customer → device enrollment → signed lease.**

This is the only hosted piece. The client contacts it for device enrollment,
removal, and periodic lease refresh; normal entitlement checks remain local
using an embedded public key. The matching verifier is the Apache-2.0 client at
`src/atelier/core/capabilities/licensing/`. This directory is **proprietary**
(see [LICENSE](./LICENSE)) and is not shipped in the `atelier` wheel.

> Solo / low-ops setup. No user accounts or passwords. Stripe holds billing;
> this Worker mints purchase credentials, tracks three device slots, and issues
> 30-day leases with a 7-day offline grace period.

---

## One-time setup (~30 min)

### 0. Prerequisites

- A Cloudflare account (`npx wrangler login`).
- A Stripe account.
- A [SendPulse](https://sendpulse.com) account with a verified sending domain,
  or swap `src/email.ts` for another sender.

```bash
cd services/license-issuer
npm install
```

### 1. Generate the signing keypair

```bash
npm run keygen
```

This prints a **private key** (Worker secret) and a **public key** (raw, base64).
Do three things with the output:

1. Set the private key as a secret (step 4).
2. Paste the public key into `wrangler.jsonc` → `vars.LICENSE_PUBLIC_KEY`.
3. Paste the **same** public key into the client:
   `src/atelier/core/capabilities/licensing/verify.py` →
   `_EMBEDDED_PUBLIC_KEY_B64 = "..."`.

Store the private key in a password manager. Lose it and you must re-issue every
customer's key. Anyone who has it can mint Pro licenses.

### 2. Create the D1 database

```bash
npx wrangler d1 create atelier-licenses
```

Paste the returned `database_id` into `wrangler.jsonc`, then create the table:

```bash
npm run db:init
```

### 3. Set `SENDPULSE_API_ID`

Edit `wrangler.jsonc` → `vars.SENDPULSE_API_ID` to your SendPulse API ID
(Account → API tab on sendpulse.com).

### 4. Set the secrets

```bash
# from keygen output:
echo '<PKCS8_BASE64>' | npx wrangler secret put LICENSE_PRIVATE_KEY
# from sendpulse.com → Account → API:
echo '<secret>'       | npx wrangler secret put SENDPULSE_API_SECRET
# from step 6 (set placeholder now, update after creating the webhook):
echo 'whsec_...'      | npx wrangler secret put STRIPE_WEBHOOK_SECRET
```

### 5. Deploy

```bash
npm run deploy
```

Note the deployed URL, e.g. `https://atelier-license-issuer.<you>.workers.dev`.
Sanity check: `curl .../health` → `ok`, and `curl .../pubkey` returns your
public key.

### 6. Wire up Stripe

**Product + price.** Create a product in Stripe. Recommended for solo/individual
sales (matches the pricing one-pager):

| Price          | Mode         | `metadata.term` |
| -------------- | ------------ | --------------- |
| $180 / year    | subscription | `annual`        |
| $399 once      | one-time     | `lifetime`      |

On the **price** (or via a Payment Link's metadata), set metadata:
`plan=pro` and `term=annual` (or `lifetime`). The Worker reads these; if absent
it infers `lifetime` for one-time payments and `annual` for subscriptions.

**Payment Link.** Create a Payment Link for the price — that link is your
"Buy" button. No custom checkout UI needed.

**Webhook.** Add an endpoint at
`https://atelier-license-issuer.<you>.workers.dev/stripe/webhook` listening for:

- `checkout.session.completed` — first purchase (issues + emails the key)
- `invoice.paid` — subscription **renewals** only (`subscription_cycle`); re-issues + re-emails
- `customer.subscription.deleted` — cancellation → marks the license revoked
- `charge.refunded` — refund → marks the license revoked

Deliveries are idempotent (deduped by Stripe event id), so retries and the
signup double-fire never send a second key.

Copy the signing secret (`whsec_...`) and re-run the `STRIPE_WEBHOOK_SECRET`
secret command from step 4, then `npm run deploy` again.

### 7. Test

Use Stripe **test mode** + the [Stripe CLI](https://stripe.com/docs/stripe-cli):

```bash
stripe listen --forward-to https://.../stripe/webhook
stripe trigger checkout.session.completed
```

You should receive an email with `atelier license activate <key>`. Run it, then
`atelier license status` should show **active**.

---

## Routes

| Method | Path               | Purpose                                  |
| ------ | ------------------ | ---------------------------------------- |
| GET    | `/health`          | Liveness check.                          |
| GET    | `/pubkey`          | Returns the public key (debug/transparency). |
| POST   | `/stripe/webhook`  | Stripe events → issue + email a purchase credential. |
| POST   | `/devices/activate` | Enroll/reactivate a device and issue its lease. |
| POST   | `/devices/refresh`  | Refresh an active device lease. |
| POST   | `/devices/remove`   | Remove a device immediately and free its slot. |

## Notes

- **Refunds / chargebacks.** Handled automatically: `charge.refunded` and
  `customer.subscription.deleted` mark the D1 row `revoked`. Existing device
  leases stop refreshing and lapse after their remaining lease/grace window.
- **Rotating the keypair** invalidates every issued license. Avoid unless the
  private key leaks; if it does, re-keygen, redeploy, bump
  `_EMBEDDED_PUBLIC_KEY_B64`, ship a client release, and re-issue from D1.
- **Local-first reality.** A determined user can patch out a local check or copy
  both a lease and its device private key. The registry prevents casual key
  sharing by limiting a purchase to three active device identities; it is not
  hardware DRM.
  That's fine at the individual-dev tier: the buyer pays $X to save 10×; the
  moat is the closed savings engine + the brand, not DRM.
