"""``atelier license`` -- activate and inspect the Pro license (open-core)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from atelier.gateway.cli.commands._shared import _emit

if TYPE_CHECKING:
    from atelier.core.capabilities.licensing import DeviceInfo


@click.group("license", invoke_without_command=True)
@click.pass_context
def license_group(ctx: click.Context) -> None:
    """Manage your Atelier Pro license."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(license_status)


def _fmt_expiry(expires_at: int | None) -> str:
    if expires_at is None:
        return "never (lifetime)"
    return datetime.fromtimestamp(expires_at, tz=UTC).strftime("%Y-%m-%d")


@license_group.command("status")
@click.option("--json", "as_json", is_flag=True)
def license_status(as_json: bool) -> None:
    """Show the current license and unlocked features."""
    from atelier.core.capabilities import licensing

    st = licensing.status()
    if as_json:
        _emit(
            {
                "licensed": st.licensed,
                "valid": st.valid,
                "plan": st.plan,
                "email": st.email,
                "expires_at": st.expires_at,
                "features": list(st.features),
                "reason": st.reason,
                "source": st.source,
            },
            as_json=True,
        )
        return
    if st.valid:
        click.echo(f"Atelier Pro: active ({st.plan})")
        click.echo(f"  Licensed to: {st.email}")
        click.echo(f"  Expires:     {_fmt_expiry(st.expires_at)}")
        click.echo(f"  Source:      {st.source}")
        click.echo("  Unlocked:")
        for feature in st.features:
            click.echo(f"    - {licensing.PRO_FEATURES.get(feature, feature)}")
    else:
        click.echo("Atelier Pro: not active (Free tier)")
        click.echo(f"  Reason: {st.reason}")
        click.echo("  Activate with: atelier license activate <key>")
        click.echo(f"  Get a key at:  {licensing.pro_url()}")


@license_group.command("activate")
@click.argument("key")
@click.option("--device-name", help="Name shown in your active-device list.")
@click.option("--json", "as_json", is_flag=True)
def license_activate(key: str, device_name: str | None, as_json: bool) -> None:
    """Verify and store a license KEY."""
    from atelier.core.capabilities import licensing

    try:
        lic = licensing.activate(key, device_name=device_name)
    except licensing.DeviceLimitError as exc:
        if as_json:
            _emit(
                {
                    "activated": False,
                    "error": "device_limit_reached",
                    "limit": exc.limit,
                    "devices": [device.__dict__ for device in exc.devices],
                },
                as_json=True,
            )
            return
        click.echo(f"Your {exc.limit} device slots are already in use:")
        for index, device in enumerate(exc.devices, start=1):
            last_seen = datetime.fromtimestamp(device.last_seen_at, tz=UTC).strftime("%Y-%m-%d")
            click.echo(f"  {index}. {device.name} (last used {last_seen})")
        if not click.confirm("Remove one of these devices and activate this device?"):
            raise click.ClickException("Activation cancelled; no device was removed.") from exc
        choice = click.prompt(
            "Device number to remove",
            type=click.IntRange(1, len(exc.devices)),
        )
        selected = exc.devices[choice - 1]
        try:
            licensing.remove_device(key, selected.device_id)
            lic = licensing.activate(key, device_name=device_name)
        except licensing.LicenseError as retry_exc:
            raise click.ClickException(f"Could not replace device: {retry_exc}") from retry_exc
    except licensing.LicenseError as exc:
        raise click.ClickException(f"Invalid license key: {exc}") from exc

    st = licensing.status()
    if as_json:
        _emit(
            {
                "activated": True,
                "plan": lic.plan,
                "email": lic.email,
                "expires_at": lic.expires_at,
                "valid": st.valid,
                "path": str(licensing.license_path()),
            },
            as_json=True,
        )
        return
    click.echo(f"Activated Atelier Pro ({lic.plan}) for {lic.email}.")
    click.echo(f"Expires: {_fmt_expiry(lic.expires_at)}")
    if not st.valid:
        click.echo(f"Warning: license is not currently valid ({st.reason}).")


@license_group.command("deactivate")
@click.option("--json", "as_json", is_flag=True)
def license_deactivate(as_json: bool) -> None:
    """Remove the stored license key (reverts to Free tier)."""
    from atelier.core.capabilities import licensing

    removed = licensing.deactivate()
    if as_json:
        _emit({"removed": removed}, as_json=True)
        return
    click.echo("License removed; reverted to Free tier." if removed else "No license was stored.")


def _purchase_token() -> str:
    from atelier.core.capabilities import licensing

    token = licensing.stored_purchase_token()
    if not token:
        raise click.ClickException(
            "No purchase key on this machine. Activate first with: atelier license activate <key>"
        )
    return token


def _fetch_devices(token: str) -> tuple[DeviceInfo, ...]:
    from atelier.core.capabilities import licensing

    try:
        return licensing.list_devices(token)
    except licensing.LicenseError as exc:
        raise click.ClickException(str(exc)) from exc


def _show_devices(as_json: bool) -> None:
    devices = _fetch_devices(_purchase_token())
    if as_json:
        _emit({"devices": [device.__dict__ for device in devices]}, as_json=True)
        return
    if not devices:
        click.echo("No active devices.")
        return
    click.echo("Active devices:")
    for index, device in enumerate(devices, start=1):
        last_seen = datetime.fromtimestamp(device.last_seen_at, tz=UTC).strftime("%Y-%m-%d")
        click.echo(f"  {index}. {device.name} (last used {last_seen})")
    click.echo("\nRemove one with: atelier license devices remove <number>")


@license_group.group("devices", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def license_devices(ctx: click.Context, as_json: bool) -> None:
    """List and remove the devices on your Pro license."""
    if ctx.invoked_subcommand is None:
        _show_devices(as_json)


@license_devices.command("list")
@click.option("--json", "as_json", is_flag=True)
def license_devices_list(as_json: bool) -> None:
    """Show the active devices on your license."""
    _show_devices(as_json)


@license_devices.command("remove")
@click.argument("index", type=int)
@click.option("--json", "as_json", is_flag=True)
def license_devices_remove(index: int, as_json: bool) -> None:
    """Revoke device number INDEX (as listed by `atelier license devices`)."""
    from atelier.core.capabilities import licensing

    token = _purchase_token()
    devices = _fetch_devices(token)
    if index < 1 or index > len(devices):
        raise click.ClickException(f"No device #{index}. Run 'atelier license devices' to list them.")
    selected = devices[index - 1]
    try:
        remaining = licensing.remove_device(token, selected.device_id)
    except licensing.LicenseError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        _emit(
            {"removed": selected.device_id, "devices": [d.__dict__ for d in remaining]},
            as_json=True,
        )
        return
    click.echo(f"Removed {selected.name}; that slot is now free.")
