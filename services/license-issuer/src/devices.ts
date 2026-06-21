import { featuresForPlan } from "./features";
import { sendDeviceLoginEmail, sendDeviceNotification } from "./email";
import { type LicensePayload, signLicense, verifyLicense } from "./license";
import type { IssuerEnv } from "./types";

const DEVICE_LIMIT = 3;
const DAY = 86_400;
const REFRESH_DAYS = 30;
const OFFLINE_GRACE_DAYS = 7;
const MAX_BODY_BYTES = 16 * 1024;
const MAGIC_TTL_SECONDS = 15 * 60;
const SESSION_TTL_SECONDS = 30 * 60;
const MAGIC_COOLDOWN_SECONDS = 60;

type PurchaseRow = {
  license_id: string;
  email: string;
  plan: string;
  expires_at: number | null;
};

type DeviceRow = {
  device_id: string;
  name: string;
  created_at: number;
  last_seen_at: number;
};

type DeviceRecord = DeviceRow & {
  public_key: string;
  license_id: string;
  email: string;
  plan: string;
  purchase_expires_at: number | null;
};

export async function handleDeviceRequest(
  request: Request,
  env: IssuerEnv,
  ctx: ExecutionContext,
): Promise<Response | null> {
  const path = new URL(request.url).pathname;
  if (!path.startsWith("/devices/")) return null;

  const origin = allowedOrigin(env, request);
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsPreflight(origin) });
  }
  if (request.method !== "POST") {
    return cors(json({ error: "method_not_allowed" }, 405), origin);
  }

  try {
    const body = await readJson(request);
    let response: Response;
    switch (path) {
      case "/devices/activate":
        response = await activateDevice(body, env, ctx);
        break;
      case "/devices/refresh":
        response = await refreshDevice(body, env);
        break;
      case "/devices/remove":
        response = await removeDevice(body, env, ctx);
        break;
      case "/devices/list":
        response = await listOwnedDevices(body, env);
        break;
      case "/devices/session":
        response = await requestDeviceSession(body, env, ctx);
        break;
      case "/devices/session/verify":
        response = await verifyDeviceSession(body, env);
        break;
      case "/devices/session/list":
        response = await sessionDevices(body, env);
        break;
      case "/devices/session/remove":
        response = await sessionRemoveDevice(body, env, ctx);
        break;
      default:
        response = json({ error: "not_found" }, 404);
    }
    return cors(response, origin);
  } catch (error) {
    console.error(
      JSON.stringify({
        message: "device_request_failed",
        path,
        error: error instanceof Error ? error.message : String(error),
      }),
    );
    return cors(json({ error: "invalid_request" }, 400), origin);
  }
}

