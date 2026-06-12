"""``atelier update`` — manually check for and apply Atelier updates.

Detection order:
1. Git checkout — ``git pull --ff-only && uv sync``
2. PyPI (uv tool) — ``uv tool upgrade atelier``
3. PyPI (pip) — ``pip install --upgrade atelier``
4. Binary (PyInstaller) — download latest GitHub release archive
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click

from atelier import __version__ as current_version
from atelier.core.foundation.update_state import write_update_state

# ---------------------------------------------------------------------------
# Install-method detection
# ---------------------------------------------------------------------------


def _git_project_root() -> Path | None:
    """Resolve the git project root, if installed from a git checkout."""
    # 1. Check install record written by local.sh
    record = Path.home() / ".atelier" / "install_dir"
    if record.exists():
        candidate = Path(record.read_text("utf-8").strip())
        if (candidate / ".git").exists():
            return candidate.resolve()
    # 2. Walk up from this file (dev install without record)
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / ".git").exists():
            # Verify it's the atelier repo, not an unrelated project
            if (parent / "pyproject.toml").exists():
                try:
                    content = (parent / "pyproject.toml").read_text("utf-8")
                    if 'name = "atelier"' in content:
                        return parent
                except OSError:
                    pass
    return None


def _is_frozen() -> bool:
    """True if running from a PyInstaller binary bundle."""
    return bool(getattr(sys, "frozen", False))


def _is_uv_tool_install() -> bool:
    """True if atelier was installed via ``uv tool install``."""
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0 and "atelier" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _pypi_latest_version() -> str | None:
    """Fetch the latest version string from PyPI."""
    import urllib.request

    try:
        resp = urllib.request.urlopen(
            "https://pypi.org/pypi/atelier/json",
            timeout=10,
        )
        data = json.loads(resp.read().decode())
        return data.get("info", {}).get("version")
    except Exception:  # noqa: BLE001
        return None


def _github_latest_version() -> str | None:
    """Fetch the latest release tag from GitHub Releases.

    Returns version string (e.g. "0.3.2") or None on failure.
    """
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/atelier-ws/atelier/releases/latest",
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "atelier-update/1.0"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        tag = data.get("tag_name", "")
        return tag.lstrip("v")
    except Exception:  # noqa: BLE001
        return None


def _detect_method_and_current() -> tuple[str, str | None]:
    """Detect install method and return (method, project_root_or_none).

    Returns one of:
      ("git", project_root_path_str)
      ("uv_tool", None)
      ("pip", None)
      ("binary", None)
    """
    # Frozen binary takes precedence — it can't be any of the others
    if _is_frozen():
        return ("binary", None)

    # Git checkout?
    git_root = _git_project_root()
    if git_root is not None:
        return ("git", str(git_root))

    # uv tool install?
    if _is_uv_tool_install():
        return ("uv_tool", None)

    # Default: pip-installed (or ambiguous — treat as pip)
    return ("pip", None)


# ---------------------------------------------------------------------------
# Update application per method
# ---------------------------------------------------------------------------


def _update_git(project_root: str) -> bool:
    """Update from git: fetch, pull, sync."""
    click.echo("  ◆ Git checkout detected — pulling latest...")
    try:
        subprocess.run(
            ["git", "fetch", "--quiet", "origin"],
            cwd=project_root,
            check=True,
            timeout=30,
        )
        result = subprocess.run(
            ["git", "rev-list", "HEAD..@{u}", "--count"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        behind = int(result.stdout.strip())
        if behind == 0:
            click.echo("  ✓ Already up-to-date.")
            return False

        click.echo(f"  ◇ {behind} new commits behind. Pulling...")
        subprocess.run(
            ["git", "pull", "--ff-only", "--quiet", "origin"],
            cwd=project_root,
            check=True,
            timeout=60,
        )

        # Sync dependencies
        if shutil.which("uv"):
            click.echo("  ◇ Syncing dependencies with uv...")
            subprocess.run(
                ["uv", "sync"],
                cwd=project_root,
                check=True,
                timeout=120,
            )
        else:
            click.echo("  ◇ Reinstalling package...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", project_root],
                cwd=project_root,
                check=True,
                timeout=120,
            )

        click.echo("  ✓ Update applied successfully.")
        return True
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"git update failed: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise click.ClickException(f"git update timed out: {exc}") from exc


def _update_uv_tool() -> bool:
    """Update via ``uv tool upgrade atelier``."""
    click.echo("  ◆ uv tool install detected — upgrading...")
    try:
        result = subprocess.run(
            ["uv", "tool", "upgrade", "atelier"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            click.echo(f"  ✓ {result.stdout.strip()}")
            # uv prints "Updated atelier vX.Y.Z -> vA.B.C"
            return True
        if "already satisfied" in result.stderr or "already" in result.stdout:
            click.echo("  ✓ Already up-to-date.")
            return False
        click.echo(result.stdout)
        click.echo(result.stderr, err=True)
        return result.returncode == 0
    except FileNotFoundError:
        raise click.ClickException("uv not found on PATH") from None
    except subprocess.TimeoutExpired as exc:
        raise click.ClickException(f"uv upgrade timed out: {exc}") from exc


def _update_pip() -> bool:
    """Update via ``pip install --upgrade atelier``."""
    click.echo("  ◆ pip install detected — upgrading...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "atelier"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            if "already up-to-date" in result.stdout.lower() or "already satisfied" in result.stdout.lower():
                click.echo("  ✓ Already up-to-date.")
                return False
            click.echo("  ✓ pip upgrade applied.")
            return True
        click.echo(result.stdout)
        click.echo(result.stderr, err=True)
        return False
    except subprocess.TimeoutExpired as exc:
        raise click.ClickException(f"pip upgrade timed out: {exc}") from exc


def _update_binary() -> bool:
    """Update binary (PyInstaller) via GitHub Releases download.

    Downloads the latest release archive and replaces the current binary.
    """
    import tarfile
    import tempfile
    import urllib.request

    click.echo("  ◆ Binary install detected — fetching latest release...")

    os_name = (sys.platform).lower()
    if os_name == "darwin":
        platform = "darwin"
    elif os_name == "linux":
        platform = "linux"
    else:
        raise click.ClickException(f"Unsupported platform: {os_name}")

    arch = os.uname().machine
    if arch in ("x86_64", "amd64"):
        arch_part = "x86_64"
    elif arch in ("aarch64", "arm64"):
        arch_part = "arm64"
    else:
        raise click.ClickException(f"Unsupported architecture: {arch}")

    suffix = f"{platform}-{arch_part}"
    asset = f"atelier-binaries-{suffix}.tar.gz"
    url = f"https://github.com/atelier-ws/atelier/releases/latest/download/{asset}"

    current_binary = Path(sys.executable if _is_frozen() else (shutil.which("atelier") or ""))
    if not current_binary.exists():
        raise click.ClickException("Could not locate the atelier binary for replacement.")

    try:
        click.echo(f"  ◇ Downloading {asset}...")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
            urllib.request.urlretrieve(url, tmp_path)  # nosec

        extract_dir = Path(tempfile.mkdtemp(prefix="atelier-update-"))
        try:
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(path=extract_dir)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Find the atelier binary in the extracted tree
        extracted_bin = extract_dir / "bin" / "atelier"
        if not extracted_bin.exists():
            # Try flat extraction (some archives extract to current dir)
            extracted_bin = extract_dir / "atelier"
        if not extracted_bin.exists():
            raise click.ClickException(f"Binary not found in release archive {asset}")

        # Replace the current binary
        import stat

        target = current_binary.resolve()
        click.echo(f"  ◇ Installing to {target}...")
        shutil.copy2(str(extracted_bin), str(target))
        target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        click.echo("  ✓ Binary updated successfully.")

        # Clean up
        shutil.rmtree(extract_dir, ignore_errors=True)
        return True

    except urllib.error.HTTPError as exc:
        raise click.ClickException(f"Download failed (HTTP {exc.code}): {exc.reason}") from exc
    except OSError as exc:
        raise click.ClickException(f"Update failed: {exc}") from exc


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("update")
@click.option("--check", "check_only", is_flag=True, help="Only check for updates, do not apply.")
@click.option("--force", "force_update", is_flag=True, help="Reinstall even if same version.")
@click.pass_context
def update_cmd(ctx: click.Context, check_only: bool, force_update: bool) -> None:
    """Check for and apply Atelier updates.

    Detects your install method (git, pip, uv tool, or binary)
    and runs the appropriate upgrade command.
    """
    root: Path = ctx.obj.get("root", Path.home() / ".atelier")

    # 1. Detect install method
    method, project_root = _detect_method_and_current()
    click.echo(f"  Current version: {current_version}")
    click.echo(f"  Install method:  {method}")

    # 2. Check remote version
    remote_version: str | None = None
    if method == "git":
        if project_root:
            try:
                result = subprocess.run(
                    ["git", "fetch", "--quiet", "origin"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    result = subprocess.run(
                        ["git", "show", "origin/main:pyproject.toml"],
                        cwd=project_root,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    match = re.search(r'^version\s*=\s*"([^"]+)"', result.stdout, re.MULTILINE)
                    if match:
                        remote_version = match.group(1)
            except (subprocess.TimeoutExpired, OSError):
                pass
    elif method in ("uv_tool", "pip"):
        remote_version = _pypi_latest_version()
    elif method == "binary":
        remote_version = _github_latest_version()

    if remote_version is None:
        raise click.ClickException("Could not determine latest available version. Check your internet connection.")

    click.echo(f"  Remote version:  {remote_version}")

    # 3. Compare
    if remote_version == current_version and not force_update:
        click.echo("\n  ✓ Already up-to-date.")
        return

    if check_only:
        click.echo(f"\n  ◇ Update available: {current_version} → {remote_version}")
        click.echo("  ◇ Run `atelier update` to apply.")
        return

    # 4. Apply
    click.echo("")
    previous = current_version
    applied: bool = False

    if method == "git":
        assert project_root is not None, "git method requires project_root"
        applied = _update_git(project_root)
    elif method == "uv_tool":
        applied = _update_uv_tool()
    elif method == "pip":
        applied = _update_pip()
    elif method == "binary":
        applied = _update_binary()

    if applied:
        # Reload version
        import importlib.metadata

        try:
            new_version = importlib.metadata.version("atelier")
        except Exception:  # noqa: BLE001
            new_version = remote_version

        write_update_state(
            previous_version=previous,
            current_version=new_version,
            method=method,
            root=root,
        )
        click.echo(f"\n  ◆ Updated from {previous} → {new_version}")
        click.echo("  ◆ Restart the MCP server or hooks to pick up changes.")
    else:
        click.echo("\n  ✓ Already up-to-date.")
