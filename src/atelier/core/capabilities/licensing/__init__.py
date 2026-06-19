"""Atelier licensing -- offline, signed Pro entitlements (open-core split).

The open-source core ships every capability. This package is the *gate*: a
feature key is either free (always allowed) or Pro (allowed only with a valid,
signed, unexpired license). Verification is offline Ed25519 -- the private
signing key lives only in the Cloudflare issuer under ``services/``.

Public API::

    from atelier.core.capabilities import licensing
    licensing.is_pro()
    licensing.require("optimizer")        # raises FeatureLocked if not unlocked
    licensing.activate(token)             # verify + persist
"""

from __future__ import annotations

from atelier.core.capabilities.licensing.entitlements import (
    current_license,
    has_feature,
    is_pro,
    reload,
    require,
    status,
)
from atelier.core.capabilities.licensing.features import PRO_FEATURES
from atelier.core.capabilities.licensing.models import (
    FeatureLocked,
    License,
    LicenseError,
    LicenseStatus,
)
from atelier.core.capabilities.licensing.store import delete_token, license_path, load_token
from atelier.core.capabilities.licensing.verify import verify_token


def activate(token: str) -> License:
    """Verify ``token``, persist it, and refresh the entitlement cache.

    Verifies the signature only -- an already-expired (but authentic) token is
    still stored; callers should inspect :func:`status` to surface expiry.
    """
    from atelier.core.capabilities.licensing import store as _store

    lic = verify_token(token)
    _store.save_token(token)
    reload()
    return lic


def deactivate() -> bool:
    """Remove the stored token and refresh the cache. Returns True if removed."""
    removed = delete_token()
    reload()
    return removed


__all__ = [
    "PRO_FEATURES",
    "FeatureLocked",
    "License",
    "LicenseError",
    "LicenseStatus",
    "activate",
    "current_license",
    "deactivate",
    "delete_token",
    "has_feature",
    "is_pro",
    "license_path",
    "load_token",
    "reload",
    "require",
    "status",
    "verify_token",
]
