"""Offline Ed25519 verification of Atelier license tokens.

Token format -- two base64url segments (no padding) joined by ``.``::

    <b64url(payload_json)>.<b64url(signature)>

The signature covers the *exact ASCII bytes* of the first segment
(detached-JWS style), so verification never depends on re-serializing the JSON.
The trusted public key is embedded below at release time; it can be overridden
via the ``ATELIER_LICENSE_PUBLIC_KEY`` env var (base64 of the 32 raw bytes) for
testing or self-issued keys.
"""

from __future__ import annotations

import base64
import binascii
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from atelier.core.capabilities.licensing.models import TOKEN_VERSION, License, LicenseError

# Base64 (standard) of the 32-byte Ed25519 public key the issuer signs with.
# Filled in at release time from `services/license-issuer/scripts/keygen.mjs`.
# Empty means "no trusted key baked into this build" -> verification fails closed
# unless the env override is set.
_EMBEDDED_PUBLIC_KEY_B64 = ""

_PUBLIC_KEY_ENV = "ATELIER_LICENSE_PUBLIC_KEY"


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + pad)
    except (binascii.Error, ValueError) as exc:
        raise LicenseError("license token is not valid base64url") from exc


def configured_public_key_b64() -> str:
    return os.environ.get(_PUBLIC_KEY_ENV, "").strip() or _EMBEDDED_PUBLIC_KEY_B64


def public_key_configured() -> bool:
    return bool(configured_public_key_b64())


def _load_public_key() -> Ed25519PublicKey:
    raw_b64 = configured_public_key_b64()
    if not raw_b64:
        raise LicenseError("no license public key configured")
    try:
        raw = base64.b64decode(raw_b64)
    except (binascii.Error, ValueError) as exc:
        raise LicenseError("configured public key is not valid base64") from exc
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise LicenseError("configured public key is not a valid Ed25519 key") from exc


def verify_token(token: str) -> License:
    """Verify ``token`` and return the parsed :class:`License`.

    Raises :class:`LicenseError` on any malformed, unsigned, untrusted, or
    unsupported token. Does *not* check expiry -- callers decide how to treat a
    signed-but-expired token.
    """
    token = token.strip()
    parts = token.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise LicenseError("license token must have the form <payload>.<signature>")
    payload_b64, sig_b64 = parts

    public_key = _load_public_key()
    signature = _b64url_decode(sig_b64)
    try:
        public_key.verify(signature, payload_b64.encode("ascii"))
    except InvalidSignature as exc:
        raise LicenseError("license signature is not valid") from exc

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LicenseError("license payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LicenseError("license payload must be a JSON object")

    version = payload.get("v")
    if version != TOKEN_VERSION:
        raise LicenseError(f"unsupported license version: {version!r}")

    try:
        return License(
            license_id=str(payload["id"]),
            email=str(payload["email"]),
            plan=str(payload["plan"]),
            issued_at=int(payload["iat"]),
            expires_at=None if payload.get("exp") is None else int(payload["exp"]),
            features=tuple(str(f) for f in payload.get("features", ())),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseError("license payload is missing required fields") from exc
