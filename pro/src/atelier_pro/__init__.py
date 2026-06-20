"""Atelier Pro overlay -- proprietary engine activation surfaces.

This package is **not** part of the Apache-2.0 core and is **not** published to
the public ``atelier`` repository. It is built into a separate wheel
(``atelier-pro``) and distributed only to licensed Pro customers.

The open-source core never imports this package directly; it soft-imports it
through :mod:`atelier.core.capabilities.pro_bridge`. When this package is absent
(every Free install), the core runs in Free mode -- silently.

``FEATURES`` is the set of Pro capability keys this overlay implements. It must
be a subset of ``PRO_FEATURES`` in the core (``licensing.features``). The core
checks *both* this set (the code is installed) *and* the Ed25519 license (the
entitlement is granted) before running any gated path.

Convention: a feature whose value comes from running code exposes a submodule
named after its key (e.g. ``atelier_pro.optimizer`` for ``"optimizer"``), loaded
via ``licensing.pro_impl("optimizer")``. A feature that is purely a view/unlock
(e.g. ``"savings_dashboard"``) only needs to appear in ``FEATURES`` -- presence
is the entitlement.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Pro capability keys this overlay provides. Keep in sync with (a subset of)
# PRO_FEATURES in the core. Add a key here -- and, if it runs code, a submodule
# of the same name -- to extend Pro coverage to another capability.
FEATURES: frozenset[str] = frozenset(
    {
        "optimizer",
        "savings_dashboard",
    }
)

__all__ = ["FEATURES", "__version__"]
