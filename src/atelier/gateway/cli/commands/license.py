"""``atelier license`` -- activate and inspect the Pro license (open-core)."""

from __future__ import annotations

from datetime import UTC, datetime

import click

from atelier.gateway.cli.commands._shared import _emit

_PRO_URL = "https://atelier.ws/pro"


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
        click.echo(f"  Get a key at:  {_PRO_URL}")


@license_group.command("activate")
@click.argument("key")
@click.option("--json", "as_json", is_flag=True)
def license_activate(key: str, as_json: bool) -> None:
    """Verify and store a license KEY."""
    from atelier.core.capabilities import licensing

    try:
        lic = licensing.activate(key)
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
