"""Fail-closed SCIP indexer bootstrap and availability metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from atelier.infra.code_intel.scip.binaries import discover_scip_binary, scip_binary_spec

ScipBootstrapTier = Literal["install_time", "lazy", "user_toolchain"]
ScipBootstrapStatus = Literal[
    "ready",
    "unsupported",
    "missing_install_time",
    "bootstrap_unavailable",
    "user_toolchain_required",
]


@dataclass(frozen=True)
class ScipBootstrapMetadata:
    """Provisioning tier and user-facing hint for one SCIP indexer."""

    tier: ScipBootstrapTier
    install_hint: str


class ScipBootstrapResult(BaseModel):
    """Availability/bootstrap result for one canonical language."""

    model_config = ConfigDict(extra="forbid")

    language: str
    tier: ScipBootstrapTier | None = None
    status: ScipBootstrapStatus
    binary: Path | None = None
    message: str = ""
    install_hint: str = ""


_BOOTSTRAP_METADATA: dict[str, ScipBootstrapMetadata] = {
    "python": ScipBootstrapMetadata("install_time", "Re-run scripts/install.sh with npm available."),
    "typescript": ScipBootstrapMetadata("install_time", "Re-run scripts/install.sh with npm available."),
    "javascript": ScipBootstrapMetadata("install_time", "Re-run scripts/install.sh with npm available."),
    "go": ScipBootstrapMetadata("lazy", "Install scip-go or provide ATELIER_SCIP_GO_BIN."),
    "ruby": ScipBootstrapMetadata("lazy", "Install scip-ruby or provide ATELIER_SCIP_RUBY_BIN."),
    "c": ScipBootstrapMetadata("lazy", "Install scip-clang or provide ATELIER_SCIP_CLANG_BIN."),
    "cpp": ScipBootstrapMetadata("lazy", "Install scip-clang or provide ATELIER_SCIP_CLANG_BIN."),
    "rust": ScipBootstrapMetadata(
        "user_toolchain", "Install rust-analyzer with SCIP support or provide ATELIER_SCIP_RUST_BIN."
    ),
    "java": ScipBootstrapMetadata(
        "user_toolchain", "Install scip-java with a JDK/coursier toolchain or provide ATELIER_SCIP_JAVA_BIN."
    ),
}

_LAZY_BOOTSTRAP_CHECKSUMS: dict[str, str] = {}


def scip_bootstrap_metadata(language: str) -> ScipBootstrapMetadata | None:
    """Return provisioning metadata for a canonical SCIP language."""

    return _BOOTSTRAP_METADATA.get(language)


def ensure_scip_binary(language: str) -> ScipBootstrapResult:
    """Resolve or bootstrap a SCIP binary, failing closed when bootstrap is not safe."""

    spec = scip_binary_spec(language)
    if spec is None:
        return ScipBootstrapResult(language=language, status="unsupported", message="unsupported language")

    metadata = scip_bootstrap_metadata(language)
    binary = discover_scip_binary(language)
    if binary is not None:
        return ScipBootstrapResult(
            language=language,
            tier=metadata.tier if metadata is not None else None,
            status="ready",
            binary=binary,
            message="ready",
            install_hint=metadata.install_hint if metadata is not None else "",
        )

    if metadata is None:
        return ScipBootstrapResult(language=language, status="unsupported", message="unsupported language")
    if metadata.tier == "user_toolchain":
        return ScipBootstrapResult(
            language=language,
            tier=metadata.tier,
            status="user_toolchain_required",
            message="SCIP indexer requires a user-managed toolchain",
            install_hint=metadata.install_hint,
        )
    if metadata.tier == "install_time":
        return ScipBootstrapResult(
            language=language,
            tier=metadata.tier,
            status="missing_install_time",
            message="SCIP indexer is installed by the Atelier installer when npm is available",
            install_hint=metadata.install_hint,
        )

    if language not in _LAZY_BOOTSTRAP_CHECKSUMS:
        return ScipBootstrapResult(
            language=language,
            tier=metadata.tier,
            status="bootstrap_unavailable",
            message="lazy SCIP bootstrap is unavailable without a checksum allowlist entry",
            install_hint=metadata.install_hint,
        )

    return ScipBootstrapResult(
        language=language,
        tier=metadata.tier,
        status="bootstrap_unavailable",
        message="lazy SCIP bootstrap download is not available in this runtime",
        install_hint=metadata.install_hint,
    )


def scip_availability_statuses() -> dict[str, ScipBootstrapResult]:
    """Return availability/bootstrap status for every supported SCIP language."""

    return {language: ensure_scip_binary(language) for language in sorted(_BOOTSTRAP_METADATA)}


__all__ = [
    "ScipBootstrapMetadata",
    "ScipBootstrapResult",
    "ScipBootstrapStatus",
    "ScipBootstrapTier",
    "ensure_scip_binary",
    "scip_availability_statuses",
    "scip_bootstrap_metadata",
]
