from __future__ import annotations

from atelier.infra.code_intel.scip.binaries import scip_binary_specs
from atelier.infra.code_intel.scip.bootstrap import scip_availability_statuses


def test_scip_availability_report_covers_registry() -> None:
    statuses = scip_availability_statuses()

    assert set(statuses) == set(scip_binary_specs())


def test_scip_availability_report_matches_provisioning_tiers() -> None:
    statuses = scip_availability_statuses()
    expected_tiers = {
        "python": "install_time",
        "typescript": "install_time",
        "javascript": "install_time",
        "go": "lazy",
        "ruby": "lazy",
        "c": "lazy",
        "cpp": "lazy",
        "rust": "user_toolchain",
        "java": "user_toolchain",
    }
    allowed_statuses = {
        "ready",
        "missing_install_time",
        "bootstrap_unavailable",
        "user_toolchain_required",
    }

    for language, tier in expected_tiers.items():
        status = statuses[language]
        assert status.tier == tier
        assert status.status in allowed_statuses
        if status.status == "ready":
            assert status.binary is not None
        else:
            assert status.install_hint