async function activateDevice(
  body: Record<string, unknown>,
  env: IssuerEnv,
  ctx: ExecutionContext,
): Promise<Response> {
  const purchaseToken = text(body.purchase_token, 4096);
  const publicKey = text(body.device_public_key, 128);
  const deviceName = text(body.device_name, 80);
  const proof = text(body.proof, 256);
  if (!purchaseToken || !publicKey || !deviceName || !proof) {
    return json({ error: "missing_fields" }, 400);
  }

  const purchase = await authenticatePurchase(purchaseToken, env);
  if (!purchase) return json({ error: "invalid_purchase_key" }, 401);
  if (
    !(await verifyDeviceProof(
      publicKey,
      proof,
      activationMessage(publicKey, deviceName),
    ))
  ) {
    return json({ error: "invalid_device_proof" }, 401);
  }

  const existing = await env.DB.prepare(
    "SELECT device_id, revoked_at FROM devices WHERE public_key = ? AND license_id = ?",
  )
    .bind(publicKey, purchase.license_id)
    .first<{ device_id: string; revoked_at: number | null }>();
  const deviceId =
    existing?.device_id ??
    `dev_${(await sha256Hex(`${purchase.license_id}\n${publicKey}`)).slice(0, 24)}`;
  const isNewActivation = !existing || existing.revoked_at !== null;
  if (!existing || existing.revoked_at !== null) {
    const active = await listDevices(env.DB, purchase.license_id);
    if (active.length >= DEVICE_LIMIT) {
      return json(
        { error: "device_limit_reached", limit: DEVICE_LIMIT, devices: active },
        409,
      );
    }
  }

  const now = unixNow();
  try {
    await env.DB.prepare(
      `INSERT INTO devices
         (device_id, license_id, public_key, name, created_at, last_seen_at, revoked_at)
       VALUES (?, ?, ?, ?, ?, ?, NULL)
       ON CONFLICT(device_id) DO UPDATE SET
         name = excluded.name,
         last_seen_at = excluded.last_seen_at,
         revoked_at = NULL`,
    )
      .bind(deviceId, purchase.license_id, publicKey, deviceName, now, now)
      .run();
  } catch (error) {
    if (String(error).includes("device_limit_reached")) {
      return json(
        {
          error: "device_limit_reached",
          limit: DEVICE_LIMIT,
          devices: await listDevices(env.DB, purchase.license_id),
        },
        409,
      );
    }
    throw error;
  }

  if (isNewActivation) {
    ctx.waitUntil(
      sendDeviceNotification(
        env.EMAIL,
        purchase.email,
        deviceName,
        "added",
      ).catch((error: unknown) =>
        console.error(
          JSON.stringify({
            message: "device_added_email_failed",
            error: error instanceof Error ? error.message : String(error),
          }),
        ),
      ),
    );
  }

  return json({
    device_token: await issueDeviceToken(env, purchase, deviceId, publicKey),
    devices: await listDevices(env.DB, purchase.license_id),
  });
}

async function refreshDevice(
  body: Record<string, unknown>,
  env: IssuerEnv,
): Promise<Response> {
  const token = text(body.device_token, 8192);
  if (!token) return json({ error: "missing_device_token" }, 400);
  let payload: LicensePayload;
  try {
    payload = await verifyLicense(token, env.LICENSE_PUBLIC_KEY);
  } catch {
    return json({ error: "invalid_device_token" }, 401);
  }
  if (
    payload.kind !== "device" ||
    !payload.device_id ||
    !payload.device_public_key
  ) {
    return json({ error: "invalid_device_token" }, 401);
  }

  const row = await env.DB.prepare(
    `SELECT d.device_id, d.public_key, d.license_id, d.name, d.created_at,
            d.last_seen_at, l.email, l.plan, l.expires_at AS purchase_expires_at
       FROM devices d
       JOIN licenses l ON l.license_id = d.license_id
      WHERE d.device_id = ?
        AND d.public_key = ?
        AND d.revoked_at IS NULL
        AND l.revoked = 0`,
  )
    .bind(payload.device_id, payload.device_public_key)
    .first<DeviceRecord>();
  if (
    !row ||
    (row.purchase_expires_at !== null && row.purchase_expires_at <= unixNow())
  ) {
    return json({ error: "device_not_active" }, 401);
  }

  await env.DB.prepare(
    "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
  )
    .bind(unixNow(), row.device_id)
    .run();
  return json({
    device_token: await issueDeviceToken(
      env,
      {
        license_id: row.license_id,
        email: row.email,
        plan: row.plan,
        expires_at: row.purchase_expires_at,
      },
      row.device_id,
      row.public_key,
    ),
  });
}

