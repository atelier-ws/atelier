"""Tests for the soft Pro-overlay bridge and its entitlement integration.

The public suite must pass *without* the proprietary ``atelier_pro`` package
installed, so these tests synthesize a fake overlay in ``sys.modules`` to drive
the "installed" path and remove it to drive the Free path.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atelier.core.capabilities import licensing, pro_bridge
from atelier.core.capabilities.licensing import entitlements

_REAL_OVERLAY_INSTALLED = importlib.util.find_spec("atelier_pro") is not None


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _make_token(priv: Ed25519PrivateKey, **overrides: object) -> str:
    payload: dict[str, object] = {
        "v": 1,
        "id": "lic_test",
        "email": "dev@example.com",
        "plan": "pro",
        "iat": int(time.time()) - 10,
        "exp": None,
        "features": [],
    }
    payload.update(overrides)
    payload_b64 = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = priv.sign(payload_b64.encode("ascii"))
    return f"{payload_b64}.{_b64u(sig)}"


def _install_fake_overlay(features: set[str]) -> None:
    """Register a fake ``atelier_pro`` (and ``atelier_pro.optimizer``)."""
    pkg = types.ModuleType("atelier_pro")
    pkg.FEATURES = frozenset(features)  # type: ignore[attr-defined]
    opt = types.ModuleType("atelier_pro.optimizer")

    def apply_policy(root: object, policy: object) -> Path:
        return Path(str(root)) / "optimization.yaml"

    opt.apply_policy = apply_policy  # type: ignore[attr-defined]
    pkg.optimizer = opt  # type: ignore[attr-defined]
    sys.modules["atelier_pro"] = pkg
    sys.modules["atelier_pro.optimizer"] = opt
    pro_bridge.reset_cache()


def _remove_fake_overlay() -> None:
    sys.modules.pop("atelier_pro", None)
    sys.modules.pop("atelier_pro.optimizer", None)
    pro_bridge.reset_cache()


@pytest.fixture(autouse=True)
def _clean_overlay() -> Iterator[None]:
    _remove_fake_overlay()
    yield
    _remove_fake_overlay()
    entitlements.reload()


@pytest.fixture
def issuer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Ed25519PrivateKey]:
    priv = Ed25519PrivateKey.generate()
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path))
    monkeypatch.setenv("ATELIER_LICENSE_PUBLIC_KEY", base64.b64encode(raw_pub).decode("ascii"))
    monkeypatch.delenv("ATELIER_LICENSE", raising=False)
    entitlements.reload()
    yield priv
    entitlements.reload()


@pytest.mark.skipif(_REAL_OVERLAY_INSTALLED, reason="real atelier_pro is installed in this env")
def test_bridge_absent_is_free() -> None:
    assert pro_bridge.available() is False
    assert pro_bridge.provides("optimizer") is False
    assert pro_bridge.load("optimizer") is None


def test_bridge_present_resolves_features() -> None:
    _install_fake_overlay({"optimizer", "savings_dashboard"})
    assert pro_bridge.available() is True
    assert pro_bridge.provides("optimizer") is True
    assert pro_bridge.provides("unlisted_feature") is False
    mod = pro_bridge.load("optimizer")
    assert mod is not None and hasattr(mod, "apply_policy")


def test_feature_active_needs_both_license_and_overlay(
    issuer: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATELIER_LICENSE", _make_token(issuer))
    entitlements.reload()

    # Licensed but overlay absent -> not active (falls back to Free).
    assert licensing.has_feature("optimizer") is True
    assert licensing.feature_active("optimizer") is False
    assert licensing.pro_impl("optimizer") is None

    # Licensed AND overlay present -> active, and pro_impl resolves.
    _install_fake_overlay({"optimizer"})
    assert licensing.feature_active("optimizer") is True
    impl = licensing.pro_impl("optimizer")
    assert impl is not None and hasattr(impl, "apply_policy")


def test_overlay_without_license_stays_locked(issuer: Ed25519PrivateKey) -> None:
    # No ATELIER_LICENSE set: even with the overlay present, a leaked wheel
    # cannot unlock the feature without a valid key.
    _install_fake_overlay({"optimizer"})
    assert pro_bridge.provides("optimizer") is True
    assert licensing.has_feature("optimizer") is False
    assert licensing.feature_active("optimizer") is False


def test_free_features_are_always_active() -> None:
    # A non-Pro key is active regardless of license or overlay.
    assert licensing.feature_active("search") is True
    assert licensing.pro_impl("search") is None  # not a Pro feature -> no overlay module
