"""The entitlement contract every Pro gate calls.

Single source of truth for "is this feature unlocked?". Loads the active token,
verifies it locally, enforces expiry, refreshes device leases when due, and
answers ``is_pro`` / ``has_feature`` / ``require``. Results are cached until the
next time-sensitive lease boundary.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from types import ModuleType

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
    next_check_at: int | None = None


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
    now = _now()
    if _cache is not None and _cache.token == token and (_cache.next_check_at is None or now < _cache.next_check_at):
        return _cache
    if token is None:
        _cache = _Resolved(token=None, license=None, reason="no license activated")
        return _cache
    try:
        lic = verify_token(token)
    except LicenseError as exc:
        _cache = _Resolved(token=token, license=None, reason=str(exc))
        return _cache
    if lic.kind == "purchase":
        _cache = _Resolved(token=token, license=None, reason="purchase key must be activated on this device")
        return _cache
    refresh_retry_at: int | None = None
    if lic.kind == "device":
        from atelier.core.capabilities.licensing.device import matches_device, refresh_device

        if not matches_device(lic.device_public_key):
            _cache = _Resolved(token=token, license=None, reason="license belongs to another device")
            return _cache
        if (
            lic.refresh_at is not None
            and now >= lic.refresh_at
            and not os.environ.get(store.LICENSE_ENV_VAR, "").strip()
        ):
            try:
                token = refresh_device(token)
                store.save_token(token)
                lic = verify_token(token)
            except LicenseError:
                refresh_retry_at = now + 3600
    if lic.is_expired(now=now):
        _cache = _Resolved(token=token, license=None, reason="license expired")
        return _cache
    boundaries = [value for value in (lic.expires_at, refresh_retry_at) if value is not None]
    if lic.refresh_at is not None and lic.refresh_at > now:
        boundaries.append(lic.refresh_at)
    _cache = _Resolved(
        token=token,
        license=lic,
        reason="active",
        next_check_at=min(boundaries) if boundaries else None,
    )
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


def feature_active(feature: str) -> bool:
    """True only when ``feature`` is BOTH licensed and physically installed.

    A Pro feature requires a valid license that grants it *and* the proprietary
    ``atelier_pro`` overlay (the code that actually runs it). If either is
    missing the caller falls back to Free behavior -- silently. Free features are
    always active.
    """
    if not has_feature(feature):
        return False
    if feature not in PRO_FEATURES:
        return True
    from atelier.core.capabilities import pro_bridge

    return pro_bridge.provides(feature)


def pro_impl(feature: str) -> ModuleType | None:
    """Return the ``atelier_pro`` implementation module for ``feature``.

    ``None`` means the Pro overlay is not installed (or does not provide this
    feature) -- the caller must fall back to Free behavior. Pair with
    :func:`require` (license) so a leaked overlay can't run without a key.
    """
    if feature not in PRO_FEATURES:
        return None
    from atelier.core.capabilities import pro_bridge

    if not pro_bridge.provides(feature):
        return None
    return pro_bridge.load(feature)


def pro_available() -> bool:
    """True if the proprietary Pro overlay package is importable."""
    from atelier.core.capabilities import pro_bridge

    return pro_bridge.available()


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
