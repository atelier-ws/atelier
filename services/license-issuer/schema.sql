-- D1 schema for the Atelier license issuer.
--   wrangler d1 execute atelier-licenses --remote --file=schema.sql
CREATE TABLE IF NOT EXISTS licenses (
  license_id      TEXT PRIMARY KEY,
  email           TEXT NOT NULL,
  plan            TEXT NOT NULL,
  term            TEXT NOT NULL,
  stripe_customer TEXT,
  issued_at       INTEGER NOT NULL,
  expires_at      INTEGER,
  token           TEXT NOT NULL,
  revoked         INTEGER NOT NULL DEFAULT 0,
  revoked_at      INTEGER,
  updated_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_licenses_email ON licenses (email);
CREATE INDEX IF NOT EXISTS idx_licenses_customer ON licenses (stripe_customer);

-- Webhook idempotency: one row per processed Stripe event id. Stripe retries
-- redeliver the same id, so we skip events we've already handled.
CREATE TABLE IF NOT EXISTS processed_events (
  event_id   TEXT PRIMARY KEY,
  type       TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
