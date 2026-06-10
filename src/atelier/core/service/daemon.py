"""``atelierd`` — Atelier HTTP service daemon CLI.

Single entry point for managing the Atelier HTTP service:

  atelierd start       Start the HTTP service (foreground)
  atelierd stop        Stop the running service
  atelierd restart     Restart via systemd (or kill+start if no systemd)
  atelierd status      Show running state
  atelierd install     Install systemd/launchd unit
  atelierd uninstall   Remove systemd/launchd unit
  atelierd logs        Follow service logs
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

# ── helpers ──────────────────────────────────────────────────────────────────


def _service_unit() -> str:
    return os.environ.get("ATELIERD_UNIT", "atelier-stack.service")


def _atelier_root() -> Path:
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    if root:
        return Path(root)
    return Path.home() / ".atelier"


def _systemctl_available() -> bool:
    return shutil.which("systemctl") is not None


def _run_systemctl(*args: str) -> int:
    return subprocess.call(["systemctl", "--user", *args])


def _launchctl_available() -> bool:
    return sys.platform == "darwin" and shutil.which("launchctl") is not None


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group(context_settings={"help_option_names": ["-h", "--help"]}, invoke_without_command=True)
@click.version_option(prog_name="atelierd")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Atelier service daemon — manage the Atelier HTTP service.

    Run with no arguments to start the service (same as ``atelierd start``).
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(start)


@cli.command()
@click.option("--host", default=None, help="Bind host (default: ATELIER_HOST or 127.0.0.1)")
@click.option("--port", default=None, type=int, help="Bind port (default: ATELIER_PORT or 8787)")
@click.option("--reload", is_flag=True, default=False, help="Enable uvicorn hot-reload (dev)")
def start(host: str | None, port: int | None, reload: bool) -> None:
    """Start the Atelier HTTP service in the foreground."""
    if host:
        os.environ["ATELIER_HOST"] = host
    if port:
        os.environ["ATELIER_PORT"] = str(port)
    from atelier.core.service.api import main

    main(host=host, port=port, reload=reload)


@cli.command()
def stop() -> None:
    """Stop the Atelier HTTP service."""
    if _systemctl_available():
        ret = _run_systemctl("stop", _service_unit())
        sys.exit(ret)
    # Fallback: find and kill the service process
    import signal

    killed = 0
    for pid_file in [
        _atelier_root() / "service.pid",
        Path("/tmp/atelierd.pid"),
    ]:
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                killed += 1
                click.echo(f"Sent SIGTERM to PID {pid}")
            except (ValueError, ProcessLookupError, OSError):
                pass
    if not killed:
        click.echo("No running atelierd process found (try: systemctl --user stop atelier-stack)", err=True)
        sys.exit(1)


@cli.command()
def restart() -> None:
    """Restart the Atelier HTTP service."""
    if _systemctl_available():
        ret = _run_systemctl("restart", _service_unit())
        sys.exit(ret)
    click.echo("systemctl not available; use 'atelierd stop && atelierd start'", err=True)
    sys.exit(1)


@cli.command()
def status() -> None:
    """Show running status of the Atelier HTTP service."""
    import urllib.request

    root_url = f"http://127.0.0.1:{os.environ.get('ATELIER_PORT', '8787')}"
    try:
        with urllib.request.urlopen(f"{root_url}/health", timeout=2) as resp:
            data = resp.read().decode()
        click.echo(f"● atelierd  running  {root_url}  {data.strip()}")
    except Exception:  # noqa: BLE001
        click.echo(f"● atelierd  stopped  (not reachable at {root_url}/health)")

    if _systemctl_available():
        click.echo("")
        _run_systemctl("status", _service_unit(), "--no-pager")


@cli.command()
@click.option("--follow/--no-follow", "-f", default=True, help="Follow log output")
@click.option("--lines", "-n", default=50, help="Number of recent lines to show")
def logs(follow: bool, lines: int) -> None:
    """Show Atelier HTTP service logs."""
    if _systemctl_available():
        args = ["journalctl", "--user", "-u", _service_unit(), f"-n{lines}"]
        if follow:
            args.append("-f")
        os.execlp("journalctl", *args)
    # Fallback: try the log file
    log_path = _atelier_root() / "service.log"
    if log_path.exists():
        if follow:
            os.execlp("tail", "tail", "-f", "-n", str(lines), str(log_path))
        else:
            subprocess.run(["tail", "-n", str(lines), str(log_path)])
    else:
        click.echo("No log file found. Use systemd: journalctl --user -u atelier-stack", err=True)


@cli.command()
@click.option(
    "--with-stack/--no-stack",
    default=True,
    show_default=True,
    help="Install the HTTP service unit (atelier-stack.service)",
)
@click.option(
    "--enable/--no-enable", default=True, show_default=True, help="Enable and start the unit immediately after install"
)
def install(with_stack: bool, enable: bool) -> None:
    """Install systemd unit for the Atelier HTTP service."""
    if not _systemctl_available():
        click.echo("systemctl not available. On macOS use 'atelierd install --launchd'.", err=True)
        sys.exit(1)

    atelierd_bin = shutil.which("atelierd") or str(Path(sys.executable).parent / "atelierd")
    project_root = os.getcwd()
    root = _atelier_root()
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    unit_content = f"""[Unit]
Description=Atelier HTTP Service
After=network.target