async function removeDevice(
  body: Record<string, unknown>,
  env: IssuerEnv,
  ctx: ExecutionContext,
): Promise<Response> {
  const purchaseToken = text(body.purchase_token, 4096);
  const deviceId = text(body.device_id, 64);
  if (!purchaseToken || !deviceId)
    return json({ error: "missing_fields" }, 400);
  const purchase = await authenticatePurchase(purchaseToken, env);
  if (!purchase) return json({ error: "invalid_purchase_key" }, 401);

  const selected = await env.DB.prepare(
    `SELECT name FROM devices
      WHERE device_id = ? AND license_id = ? AND revoked_at IS NULL`,
  )
    .bind(deviceId, purchase.license_id)
    .first<{ name: string }>();

  await env.DB.prepare(
    `UPDATE devices SET revoked_at = ?
      WHERE device_id = ? AND license_id = ? AND revoked_at IS NULL`,
  )
    .bind(unixNow(), deviceId, purchase.license_id)
    .run();
  if (selected) {
    ctx.waitUntil(
      sendDeviceNotification(
        env.EMAIL,
        purchase.email,
        selected.name,
        "removed",
      ).catch((error: unknown) =>
        console.error(
          JSON.stringify({
            message: "device_removed_email_failed",
            error: error instanceof Error ? error.message : String(error),
          }),
        ),
      ),
    );
  }
  return json({ devices: await listDevices(env.DB, purchase.license_id) });
}

// --- CLI: list devices for a stored purchase credential ----------------------

async function listOwnedDevices(
  body: Record<string, unknown>,
  env: IssuerEnv,
): Promise<Response> {
  const purchaseToken = text(body.purchase_token, 4096);
  if (!purchaseToken) return json({ error: "missing_fields" }, 400);
  const purchase = await authenticatePurchase(purchaseToken, env);
  if (!purchase) return json({ error: "invalid_purchase_key" }, 401);
  return json({ devices: await listDevices(env.DB, purchase.license_id) });
}

// --- Web: email magic-link device management ---------------------------------

async function requestDeviceSession(
  body: Record<string, unknown>,
  env: IssuerEnv,
  ctx: ExecutionContext,
): Promise<Response> {
  const email = normalizeEmail(body.email);
  // Respond identically for known and unknown addresses. All existence checks
  // and the email send happen AFTER the response (waitUntil), so response
  // latency cannot leak whether the address has a license.
  if (email) {
    ctx.waitUntil(
      maybeSendDeviceLink(env, email).catch((error: unknown) =>
        console.error(
          JSON.stringify({
            message: "device_login_email_failed",
            error: error instanceof Error ? error.message : String(error),
          }),
        ),
      ),
    );
  }
  return json({ ok: true }, 202);
}

async function maybeSendDeviceLink(
  env: IssuerEnv,
  email: string,
): Promise<void> {
  const now = unixNow();
  const recent = await env.DB.prepare(
    "SELECT 1 FROM device_sessions WHERE email = ? AND kind = 'magic' AND created_at > ? LIMIT 1",
  )
    .bind(email, now - MAGIC_COOLDOWN_SECONDS)
    .first();
  if (recent) return; // a fresh link was just sent; don't spam the inbox
  const license = await env.DB.prepare(
    `SELECT 1 FROM licenses
      WHERE lower(email) = ? AND revoked = 0
        AND (expires_at IS NULL OR expires_at > ?) LIMIT 1`,
  )
    .bind(email, now)
    .first();
  if (!license) return; // unknown address: send nothing
  const token = randomToken();
  await env.DB.prepare(
    `INSERT INTO device_sessions (token_hash, email, kind, created_at, expires_at, consumed_at)
     VALUES (?, ?, 'magic', ?, ?, NULL)`,
  )
    .bind(await sha256Hex(token), email, now, now + MAGIC_TTL_SECONDS)
    .run();
  const site = (env.SITE_URL ?? "").replace(/\/+$/, "");
  await sendDeviceLoginEmail({
    apiId: env.SENDPULSE_API_ID,
    apiSecret: env.SENDPULSE_API_SECRET,
    to: email,
    url: `${site}/license/devices?token=${encodeURIComponent(token)}`,
  });
}

