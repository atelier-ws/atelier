"""M4 — Scoped Pull Context benchmark (Phase 11).

Target: precision >=0.6 and recall >=0.85 on 20 multi-file edits from repo history.
Baseline: no scoped pull capability.

TODO(Phase 11): Implement once SCOPED-01-05 are shipped.
"""

import pytest


@pytest.mark.slow
def test_m4_scoped_placeholder() -> None:
    pytest.skip("M4 benchmark not yet implemented — ships in Phase 11")
