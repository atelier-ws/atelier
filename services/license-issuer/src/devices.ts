import { featuresForPlan } from "./features";
import { sendDeviceNotification } from "./email";
import { type LicensePayload, signLicense, verifyLicense } from "./license";
import type { IssuerEnv } from "./types";

const DEVICE_LIMIT = 3;
const DAY = 86_400;
const REFRESH_DAYS = 30;
const OFFLINE_GRACE_DAYS = 7;
const MAX_BODY_BYTES = 16 * 1024;

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
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  try {
    const body = await readJson(request);
    if (path === "/devices/activate") return activateDevice(body, env, ctx);
    if (path === "/devices/refresh") return refreshDevice(body, env);
    if (path === "/devices/remove") return removeDevice(body, env, ctx);
    return json({ error: "not_found" }, 404);
  } catch (error) {
    console.error(
      JSON.stringify({
        message: "device_request_failed",
        path,
        error: error instanceof Error ? error.message : String(error),
      }),
    );
    return json({ error: "invalid_request" }, 400);
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
  if (!(await verifyDeviceProof(publicKey, proof, activationMessage(publicKey, deviceName)))) {
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
      return json({ error: "device_limit_reached", limit: DEVICE_LIMIT, devices: active }, 409);
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
      return json({
        error: "device_limit_reached",
        limit: DEVICE_LIMIT,
        devices: await listDevices(env.DB, purchase.license_id),
      }, 409);
    }
    throw error;
  }

  if (isNewActivation) {
    ctx.waitUntil(
      sendDeviceNotification(env.EMAIL, purchase.email, deviceName, "added").catch(
        (error: unknown) =>
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
  if (!row || (row.purchase_expires_at !== null && row.purchase_expires_at <= unixNow())) {
    return json({ error: "device_not_active" }, 401);
  }

  await env.DB.prepare("UPDATE devices SET last_seen_at = ? WHERE device_id = ?")
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
  if (!purchaseToken || !deviceId) return json({ error: "missing_fields" }, 400);
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
      sendDeviceNotification(env.EMAIL, purchase.email, selected.name, "removed").catch(
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
  return json({ devices: await listDevices(env.DB, purchase.license_id) });
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
    purchase.expires_at === null ? leaseEnd : Math.min(leaseEnd, purchase.expires_at);
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

async function listDevices(db: D1Database, licenseId: string): Promise<DeviceRow[]> {
  const rows = await db.prepare(
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

async function readBoundedText(request: Request, maxBytes: number): Promise<string> {
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
  const binary = atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
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
    headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}
