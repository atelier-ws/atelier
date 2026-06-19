"""Tests for the open-core licensing / entitlement layer."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atelier.core.capabilities import licensing
from atelier.core.capabilities.licensing import entitlements


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


def test_free_tier_locks_pro_features(issuer: Ed25519PrivateKey) -> None:
    assert licensing.is_pro() is False
    assert licensing.has_feature("optimizer") is False
    # Non-Pro capabilities are always allowed.
    assert licensing.has_feature("search") is True
    with pytest.raises(licensing.FeatureLocked):
        licensing.require("optimizer")


def test_valid_pro_token_unlocks(issuer: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_LICENSE", _make_token(issuer))
    entitlements.reload()
    assert licensing.is_pro() is True
    assert licensing.has_feature("optimizer") is True
    licensing.require("optimizer")  # does not raise
    st = licensing.status()
    assert st.valid and st.plan == "pro" and st.email == "dev@example.com"


def test_expired_token_is_not_pro(issuer: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_LICENSE", _make_token(issuer, exp=int(time.time()) - 1))
    entitlements.reload()
    assert licensing.is_pro() is False
    assert licensing.status().reason == "license expired"


def test_tampered_signature_rejected(issuer: Ed25519PrivateKey) -> None:
    head, sig = _make_token(issuer).split(".")
    flipped = sig[:-2] + ("AA" if not sig.endswith("AA") else "BB")
    with pytest.raises(licensing.LicenseError):
        licensing.verify_token(f"{head}.{flipped}")


def test_wrong_key_rejected(issuer: Ed25519PrivateKey) -> None:
    other = Ed25519PrivateKey.generate()
    with pytest.raises(licensing.LicenseError):
        licensing.verify_token(_make_token(other))


def test_activate_and_deactivate_roundtrip(issuer: Ed25519PrivateKey) -> None:
    licensing.activate(_make_token(issuer))
    assert licensing.license_path().exists()
    assert licensing.is_pro() is True
    assert licensing.deactivate() is True
    assert licensing.license_path().exists() is False
    assert licensing.is_pro() is False


def test_feature_scoped_token(issuer: Ed25519PrivateKey, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_LICENSE", _make_token(issuer, features=["model_routing"]))
    entitlements.reload()
    assert licensing.has_feature("model_routing") is True
    assert licensing.has_feature("optimizer") is False


def test_pro_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_PRO_URL", raising=False)
    assert licensing.pro_url() == "https://atelier.ws/pro"
    monkeypatch.setenv("ATELIER_PRO_URL", "https://buy.example.com/pro")
    assert licensing.pro_url() == "https://buy.example.com/pro"
