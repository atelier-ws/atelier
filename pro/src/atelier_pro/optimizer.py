"""Pro activation surface for the optimization engine.

Building an optimization policy (from a preset, a custom YAML, or the advisor)
is free and lives in the Apache-2.0 core. *Activating* a policy -- the lever that
makes the runtime engine apply your chosen settings instead of the Free baseline
-- is the paid action, so it lives here in the proprietary overlay.

The core's ``atelier optimize apply`` command resolves this module via
``licensing.pro_impl("optimizer")`` and calls :func:`apply_policy`. When the
overlay is absent the core never reaches this code.
"""

from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.optimization.policy import Policy, save_policy


def apply_policy(root: Path | str, policy: Policy) -> Path:
    """Persist ``policy`` as the active optimization policy; return its path.

    This is the paid lever: once written, the runtime engine
    (``load_current_policy``) honors these settings instead of the Free
    baseline. The core gates the call site on both the license and the presence
    of this overlay.
    """
    return save_policy(Path(root), policy)
