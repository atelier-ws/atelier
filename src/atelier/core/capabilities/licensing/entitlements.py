"""The entitlement contract every Pro gate calls.

Single source of truth for "is this feature unlocked?". Loads the active token
(env or file), verifies it offline, enforces expiry, and answers ``is_pro`` /
``has_feature`` / ``require``. Results are cached per-token so the hot path pays
the Ed25519 cost at most once per distinct token.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from atelier.core.capabilities.licensing import store
from atelier.core.capabilities.licensing.features import PRO_FEATURES, describe
from atelier.core.capabilities.licensing.models import (
    PRO_PLANS,
    FeatureLocked,
    License,
    LicenseError,
    LicenseStatus,
)
from atelier.core.capabilities.licensing.verify import public_key_configured, verify_token


@dataclass
class _Resolved:
    token: str | None
    license: License | None
    reason: str


_cache: _Resolved | None = None


def reload() -> None:
    """Drop the cached entitlement state (call after activate/deactivate)."""
    global _cache
    _cache = None


def _now() -> int:
    return int(time.time())


def _resolve() -> _Resolved:
    global _cache
    token = store.load_token()
    if _cache is not None and _cache.token == token:
        return _cache
    if token is None:
        _cache = _Resolved(token=None, license=None, reason="no license activated")
        return _cache
    try:
        lic = verify_token(token)
    except LicenseError as exc:
        _cache = _Resolved(token=token, license=None, reason=str(exc))
        return _cache
    if lic.is_expired(now=_now()):
        _cache = _Resolved(token=token, license=None, reason="license expired")
        return _cache
    _cache = _Resolved(token=token, license=lic, reason="active")
    return _cache


def current_license() -> License | None:
    return _resolve().license


def is_pro() -> bool:
    lic = current_license()
    return lic is not None and lic.plan in PRO_PLANS


def has_feature(feature: str) -> bool:
    """True if ``feature`` is unlocked. Non-Pro features are always allowed."""
    if feature not in PRO_FEATURES:
        return True
    lic = current_license()
    return lic is not None and lic.grants(feature)


def require(feature: str) -> None:
    """Raise :class:`FeatureLocked` unless ``feature`` is unlocked."""
    if not has_feature(feature):
        raise FeatureLocked(feature, f"{describe(feature)} requires Atelier Pro")


def status() -> LicenseStatus:
    resolved = _resolve()
    if os.environ.get(store.LICENSE_ENV_VAR, "").strip():
        source = "env"
    elif store.license_path().exists():
        source = "file"
    else:
        source = "none"

    lic = resolved.license
    if lic is not None:
        return LicenseStatus(
            licensed=True,
            valid=True,
            plan=lic.plan,
            email=lic.email,
            expires_at=lic.expires_at,
            features=lic.features or tuple(PRO_FEATURES),
            reason="active",
            source=source,
        )

    reason = resolved.reason
    if resolved.token is not None and not public_key_configured():
        reason = "this build has no license public key configured"
    return LicenseStatus(
        licensed=resolved.token is not None,
        valid=False,
        plan=None,
        email=None,
        expires_at=None,
        features=(),
        reason=reason,
        source=source,
    )
