"""``atelier license`` -- activate and inspect the Pro license (open-core)."""

from __future__ import annotations

from datetime import UTC, datetime

import click

from atelier.gateway.cli.commands._shared import _emit


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
