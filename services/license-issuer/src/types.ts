/** Bindings for the Atelier license-issuer Worker. Set via wrangler.jsonc
 * (vars) and `wrangler secret put` (secrets). */
export interface Env {
  /** D1 database binding (see wrangler.jsonc). */
  DB: D1Database;
  /** Stripe webhook signing secret (`whsec_...`). SECRET. */
  STRIPE_WEBHOOK_SECRET: string;
  /** Ed25519 private key, PKCS#8 DER, base64. SECRET. From keygen.mjs. */
  LICENSE_PRIVATE_KEY: string;
  /** Ed25519 public key, raw 32 bytes, base64. VAR. Served at /pubkey. */
  LICENSE_PUBLIC_KEY: string;
  /** Resend API key (`re_...`) used to email keys. SECRET. */
  RESEND_API_KEY: string;
  /** From address, e.g. "Atelier <licenses@yourdomain.com>". VAR. */
  FROM_EMAIL: string;
}
