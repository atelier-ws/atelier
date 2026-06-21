from __future__ import annotations

from click.testing import CliRunner

from atelier.core.capabilities import licensing
from atelier.core.capabilities.licensing.device import DeviceInfo, DeviceLimitError
from atelier.core.capabilities.licensing.models import License
from atelier.gateway.cli import cli


def test_activation_removes_selected_device_before_retry(monkeypatch, tmp_path) -> None:
    devices = (
        DeviceInfo("dev_laptop", "Laptop", 100, 200),
        DeviceInfo("dev_old", "Old workstation", 100, 150),
        DeviceInfo("dev_ci", "CI machine", 100, 120),
    )
    attempts = 0
    removed: list[str] = []

    def activate(key: str, *, device_name: str | None = None) -> License:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise DeviceLimitError(devices)
        return License("lic_test", "dev@example.com", "pro", 100, 9999999999, kind="device")

    monkeypatch.setattr(licensing, "activate", activate)
    monkeypatch.setattr(
        licensing,
        "remove_device",
        lambda purchase_token, device_id: removed.append(device_id) or (),
    )

    result = CliRunner().invoke(
        cli,
        ["--root", str(tmp_path), "license", "activate", "purchase-token"],
        input="y\n2\n",
    )

    assert result.exit_code == 0, result.output
    assert removed == ["dev_old"]
    assert attempts == 2
    assert "Activated Atelier Pro" in result.output


def test_license_devices_lists_active(monkeypatch, tmp_path) -> None:
    devices = (
        DeviceInfo("dev_laptop", "Laptop", 100, 1_700_000_000),
        DeviceInfo("dev_ci", "CI machine", 100, 1_699_000_000),
    )
    monkeypatch.setattr(licensing, "stored_purchase_token", lambda: "purchase-token")
    monkeypatch.setattr(licensing, "list_devices", lambda token: devices)

    result = CliRunner().invoke(cli, ["--root", str(tmp_path), "license", "devices"])

    assert result.exit_code == 0, result.output
    assert "1. Laptop" in result.output
    assert "CI machine" in result.output


def test_license_devices_remove_by_index(monkeypatch, tmp_path) -> None:
    devices = (
        DeviceInfo("dev_laptop", "Laptop", 100, 1_700_000_000),
        DeviceInfo("dev_ci", "CI machine", 100, 1_699_000_000),
    )
    removed: list[str] = []
    monkeypatch.setattr(licensing, "stored_purchase_token", lambda: "purchase-token")
    monkeypatch.setattr(licensing, "list_devices", lambda token: devices)
    monkeypatch.setattr(
        licensing,
        "remove_device",
        lambda token, device_id: removed.append(device_id) or (devices[0],),
    )

    result = CliRunner().invoke(cli, ["--root", str(tmp_path), "license", "devices", "remove", "2"])

    assert result.exit_code == 0, result.output
    assert removed == ["dev_ci"]
    assert "Removed CI machine" in result.output


def test_license_devices_without_purchase_key_errors(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(licensing, "stored_purchase_token", lambda: None)

    result = CliRunner().invoke(cli, ["--root", str(tmp_path), "license", "devices"])

    assert result.exit_code != 0
    assert "atelier license activate" in result.output
