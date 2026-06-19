/** Ed25519 license signing using the Workers Web Crypto API.
 *
 * Token format mirrors the Python verifier in
 * `src/atelier/core/capabilities/licensing/verify.py`:
 *
 *     <b64url(payload_json)>.<b64url(signature)>
 *
 * The signature covers the ASCII bytes of the first segment, so the verifier
 * never re-serializes the JSON.
 */

export interface LicensePayload {
  v: number;
  id: string;
  email: string;
  plan: string;
  iat: number;
  exp: number | null;
  features: string[];
}

function b64urlEncode(input: ArrayBuffer | Uint8Array): string {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function importPrivateKey(pkcs8B64: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "pkcs8",
    b64ToBytes(pkcs8B64),
    { name: "Ed25519" },
    false,
    ["sign"],
  );
}

export async function signLicense(
  payload: LicensePayload,
  privateKeyPkcs8B64: string,
): Promise<string> {
  const payloadB64 = b64urlEncode(
    new TextEncoder().encode(JSON.stringify(payload)),
  );
  const key = await importPrivateKey(privateKeyPkcs8B64);
  const sig = await crypto.subtle.sign(
    { name: "Ed25519" },
    key,
    new TextEncoder().encode(payloadB64),
  );
  return `${payloadB64}.${b64urlEncode(sig)}`;
}
