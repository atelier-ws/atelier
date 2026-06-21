"""Data models for the Atelier licensing layer.

A *license* is a short, signed token a customer pastes via ``atelier license
activate``. Activation exchanges that purchase credential for a device-bound,
Ed25519-signed lease. Lease verification remains local; the client contacts the
issuer periodically to refresh it. The signing key lives only in the issuer (a
Cloudflare Worker); the public key is embedded in the client.
"""

from __future__ import annotations

from dataclasses import dataclass

# Plans that unlock the paid capability set. ``enterprise`` is a superset of
# ``pro`` for entitlement purposes; the per-license ``features`` list does the
# tier-specific narrowing (a Pro token omits the Enterprise-only keys).
PRO_PLANS: frozenset[str] = frozenset({"pro", "enterprise"})

# Bump when the token payload shape changes incompatibly.
TOKEN_VERSION = 1


class LicenseError(Exception):
    """Raised when a license token is malformed, unsigned, or untrusted."""


class FeatureLocked(Exception):
    """Raised when a Pro-only feature is used without a valid license.

    Carries the offending ``feature`` key so callers can render a precise
    upgrade prompt.
    """

    def __init__(self, feature: str, message: str | None = None) -> None:
        self.feature = feature
        super().__init__(message or f"'{feature}' requires an Atelier Pro license")


@dataclass(frozen=True)
class License:
    """A verified license payload.

    Instances are only ever constructed *after* signature verification, so a
    ``License`` in hand always means the token was signed by the trusted issuer.
    Expiry is enforced separately (a signed-but-expired token still parses).
    """

    license_id: str
    email: str
    plan: str
    issued_at: int
    expires_at: int | None
    features: tuple[str, ...] = ()
    kind: str = "legacy"
    device_id: str | None = None
    device_public_key: str | None = None
    refresh_at: int | None = None

    def is_expired(self, *, now: int) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def grants(self, feature: str) -> bool:
        """Whether this license grants ``feature`` (empty ``features`` = all)."""
        if self.kind == "purchase":
            return False
        if not self.features:
            return self.plan in PRO_PLANS
        return feature in self.features


@dataclass(frozen=True)
class LicenseStatus:
    """A flattened, render-ready view of the current entitlement state."""

    licensed: bool
    valid: bool
    plan: str | None
    email: str | None
    expires_at: int | None
    features: tuple[str, ...]
    reason: str
    source: str
