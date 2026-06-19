/** Atelier license-issuer Worker.
 *
 * Stripe checkout -> signed Ed25519 license -> stored in D1 -> emailed to the
 * customer. Fully offline-verifiable on the client; this service never sees the
 * customer's machine. CLOSED / commercial -- see ./LICENSE.
 */

import { sendLicenseEmail } from "./email";
import { type LicensePayload, signLicense } from "./license";
import { verifyStripeSignature } from "./stripe";
import type { Env } from "./types";

// Must match PRO_FEATURES in the Python client (features.py). An empty list in
// the token also means "all Pro features"; we send the explicit list so older
// clients still see exactly what they bought.
const PRO_FEATURES = [
  "optimizer",
  "context_compression",
  "prefix_cache",
  "scoped_context",
  "budget_optimizer",
  "model_routing",
  "cross_vendor_routing",
  "savings_dashboard",
  "unlimited_repos",
];

const DAY = 86400;

function termToExpiry(term: string, nowSec: number): number | null {
  switch (term) {
    case "lifetime":
      return null;
    case "annual":
      return nowSec + 400 * DAY; // 1 year + grace
    default:
      return nowSec + 35 * DAY; // monthly + grace
  }
}

interface IssueInput {
  email: string;
  plan: string;
  term: string;
  customer: string | null;
}

async function issueAndDeliver(env: Env, input: IssueInput): Promise<string> {
  const nowSec = Math.floor(Date.now() / 1000);
  const expires = termToExpiry(input.term, nowSec);
  // Stable id per Stripe customer so renewals refresh the same license row.
  const licenseId = input.customer
    ? `lic_${input.customer}`
    : `lic_${crypto.randomUUID()}`;
  const payload: LicensePayload = {
    v: 1,
    id: licenseId,
    email: input.email,
    plan: input.plan,
    iat: nowSec,
    exp: expires,
    features: PRO_FEATURES,
  };
  const token = await signLicense(payload, env.LICENSE_PRIVATE_KEY);

  await env.DB.prepare(
    `INSERT INTO licenses
       (license_id, email, plan, term, stripe_customer, issued_at, expires_at, token, revoked, revoked_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)
     ON CONFLICT(license_id) DO UPDATE SET
       email=excluded.email, plan=excluded.plan, term=excluded.term,
       expires_at=excluded.expires_at, token=excluded.token,
       revoked=0, revoked_at=NULL, updated_at=excluded.updated_at`,
  )
    .bind(
      licenseId,
      input.email,
      input.plan,
      input.term,
      input.customer,
      nowSec,
      expires,
      token,
      nowSec,
    )
    .run();

  await sendLicenseEmail({
    apiKey: env.RESEND_API_KEY,
    from: env.FROM_EMAIL,
    to: input.email,
    token,
    plan: input.plan,
    expires,
  });
  return token;
}

/** Best-effort revocation. Offline-issued keys keep working until their embedded
 * expiry (we cannot reach the customer's machine), but we mark the row revoked
 * and shorten its expiry so renewals stop and any future online check enforces
 * it. */
async function revokeByCustomer(
  env: Env,
  customer: string | null,
  nowSec: number,
): Promise<void> {
  if (!customer) return;
  await env.DB.prepare(
    `UPDATE licenses
        SET revoked = 1, revoked_at = ?, expires_at = MIN(COALESCE(expires_at, ?), ?), updated_at = ?
      WHERE license_id = ?`,
  )
    .bind(nowSec, nowSec, nowSec, nowSec, `lic_${customer}`)
    .run();
}

async function alreadyProcessed(env: Env, eventId: string): Promise<boolean> {
  const row = await env.DB.prepare(
    "SELECT 1 FROM processed_events WHERE event_id = ?",
  )
    .bind(eventId)
    .first();
  return row !== null;
}

async function markProcessed(
  env: Env,
  eventId: string,
  type: string,
  nowSec: number,
): Promise<void> {
  await env.DB.prepare(
    "INSERT OR IGNORE INTO processed_events (event_id, type, created_at) VALUES (?, ?, ?)",
  )
    .bind(eventId, type, nowSec)
    .run();
}

async function handleStripeWebhook(req: Request, env: Env): Promise<Response> {
  const body = await req.text();
  const ok = await verifyStripeSignature(
    body,
    req.headers.get("Stripe-Signature"),
    env.STRIPE_WEBHOOK_SECRET,
  );
  if (!ok) return new Response("bad signature", { status: 400 });

  let event: any;
  try {
    event = JSON.parse(body);
  } catch {
    return new Response("bad json", { status: 400 });
  }

  const eventId: string | undefined = event.id;
  const nowSec = Math.floor(Date.now() / 1000);

  // Idempotency: Stripe retries deliver the same event id more than once.
  // Verify-then-process-then-mark, so a failed run (500) is retried but a
  // succeeded one is never re-emailed.
  if (eventId && (await alreadyProcessed(env, eventId))) {
    return new Response("ok (duplicate)");
  }

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const s = event.data.object;
        const email = s.customer_details?.email ?? s.customer_email;
        if (email) {
          await issueAndDeliver(env, {
            email,
            plan: s.metadata?.plan ?? "pro",
            // `payment` mode => one-time => lifetime; `subscription` => annual.
            term:
              s.metadata?.term ??
              (s.mode === "payment" ? "lifetime" : "annual"),
            customer: s.customer ?? null,
          });
        }
        break;
      }
      case "invoice.paid": {
        const inv = event.data.object;
        // Renewals only. The first subscription invoice (`subscription_create`)
        // is already covered by checkout.session.completed -- acting on it too
        // would email the buyer a second key on signup.
        if (inv.billing_reason !== "subscription_cycle") break;
        const email = inv.customer_email;
        const meta = inv.lines?.data?.[0]?.metadata ?? {};
        if (email) {
          await issueAndDeliver(env, {
            email,
            plan: meta.plan ?? "pro",
            term: meta.term ?? "annual",
            customer: inv.customer ?? null,
          });
        }
        break;
      }
      case "customer.subscription.deleted": {
        await revokeByCustomer(
          env,
          event.data.object?.customer ?? null,
          nowSec,
        );
        break;
      }
      case "charge.refunded": {
        await revokeByCustomer(
          env,
          event.data.object?.customer ?? null,
          nowSec,
        );
        break;
      }
      default:
        break;
    }
  } catch (err) {
    // Do not mark processed -> Stripe will retry this event.
    return new Response(`handler error: ${(err as Error).message}`, {
      status: 500,
    });
  }

  if (eventId) await markProcessed(env, eventId, event.type, nowSec);
  return new Response("ok");
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (req.method === "GET" && url.pathname === "/health") {
      return new Response("ok");
    }
    if (req.method === "GET" && url.pathname === "/pubkey") {
      return Response.json({
        public_key: env.LICENSE_PUBLIC_KEY,
        algorithm: "ed25519",
        format: "raw-base64",
      });
    }
    if (req.method === "POST" && url.pathname === "/stripe/webhook") {
      return handleStripeWebhook(req, env);
    }
    return new Response("not found", { status: 404 });
  },
};
