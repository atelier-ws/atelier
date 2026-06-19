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
       (license_id, email, plan, term, stripe_customer, issued_at, expires_at, token, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(license_id) DO UPDATE SET
       email=excluded.email, plan=excluded.plan, term=excluded.term,
       expires_at=excluded.expires_at, token=excluded.token, updated_at=excluded.updated_at`,
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

  try {
    if (event.type === "checkout.session.completed") {
      const s = event.data.object;
      const email = s.customer_details?.email ?? s.customer_email;
      if (!email) return new Response("ok (no email)");
      const meta = s.metadata ?? {};
      await issueAndDeliver(env, {
        email,
        plan: meta.plan ?? "pro",
        // `payment` mode => one-time => lifetime; `subscription` => annual.
        term: meta.term ?? (s.mode === "payment" ? "lifetime" : "annual"),
        customer: s.customer ?? null,
      });
    } else if (event.type === "invoice.paid") {
      // Subscription renewal: refresh the same customer's license + email it.
      const inv = event.data.object;
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
    }
  } catch (err) {
    return new Response(`handler error: ${(err as Error).message}`, {
      status: 500,
    });
  }
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