async function verifyDeviceSession(
  body: Record<string, unknown>,
  env: IssuerEnv,
): Promise<Response> {
  const token = text(body.token, 512);
  if (!token) return json({ error: "missing_token" }, 400);
  const now = unixNow();
  const tokenHash = await sha256Hex(token);
  const magic = await env.DB.prepare(
    `SELECT email FROM device_sessions
      WHERE token_hash = ? AND kind = 'magic'
        AND consumed_at IS NULL AND expires_at > ?`,
  )
    .bind(tokenHash, now)
    .first<{ email: string }>();
  if (!magic) return json({ error: "invalid_or_expired" }, 401);
  await env.DB.prepare(
    "UPDATE device_sessions SET consumed_at = ? WHERE token_hash = ?",
  )
    .bind(now, tokenHash)
    .run();
  const session = randomToken();
  await env.DB.prepare(
    `INSERT INTO device_sessions (token_hash, email, kind, created_at, expires_at, consumed_at)
     VALUES (?, ?, 'session', ?, ?, NULL)`,
  )
    .bind(await sha256Hex(session), magic.email, now, now + SESSION_TTL_SECONDS)
    .run();
  return json({
    session,
    email: magic.email,
    devices: await listDevicesForEmail(env.DB, magic.email),
  });
}

async function sessionDevices(
  body: Record<string, unknown>,
  env: IssuerEnv,
): Promise<Response> {
  const email = await resolveSessionEmail(body, env);
  if (!email) return json({ error: "invalid_session" }, 401);
  return json({ email, devices: await listDevicesForEmail(env.DB, email) });
}

async function sessionRemoveDevice(
  body: Record<string, unknown>,
  env: IssuerEnv,
  ctx: ExecutionContext,
): Promise<Response> {
  const email = await resolveSessionEmail(body, env);
  if (!email) return json({ error: "invalid_session" }, 401);
  const deviceId = text(body.device_id, 64);
  if (!deviceId) return json({ error: "missing_fields" }, 400);
  const selected = await env.DB.prepare(
    `SELECT d.name FROM devices d JOIN licenses l ON l.license_id = d.license_id
      WHERE d.device_id = ? AND lower(l.email) = ? AND d.revoked_at IS NULL`,
  )
    .bind(deviceId, email)
    .first<{ name: string }>();
  await env.DB.prepare(
    `UPDATE devices SET revoked_at = ?
      WHERE device_id = ? AND revoked_at IS NULL
        AND license_id IN (SELECT license_id FROM licenses WHERE lower(email) = ?)`,
  )
    .bind(unixNow(), deviceId, email)
    .run();
  if (selected) {
    ctx.waitUntil(
      sendDeviceNotification(env.EMAIL, email, selected.name, "removed").catch(
        (error: unknown) =>
          console.error(
            JSON.stringify({
              message: "device_removed_email_failed",
              error: error instanceof Error ? error.message : String(error),
            }),
          ),
      ),
    );
  }
  return json({ email, devices: await listDevicesForEmail(env.DB, email) });
}

async function resolveSessionEmail(
  body: Record<string, unknown>,
  env: IssuerEnv,
): Promise<string | null> {
  const session = text(body.session, 512);
  if (!session) return null;
  const row = await env.DB.prepare(
    `SELECT email FROM device_sessions
      WHERE token_hash = ? AND kind = 'session'
        AND consumed_at IS NULL AND expires_at > ?`,
  )
    .bind(await sha256Hex(session), unixNow())
    .first<{ email: string }>();
  return row?.email ?? null;
}

async function listDevicesForEmail(
  db: D1Database,
  email: string,
): Promise<DeviceRow[]> {
  const rows = await db
    .prepare(
      `SELECT d.device_id, d.name, d.created_at, d.last_seen_at
         FROM devices d JOIN licenses l ON l.license_id = d.license_id
        WHERE lower(l.email) = ? AND l.revoked = 0 AND d.revoked_at IS NULL
        ORDER BY d.last_seen_at DESC`,
    )
    .bind(email)
    .all<DeviceRow>();
  return rows.results;
}

function normalizeEmail(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const email = value.trim().toLowerCase();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 254
    ? email
    : null;
}

