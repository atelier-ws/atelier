"""Device enrollment and automatic lease refresh for Pro licenses."""

from __future__ import annotations

import base64
import json
import os
import platform
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atelier.core.capabilities.licensing.models import LicenseError
from atelier.core.foundation.paths import default_store_root

_DEFAULT_ISSUER_URL = "https://atelier-license-issuer.pankaj4u4m.workers.dev"
_DEVICE_KEY_FILENAME = "device.key"
_PURCHASE_KEY_FILENAME = "purchase.key"


@dataclass(frozen=True)
class DeviceInfo:
    device_id: str
    name: str
    created_at: int
    last_seen_at: int


class DeviceLimitError(LicenseError):
    def __init__(self, devices: tuple[DeviceInfo, ...], limit: int = 3) -> None:
        self.devices = devices
        self.limit = limit
        super().__init__(f"device limit reached ({limit} active devices)")


def issuer_url() -> str:
    return os.environ.get("ATELIER_LICENSE_ISSUER_URL", "").strip().rstrip("/") or _DEFAULT_ISSUER_URL


def device_key_path() -> Path:
    return default_store_root() / _DEVICE_KEY_FILENAME


def purchase_key_path() -> Path:
    return default_store_root() / _PURCHASE_KEY_FILENAME


def _save_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value.strip() + "\n")
    finally:
        os.chmod(path, 0o600)


def _load_or_create_private_key() -> Ed25519PrivateKey:
    path = device_key_path()
    if path.exists():
        try:
            raw = base64.b64decode(path.read_text(encoding="utf-8").strip(), validate=True)
            return Ed25519PrivateKey.from_private_bytes(raw)
        except (ValueError, OSError) as exc:
            raise LicenseError("stored device key is invalid") from exc
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    _save_private(path, base64.b64encode(raw).decode("ascii"))
    return key


def _public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def device_name() -> str:
    configured = os.environ.get("ATELIER_DEVICE_NAME", "").strip()
    if configured:
        return configured[:80]
    hostname = platform.node().strip() or "unknown-device"
    return f"{hostname} ({platform.system()})"[:80]


def matches_device(license_public_key: str | None) -> bool:
    if not license_public_key or not device_key_path().exists():
        return False
    try:
        return _public_key_b64(_load_or_create_private_key()) == license_public_key
    except LicenseError:
        return False


def _devices(value: Any) -> tuple[DeviceInfo, ...]:
    if not isinstance(value, list):
        return ()
    devices: list[DeviceInfo] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            devices.append(
                DeviceInfo(
                    device_id=str(item["device_id"]),
                    name=str(item["name"]),
                    created_at=int(item["created_at"]),
                    last_seen_at=int(item["last_seen_at"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(devices)


def _request(path: str, body: dict[str, object]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{issuer_url()}{path}",
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Atelier-CLI/0.4",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            result = json.loads(exc.read())
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise LicenseError(f"license issuer returned HTTP {exc.code}") from exc
        if exc.code == 409 and result.get("error") == "device_limit_reached":
            raise DeviceLimitError(_devices(result.get("devices")), int(result.get("limit", 3))) from exc
        raise LicenseError(str(result.get("error", f"license issuer returned HTTP {exc.code}"))) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LicenseError("could not reach the license issuer") from exc
    if not isinstance(result, dict):
        raise LicenseError("license issuer returned an invalid response")
    return result


def activate_purchase(purchase_token: str, *, name: str | None = None) -> str:
    key = _load_or_create_private_key()
    public_key = _public_key_b64(key)
    chosen_name = (name or device_name()).strip()[:80]
    message = f"atelier-device-activate-v1\n{public_key}\n{chosen_name}".encode()
    proof = base64.b64encode(key.sign(message)).decode("ascii")
    result = _request(
        "/devices/activate",
        {
            "purchase_token": purchase_token,
            "device_public_key": public_key,
            "device_name": chosen_name,
            "proof": proof,
        },
    )
    token = result.get("device_token")
    if not isinstance(token, str) or not token:
        raise LicenseError("license issuer did not return a device token")
    _save_private(purchase_key_path(), purchase_token)
    return token


def remove_device(purchase_token: str, device_id: str) -> tuple[DeviceInfo, ...]:
    result = _request(
        "/devices/remove",
        {"purchase_token": purchase_token, "device_id": device_id},
    )
    return _devices(result.get("devices"))


def refresh_device(device_token: str) -> str:
    result = _request("/devices/refresh", {"device_token": device_token})
    token = result.get("device_token")
    if not isinstance(token, str) or not token:
        raise LicenseError("license issuer did not return a refreshed device token")
    return token
