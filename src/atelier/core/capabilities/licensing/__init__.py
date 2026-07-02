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

import os

from atelier.core.capabilities.licensing.device import DeviceInfo, DeviceLimitError
from atelier.core.capabilities.licensing.entitlements import (
    current_license,
    feature_active,
    has_feature,
    is_pro,
    pro_available,
    pro_impl,
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

_DEFAULT_PRO_URL = "https://atelier.ws/pro"


def pro_url() -> str:
    """Where to send users to buy Pro.

    Override with ``ATELIER_PRO_URL`` to point straight at your Stripe Payment
    Link (or any storefront) without rebuilding the client.
    """
    return os.environ.get("ATELIER_PRO_URL", "").strip() or _DEFAULT_PRO_URL


def activate(token: str, *, device_name: str | None = None) -> License:
    """Verify ``token``, persist it, and refresh the entitlement cache.

    Verifies the signature only -- an already-expired (but authentic) token is
    still stored; callers should inspect :func:`status` to surface expiry.
    """
    from atelier.core.capabilities.licensing import store as _store

    lic = verify_token(token)
    activated_token = token
    if lic.kind == "purchase":
        from atelier.core.capabilities.licensing.device import activate_purchase, matches_device

        activated_token = activate_purchase(token, name=device_name)
        lic = verify_token(activated_token)
        if lic.kind != "device" or not matches_device(lic.device_public_key):
            raise LicenseError("issuer returned a token for a different device")
    elif lic.kind == "device":
        from atelier.core.capabilities.licensing.device import matches_device

        if not matches_device(lic.device_public_key):
            raise LicenseError("license belongs to another device")
    _store.save_token(activated_token)
    reload()
    return lic


def remove_device(purchase_token: str, device_id: str) -> tuple[DeviceInfo, ...]:
    from atelier.core.capabilities.licensing.device import remove_device as _remove_device

    return _remove_device(purchase_token, device_id)


def list_devices(purchase_token: str) -> tuple[DeviceInfo, ...]:
    from atelier.core.capabilities.licensing.device import list_devices as _list_devices

    return _list_devices(purchase_token)


def stored_purchase_token() -> str | None:
    """Return the purchase credential saved at activation, if present."""
    from atelier.core.capabilities.licensing.device import load_purchase_token

    return load_purchase_token()


def deactivate() -> bool:
    """Remove the stored token and refresh the cache. Returns True if removed."""
    removed = delete_token()
    reload()
    return removed


__all__ = [
    "PRO_FEATURES",
    "DeviceInfo",
    "DeviceLimitError",
    "FeatureLocked",
    "License",
    "LicenseError",
    "LicenseStatus",
    "activate",
    "current_license",
    "deactivate",
    "delete_token",
    "feature_active",
    "has_feature",
    "is_pro",
    "license_path",
    "list_devices",
    "load_token",
    "pro_available",
    "pro_impl",
    "pro_url",
    "reload",
    "remove_device",
    "require",
    "status",
    "stored_purchase_token",
    "verify_token",
]