function randomToken(): string {
  return toBase64Url(crypto.getRandomValues(new Uint8Array(32)));
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function allowedOrigin(env: IssuerEnv, request: Request): string | null {
  const origin = request.headers.get("Origin");
  if (!origin) return null;
  const site = (env.SITE_URL ?? "").replace(/\/+$/, "");
  if (!site) return null;
  const allowed = new Set([site, site.replace("://", "://www.")]);
  return allowed.has(origin) ? origin : null;
}

function cors(response: Response, origin: string | null): Response {
  if (!origin) return response;
  const next = new Response(response.body, response);
  next.headers.set("Access-Control-Allow-Origin", origin);
  next.headers.set("Vary", "Origin");
  return next;
}

function corsPreflight(origin: string | null): Record<string, string> {
  const headers: Record<string, string> = {
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
  if (origin) {
    headers["Access-Control-Allow-Origin"] = origin;
    headers["Vary"] = "Origin";
  }
  return headers;
}

async function authenticatePurchase(
  token: string,
  env: IssuerEnv,
): Promise<PurchaseRow | null> {
  let payload: LicensePayload;
  try {
    payload = await verifyLicense(token, env.LICENSE_PUBLIC_KEY);
  } catch {
    return null;
  }
  if (payload.kind !== "purchase") return null;
  return env.DB.prepare(
    `SELECT license_id, email, plan, expires_at
       FROM licenses
      WHERE license_id = ? AND revoked = 0
        AND (expires_at IS NULL OR expires_at > ?)`,
  )
    .bind(payload.id, unixNow())
    .first<PurchaseRow>();
}

async function issueDeviceToken(
  env: IssuerEnv,
  purchase: PurchaseRow,
  deviceId: string,
  publicKey: string,
): Promise<string> {
  const now = unixNow();
  const refreshAt = now + REFRESH_DAYS * DAY;
  const leaseEnd = now + (REFRESH_DAYS + OFFLINE_GRACE_DAYS) * DAY;
  const expiresAt =
    purchase.expires_at === null
      ? leaseEnd
      : Math.min(leaseEnd, purchase.expires_at);
  return signLicense(
    {
      v: 1,
      id: purchase.license_id,
      email: purchase.email,
      plan: purchase.plan,
      iat: now,
      exp: expiresAt,
      features: featuresForPlan(purchase.plan),
      kind: "device",
      device_id: deviceId,
      device_public_key: publicKey,
      refresh_at: Math.min(refreshAt, expiresAt),
    },
    env.LICENSE_PRIVATE_KEY,
  );
}

async function listDevices(
  db: D1Database,
  licenseId: string,
): Promise<DeviceRow[]> {
  const rows = await db
    .prepare(
      `SELECT device_id, name, created_at, last_seen_at
       FROM devices
      WHERE license_id = ? AND revoked_at IS NULL
      ORDER BY last_seen_at DESC`,
    )
    .bind(licenseId)
    .all<DeviceRow>();
  return rows.results;
}

function activationMessage(publicKey: string, name: string): string {
  return `atelier-device-activate-v1\n${publicKey}\n${name}`;
}

async function verifyDeviceProof(
  publicKeyB64: string,
  proofB64: string,
  message: string,
): Promise<boolean> {
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      fromBase64(publicKeyB64),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    return crypto.subtle.verify(
      "Ed25519",
      key,
      fromBase64(proofB64),
      new TextEncoder().encode(message),
    );
  } catch {
    return false;
  }
}

async function readJson(request: Request): Promise<Record<string, unknown>> {
  const textBody = await readBoundedText(request, MAX_BODY_BYTES);
  const parsed: unknown = JSON.parse(textBody);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("invalid_json");
  }
  return parsed as Record<string, unknown>;
}

async function readBoundedText(
  request: Request,
  maxBytes: number,
): Promise<string> {
  const declared = Number(request.headers.get("Content-Length") ?? "0");
  if (declared > maxBytes) throw new Error("request_too_large");
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      throw new Error("request_too_large");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

function text(value: unknown, max: number): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= max
    ? value
    : null;
}

function fromBase64(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(
    normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="),
  );
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function unixNow(): number {
  return Math.floor(Date.now() / 1000);
}

function json(body: unknown, status = 200): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
