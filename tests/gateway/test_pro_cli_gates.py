"""Pro entitlement gates on CLI control surfaces (recall, router, zoekt).

Free installs (no `atelier_pro` overlay, no license) must block these commands
with an upsell; a Pro install (overlay + valid license) opens the gate.
"""

from __future__ import annotations

import base64
import json
import sys
import time
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atelier.core.capabilities import pro_bridge
from atelier.core.capabilities.licensing import entitlements
from atelier.gateway.cli import cli
from tests.helpers import init_store_at


def _invoke(root: Path, *args: str) -> Result:
    return CliRunner().invoke(cli, ["--root", str(root), *args])


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _make_token(priv: Ed25519PrivateKey) -> str:
    payload = {
        "v": 1,
        "id": "lic_test",
        "email": "dev@example.com",
        "plan": "pro",
        "iat": int(time.time()) - 10,
        "exp": None,
        "features": [],
    }
    seg = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{seg}.{_b64u(priv.sign(seg.encode('ascii')))}"


def _install_overlay() -> None:
    pkg = types.ModuleType("atelier_pro")
    pkg.FEATURES = frozenset({"session_recall", "model_routing", "code_search"})  # type: ignore[attr-defined]
    sys.modules["atelier_pro"] = pkg
    pro_bridge.reset_cache()


def _remove_overlay() -> None:
    sys.modules.pop("atelier_pro", None)
    pro_bridge.reset_cache()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    _remove_overlay()
    # Isolate the license store away from any real ~/.atelier and clear env.
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "lic"))
    monkeypatch.delenv("ATELIER_LICENSE", raising=False)
    entitlements.reload()
    yield
    _remove_overlay()
    entitlements.reload()


GATED = [
    ("recall", "search", "hello"),
    ("router", "start"),
    ("zoekt", "index"),
    ("knowledge", "extract"),
    ("swarm", "start"),
    ("memory", "find", "hello"),
]


@pytest.mark.parametrize("args", GATED)
def test_free_install_blocks_pro_cli(tmp_path: Path, args: tuple[str, ...]) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    res = _invoke(root, *args)
    assert res.exit_code != 0
    assert "Atelier Pro feature" in res.output


def test_pro_install_opens_recall_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    priv = Ed25519PrivateKey.generate()
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv("ATELIER_LICENSE_PUBLIC_KEY", base64.b64encode(raw_pub).decode("ascii"))
    monkeypatch.setenv("ATELIER_LICENSE", _make_token(priv))
    _install_overlay()
    entitlements.reload()

    root = tmp_path / "a"
    init_store_at(str(root))
    res = _invoke(root, "recall", "search", "hello")
    # Gate opened: the command ran (no matches in an empty index) instead of the upsell.
    assert "Atelier Pro feature" not in res.output
    assert res.exit_code == 0, res.output
