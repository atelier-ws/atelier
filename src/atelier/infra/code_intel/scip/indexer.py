"""Discovery helpers for precomputed SCIP artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from atelier.infra.code_intel.scip.binaries import (
    discover_scip_binaries,
    discover_scip_binary,
    scip_binary_spec,
)
from atelier.infra.code_intel.scip.external_artifacts import (
    DiscoveredScipArtifact,
    classify_scip_artifact,
    discover_external_scip_artifacts,
)


def default_scip_cache_root(repo_root: Path, repo_id: str) -> Path:
    """Return the repo-local cache directory used for synthetic SCIP artifacts."""

    return repo_root / ".atelier" / "cache" / "scip" / repo_id


ScipIndexStatus = Literal[
    "indexed",
    "unsupported",
    "missing_binary",
    "missing_context",
    "failed",
    "timeout",
    "missing_output",
]


class ScipIndexResult(BaseModel):
    """Result of an explicit lazy SCIP indexing attempt."""

    model_config = ConfigDict(extra="forbid")

    language: str
    status: ScipIndexStatus
    artifact_path: Path | None = None
    command: tuple[str, ...] = ()
    message: str = ""


class ScipIndexer:
    """Discovers checked-in or repo-local SCIP artifacts without installing tooling."""

    def __init__(self, repo_root: Path, repo_id: str, *, cache_root: Path | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.repo_id = repo_id
        self.cache_root = (cache_root or default_scip_cache_root(self.repo_root, repo_id)).resolve()

    def discover_artifacts(self) -> list[DiscoveredScipArtifact]:
        """Return existing `.scip` artifacts under the allowed repo-local cache roots."""

        roots = [self.cache_root]
        artifacts: list[DiscoveredScipArtifact] = []
        seen: set[Path] = set()
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("*.scip")):
                resolved = path.resolve()
                if resolved.name.startswith("external-"):
                    continue
                if resolved not in seen and resolved.is_file():
                    seen.add(resolved)
                    artifacts.append(classify_scip_artifact(resolved))
            for artifact in discover_external_scip_artifacts(root):
                if artifact.path not in seen:
                    seen.add(artifact.path)
                    artifacts.append(artifact)
        return artifacts

    def available_binaries(self) -> dict[str, Path]:
        """Expose local SCIP binaries for future bootstrap paths."""

        return discover_scip_binaries()

    def index_language(self, language: str, *, timeout_seconds: float = 120.0) -> ScipIndexResult:
        """Run one SCIP indexer on demand and write a repo-local artifact."""

        spec = scip_binary_spec(language)
        if spec is None:
            return ScipIndexResult(language=language, status="unsupported", message="unsupported language")
        binary = discover_scip_binary(language)
        if binary is None:
            return ScipIndexResult(language=language, status="missing_binary", message="SCIP binary not found")
        missing_context = spec.missing_context_files(self.repo_root)
        if missing_context:
            return ScipIndexResult(
                language=language,
                status="missing_context",
                message=f"missing required context: {', '.join(missing_context)}",
            )

        self.cache_root.mkdir(parents=True, exist_ok=True)
        output_path = self.cache_root / f"{language}.scip"
        expected_output = spec.expected_output_path(output_path, self.repo_root)
        command = tuple(spec.command(binary, output_path, self.repo_root))

        try:
            completed = subprocess.run(
                list(command),
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ScipIndexResult(language=language, status="timeout", command=command, message="indexer timed out")

        if completed.returncode != 0:
            return ScipIndexResult(
                language=language,
                status="failed",
                command=command,
                message=(completed.stderr or completed.stdout).strip(),
            )

        if expected_output != output_path and expected_output.exists():
            if output_path.exists():
                output_path.unlink()
            expected_output.replace(output_path)

        if not output_path.is_file():
            return ScipIndexResult(
                language=language,
                status="missing_output",
                command=command,
                message=f"indexer did not produce {output_path}",
            )

        artifact = classify_scip_artifact(output_path)
        return ScipIndexResult(
            language=language,
            status="indexed",
            artifact_path=artifact.path,
            command=command,
            message="indexed",
        )


__all__ = ["ScipIndexResult", "ScipIndexStatus", "ScipIndexer", "default_scip_cache_root"]
