// Generate an Ed25519 keypair for the Atelier license issuer.
//
//   node scripts/keygen.mjs
//
// Outputs:
//   * LICENSE_PRIVATE_KEY  -> set as a Worker SECRET (never commit it)
//   * LICENSE_PUBLIC_KEY   -> paste into the Python client + wrangler var
//
// Run once. Store the private key in a password manager; if you lose it you
// must re-issue every customer's license.

import { generateKeyPairSync } from "node:crypto";

const { publicKey, privateKey } = generateKeyPairSync("ed25519");

// PKCS#8 DER, base64 -> importable by Web Crypto in the Worker.
const pkcs8B64 = privateKey
  .export({ type: "pkcs8", format: "der" })
  .toString("base64");

// SPKI DER ends with the raw 32-byte public key; that raw form is what
// cryptography.Ed25519PublicKey.from_public_bytes() expects on the client.
const spki = publicKey.export({ type: "spki", format: "der" });
const rawPubB64 = spki.subarray(spki.length - 32).toString("base64");

console.log("=== Atelier license keypair ===\n");
console.log("1) Private key (Worker secret). Run:\n");
console.log(
  `   echo '${pkcs8B64}' | npx wrangler secret put LICENSE_PRIVATE_KEY\n`,
);
console.log("2) Public key (raw, base64). Two places:\n");
console.log(
  `   a. wrangler.jsonc  ->  vars.LICENSE_PUBLIC_KEY = "${rawPubB64}"`,
);
console.log(
  "   b. src/atelier/core/capabilities/licensing/verify.py  ->  " +
    `_EMBEDDED_PUBLIC_KEY_B64 = "${rawPubB64}"\n`,
);
console.log(
  "Keep the private key safe. Anyone with it can mint Atelier Pro licenses.",
);
