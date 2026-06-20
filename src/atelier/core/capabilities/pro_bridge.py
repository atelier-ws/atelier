"""Soft bridge to the proprietary Pro overlay package (``atelier_pro``).

The open-source core never imports Pro code directly. It asks this bridge two
questions:

* ``provides(feature)`` -- is the overlay installed *and* does it ship this
  capability?
* ``load(name)`` -- give me the overlay implementation module (or ``None``).

When the overlay is absent -- every Free install -- every query returns
``False`` / ``None`` and callers fall back to Free behavior silently, with no
import error. This is one half of the entitlement contract; the other half is
the Ed25519 license check in :mod:`atelier.core.capabilities.licensing`. A Pro
path runs only when BOTH agree: the code is physically present (this bridge) AND
a valid license grants it (the license check). A leaked overlay still can't run
without a key; a key with no overlay has nothing to run.

The overlay package must expose a module-level ``FEATURES`` (an iterable of the
Pro capability keys it implements, a subset of ``PRO_FEATURES`` in
``licensing.features``).
"""

from __future__ import annotations

import importlib
from types import ModuleType

_PACKAGE = "atelier_pro"

_overlay: ModuleType | None = None
_loaded = False


def _overlay_module() -> ModuleType | None:
    """Import the overlay package once; cache presence (or absence)."""
    global _overlay, _loaded
    if not _loaded:
        try:
            _overlay = importlib.import_module(_PACKAGE)
        except ImportError:
            _overlay = None
        _loaded = True
    return _overlay


def available() -> bool:
    """True if the proprietary Pro overlay package is importable."""
    return _overlay_module() is not None


def provides(feature: str) -> bool:
    """True if the overlay is installed and declares ``feature`` in ``FEATURES``."""
    overlay = _overlay_module()
    if overlay is None:
        return False
    return feature in set(getattr(overlay, "FEATURES", ()))


def load(name: str) -> ModuleType | None:
    """Soft-import ``atelier_pro.<name>``; ``None`` if the overlay is absent."""
    if _overlay_module() is None:
        return None
    try:
        return importlib.import_module(f"{_PACKAGE}.{name}")
    except ImportError:
        return None


def reset_cache() -> None:
    """Forget the cached overlay import (tests inject/remove a fake overlay)."""
    global _overlay, _loaded
    _overlay = None
    _loaded = False
