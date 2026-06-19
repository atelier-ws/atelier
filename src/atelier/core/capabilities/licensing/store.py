"""Persistence for the activated license token (``~/.atelier/license.key``)."""

from __future__ import annotations

import os
from pathlib import Path

from atelier.core.foundation.paths import default_store_root

_LICENSE_FILENAME = "license.key"

# Env var that, when set, overrides the on-disk token (useful for CI, the
# project's own benchmarks, and ephemeral containers).
LICENSE_ENV_VAR = "ATELIER_LICENSE"


def license_path() -> Path:
    return default_store_root() / _LICENSE_FILENAME


def load_token() -> str | None:
    """Return the active token: ``ATELIER_LICENSE`` env wins, then the file."""
    env_token = os.environ.get(LICENSE_ENV_VAR, "").strip()
    if env_token:
        return env_token
    path = license_path()
    if not path.exists():
        return None
    token = path.read_text(encoding="utf-8").strip()
    return token or None


def save_token(token: str) -> Path:
    """Persist ``token`` with owner-only permissions and return its path."""
    path = license_path()
    parent = path.parent
    parent_existed = parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed:
        os.chmod(parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token.strip() + "\n")
    finally:
        os.chmod(path, 0o600)
    return path


def delete_token() -> bool:
    """Remove the stored token file. Returns True if a file was deleted."""
    path = license_path()
    if path.exists():
        path.unlink()
        return True
    return False
