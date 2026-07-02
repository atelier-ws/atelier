"""The entitlement contract every Pro gate calls.

Single source of truth for "is this feature unlocked?". The only entitlement
source is the OAuth session created by ``atelier login``: the auth server
reports the account's plan via ``/api/auth/me``, cached on disk for 24 h.
Results are cached in-process until the next cache boundary.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from atelier.core.capabilities.licensing import store
from atelier.core.capabilities.licensing.features import PRO_FEATURES, describe
from atelier.core.capabilities.licensing.models import (
    PRO_PLANS,
    FeatureLocked,
    License,
    LicenseStatus,
)

_OFFLINE_RETRY_SECONDS = 3600


@dataclass
class _Resolved:
    token: str | None
    license: License | None
    reason: str
    next_check_at: int | None = None


_cache: _Resolved | None = None


def reload() -> None:
    """Drop the cached entitlement state (call after login/logout)."""
    global _cache
    _cache = None


def _now() -> int:
    return int(time.time())


def _fetch_auth_user(auth_token: str) -> dict[str, object] | None:
    """Fetch ``/api/auth/me`` (also renews the server-side CLI token) and cache it.

    Returns ``None`` on any failure -- the caller decides how to degrade.
    """
    import json
    import urllib.request

    try:
        req = urllib.request.Request(
            f"{store.load_auth_base()}/api/auth/me",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    store.save_auth_user(data)
    return data


def _resolve() -> _Resolved:
    global _cache
    token = store.load_auth_token()
    now = _now()
    if _cache is not None and _cache.token == token and (_cache.next_check_at is None or now < _cache.next_check_at):
        return _cache
    if token is None:
        _cache = _Resolved(token=None, license=None, reason="not signed in")
        return _cache
    data = store.load_auth_user()
    if data is None:
        data = _fetch_auth_user(token)
    if data is None:
        _cache = _Resolved(
            token=token,
            license=None,
            reason="could not verify the subscription (offline?)",
            next_check_at=now + _OFFLINE_RETRY_SECONDS,
        )
        return _cache
    plan = str(data.get("plan") or "free")
    if plan not in PRO_PLANS:
        _cache = _Resolved(
            token=token,
            license=None,
            reason="signed in on the free plan",
            next_check_at=now + store.AUTH_USER_CACHE_TTL,
        )
        return _cache
    lic = License(
        license_id=str(data.get("user_id") or ""),
        email=str(data.get("email") or ""),
        plan=plan,
    )
    _cache = _Resolved(token=token, license=lic, reason="active", next_check_at=now + store.AUTH_USER_CACHE_TTL)
    return _cache


def current_license() -> License | None:
    return _resolve().license


def is_pro() -> bool:
    lic = current_license()
    return lic is not None and lic.plan in PRO_PLANS


def _detect_pro_source_tree() -> bool:
    """True only in a source monorepo: the proprietary overlay SOURCE tree
    (``pro/src/atelier_pro``) is checked out next to the core."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pro" / "src" / "atelier_pro" / "__init__.py").is_file():
            return True
    return False


_PRO_SOURCE_TREE = _detect_pro_source_tree()


def _dev_unlock() -> bool:
    """Dev affordance with NO production attack surface.

    Unlocks Pro only in a source monorepo, detected by the proprietary overlay
    SOURCE tree (``pro/src/atelier_pro``) sitting next to the core. There is
    deliberately **no env var or config flag** -- so a distributed build cannot be
    tricked into unlocking Pro. A distributed build never has that source tree:
    the OSS snapshot strips ``pro/`` entirely, and the Pro wheel installs
    ``atelier_pro`` into site-packages (never as ``<repo>/pro/src``). To unlock
    one would need the proprietary source itself -- at which point the license is
    moot anyway. Suppressed under the test runner so the licensing suite still
    exercises real gating.
    """
    if "pytest" in sys.modules:
        return False
    return _PRO_SOURCE_TREE


def has_feature(feature: str) -> bool:
    """True if ``feature`` is unlocked. Non-Pro features are always allowed."""
    if feature not in PRO_FEATURES:
        return True
    if _dev_unlock():
        return True
    lic = current_license()
    return lic is not None and lic.grants(feature)


def require(feature: str) -> None:
    """Raise :class:`FeatureLocked` unless ``feature`` is unlocked."""
    if not has_feature(feature):
        raise FeatureLocked(feature, f"{describe(feature)} requires Atelier Pro")


def feature_active(feature: str) -> bool:
    """True only when ``feature`` is BOTH licensed and physically installed.

    A Pro feature requires a plan that grants it *and* the proprietary
    ``atelier_pro`` overlay (the code that actually runs it). If either is
    missing the caller falls back to Free behavior -- silently. Free features are
    always active.
    """
    if not has_feature(feature):
        return False
    if feature not in PRO_FEATURES:
        return True
    if _dev_unlock():
        # Dev: skip the overlay-presence half too, so source checkouts run Pro
        # paths whose runtime is in the open-core (e.g. swarm) without the wheel.
        return True
    from atelier.core.capabilities import pro_bridge

    return pro_bridge.provides(feature)


def pro_impl(feature: str) -> ModuleType | None:
    """Return the ``atelier_pro`` implementation module for ``feature``.

    ``None`` means the Pro overlay is not installed (or does not provide this
    feature) -- the caller must fall back to Free behavior. Pair with
    :func:`require` (plan) so a leaked overlay can't run without a Pro account.
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
    if os.environ.get(store.AUTH_TOKEN_ENV_VAR, "").strip():
        source = "env"
    elif store.auth_token_path().exists():
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
            features=lic.features or tuple(PRO_FEATURES),
            reason="active",
            source=source,
        )
    return LicenseStatus(
        licensed=resolved.token is not None,
        valid=False,
        plan=None,
        email=None,
        features=(),
        reason=resolved.reason,
        source=source,
    )
