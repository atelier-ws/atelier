/** Bindings for the Atelier license-issuer Worker. Set via wrangler.jsonc
 * (vars) and `wrangler secret put` (secrets). */
export type IssuerEnv = Env & {
  /** Stripe webhook signing secret (`whsec_...`). SECRET. */
  STRIPE_WEBHOOK_SECRET: string;
  /** Ed25519 private key, PKCS#8 DER, base64. SECRET. From keygen.mjs. */
  LICENSE_PRIVATE_KEY: string;
  /** SendPulse API secret. SECRET. */
  SENDPULSE_API_SECRET: string;
};