[Service]
Type=simple
WorkingDirectory={project_root}
ExecStart={atelierd_bin} start
Restart=on-failure
RestartSec=5
Environment=ATELIER_ROOT={root}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    unit_path = unit_dir / _service_unit()
    unit_path.write_text(unit_content, encoding="utf-8")
    click.echo(f"Installed {unit_path}")

    _run_systemctl("daemon-reload")
    if enable:
        _run_systemctl("enable", "--now", _service_unit())
        click.echo(f"Enabled and started {_service_unit()}")


@cli.command()
@click.option("--stop/--no-stop", default=True, help="Stop the service before uninstalling")
def uninstall(stop: bool) -> None:
    """Remove the systemd unit for the Atelier HTTP service."""
    if not _systemctl_available():
        click.echo("systemctl not available.", err=True)
        sys.exit(1)
    if stop:
        _run_systemctl("stop", _service_unit())
    _run_systemctl("disable", _service_unit())
    unit_path = Path.home() / ".config" / "systemd" / "user" / _service_unit()
    if unit_path.exists():
        unit_path.unlink()
        click.echo(f"Removed {unit_path}")
    _run_systemctl("daemon-reload")
    click.echo("Uninstalled.")


# ── frontend commands ─────────────────────────────────────────────────────────

_FRONTEND_UNIT = "atelier-frontend.service"


def _frontend_dir() -> Path:
    """Return the frontend Vite source directory."""
    # 1. Explicit env var (cleanest override)
    env_dir = os.environ.get("ATELIER_FRONTEND_DIR")
    if env_dir:
        return Path(env_dir)
    # 2. cwd is the frontend dir (when systemd WorkingDirectory is set)
    cwd = Path.cwd()
    if (cwd / "package.json").exists() and (cwd / "node_modules" / ".bin" / "vite").exists():
        return cwd
    # 3. Look relative to the installed package source
    import importlib.util

    spec = importlib.util.find_spec("atelier")
    if spec and spec.origin:
        src_root = Path(spec.origin).parents[3]
        candidate = src_root / "frontend"
        if (candidate / "package.json").exists():
            return candidate
    return Path.cwd() / "frontend"


@cli.command("frontend-start")
@click.option("--host", default="localhost", show_default=True)
@click.option("--port", default=3125, show_default=True, type=int)
@click.option("--api-url", default=None, help="Atelier service URL for VITE_API_URL (default: http://localhost:8787)")
def frontend_start(host: str, port: int, api_url: str | None) -> None:
    """Start the Atelier visualization frontend (Vite dev server)."""
    fdir = _frontend_dir()
    if not fdir.exists():
        click.echo(f"Frontend directory not found: {fdir}", err=True)
        sys.exit(1)
    # Prefer locally installed vite binary to avoid npm exec download overhead
    vite_bin = fdir / "node_modules" / ".bin" / "vite"
    if not vite_bin.exists():
        # Install node_modules first
        subprocess.run(["npm", "ci"], cwd=str(fdir), check=True)
    env = os.environ.copy()
    env["VITE_API_URL"] = api_url or os.environ.get("ATELIER_SERVICE_URL", "http://localhost:8787")
    os.execlpe(str(vite_bin), "vite", "--host", host, "--port", str(port), env)


@cli.command("frontend-install")
@click.option("--enable/--no-enable", default=True, help="Enable and start the unit immediately")
def frontend_install(enable: bool) -> None:
    """Install systemd unit for the Atelier visualization frontend."""
    if not _systemctl_available():
        click.echo("systemctl not available.", err=True)
        sys.exit(1)
    fdir = _frontend_dir()
    if not fdir.exists():
        click.echo(f"Frontend directory not found: {fdir}", err=True)
        sys.exit(1)
    atelierd_bin = shutil.which("atelierd") or str(Path(sys.executable).parent / "atelierd")
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_content = f"""[Unit]
Description=Atelier Visualization Frontend
After=atelier-stack.service

[Service]
Type=simple
WorkingDirectory={fdir}
ExecStart={atelierd_bin} frontend-start
Restart=on-failure
RestartSec=5
Environment=ATELIER_ROOT={_atelier_root()}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    unit_path = unit_dir / _FRONTEND_UNIT
    unit_path.write_text(unit_content, encoding="utf-8")
    click.echo(f"Installed {unit_path}")
    _run_systemctl("daemon-reload")
    if enable:
        _run_systemctl("enable", "--now", _FRONTEND_UNIT)
        click.echo(f"Enabled and started {_FRONTEND_UNIT}")


def main() -> None:
    """Entry point for the ``atelierd`` console script."""
    cli()
