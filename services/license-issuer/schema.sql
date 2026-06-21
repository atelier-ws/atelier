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

CREATE TABLE IF NOT EXISTS devices (
  device_id    TEXT PRIMARY KEY,
  license_id   TEXT NOT NULL REFERENCES licenses(license_id) ON DELETE CASCADE,
  public_key   TEXT NOT NULL,
  name         TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  revoked_at   INTEGER,
  UNIQUE (license_id, public_key)
);

CREATE INDEX IF NOT EXISTS idx_devices_license
  ON devices (license_id, revoked_at, last_seen_at);

-- Email magic-link auth for the self-service device manager. `magic` rows are
-- one-time login links (consumed on first use); `session` rows are the short
-- browser session minted after a magic link is verified. Both store only the
-- SHA-256 of the opaque token, never the token itself.
CREATE TABLE IF NOT EXISTS device_sessions (
  token_hash  TEXT PRIMARY KEY,
  email       TEXT NOT NULL,
  kind        TEXT NOT NULL,            -- 'magic' | 'session'
  created_at  INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL,
  consumed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_device_sessions_email
  ON device_sessions (email, created_at);

CREATE TRIGGER IF NOT EXISTS devices_limit_insert
BEFORE INSERT ON devices
WHEN NEW.revoked_at IS NULL
 AND (SELECT COUNT(*) FROM devices
       WHERE license_id = NEW.license_id AND revoked_at IS NULL) >= 3
BEGIN
  SELECT RAISE(ABORT, 'device_limit_reached');
END;

CREATE TRIGGER IF NOT EXISTS devices_limit_reactivate
BEFORE UPDATE OF revoked_at ON devices
WHEN OLD.revoked_at IS NOT NULL
 AND NEW.revoked_at IS NULL
 AND (SELECT COUNT(*) FROM devices
       WHERE license_id = NEW.license_id
         AND revoked_at IS NULL
         AND device_id != NEW.device_id) >= 3
BEGIN
  SELECT RAISE(ABORT, 'device_limit_reached');
END;
