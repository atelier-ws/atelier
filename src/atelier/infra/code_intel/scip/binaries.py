"""Environment-aware local SCIP binary discovery."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from atelier.infra.code_intel.languages import language_by_name

ScipOutputStrategy = Literal["file_arg", "cache_dir_index", "repo_index"]


@dataclass(frozen=True)
class ScipBinarySpec:
    """SCIP binary discovery and invocation metadata for one canonical language."""

    language: str
    env_var: str
    fallback_command: str
    argv_template: tuple[str, ...]
    output_strategy: ScipOutputStrategy = "file_arg"
    required_context_files: tuple[str, ...] = ()

    def command(self, binary: Path, output_path: Path, repo_root: Path) -> list[str]:
        """Build the argv list for this indexer without invoking a shell."""

        output_dir = output_path.parent
        replacements = {
            "{output}": str(output_path),
            "{output_dir}": str(output_dir),
            "{repo_root}": str(repo_root),
        }
        argv = [str(binary)]
        for arg in self.argv_template:
            argv.append(replacements.get(arg, arg))
        return argv

    def expected_output_path(self, output_path: Path, repo_root: Path) -> Path:
        """Return where this indexer is expected to write before normalization."""

        if self.output_strategy == "cache_dir_index":
            return output_path.parent / "index.scip"
        if self.output_strategy == "repo_index":
            return repo_root / "index.scip"
        return output_path

    def missing_context_files(self, repo_root: Path) -> tuple[str, ...]:
        """Return required repo-local context files that are absent."""

        return tuple(name for name in self.required_context_files if not (repo_root / name).exists())


# Canonical-keyed env-var names. These strings are operator-supplied config and
# MUST stay byte-identical across refactors (DLS-LANG-04). The indexer binary
# name (the fallback) is sourced from the canonical registry's `scip_indexer`.
_SCIP_ENV_VARS = {
    "python": "ATELIER_SCIP_PYTHON_BIN",
    "typescript": "ATELIER_SCIP_TYPESCRIPT_BIN",
    "javascript": "ATELIER_SCIP_TYPESCRIPT_BIN",
    "go": "ATELIER_SCIP_GO_BIN",
    "rust": "ATELIER_SCIP_RUST_BIN",
    "java": "ATELIER_SCIP_JAVA_BIN",
    "ruby": "ATELIER_SCIP_RUBY_BIN",
    "c": "ATELIER_SCIP_CLANG_BIN",
    "cpp": "ATELIER_SCIP_CLANG_BIN",
}

_SCIP_BINARY_SPECS: dict[str, ScipBinarySpec] = {
    "python": ScipBinarySpec("python", _SCIP_ENV_VARS["python"], "scip-python", ("index", "--output", "{output}")),
    "typescript": ScipBinarySpec(
        "typescript", _SCIP_ENV_VARS["typescript"], "scip-typescript", ("index", "--output", "{output}")
    ),
    "javascript": ScipBinarySpec(
        "javascript", _SCIP_ENV_VARS["javascript"], "scip-typescript", ("index", "--output", "{output}")
    ),
    "go": ScipBinarySpec("go", _SCIP_ENV_VARS["go"], "scip-go", (), output_strategy="repo_index"),
    "rust": ScipBinarySpec(
        "rust",
        _SCIP_ENV_VARS["rust"],
        "rust-analyzer",
        ("scip", "{output_dir}"),
        output_strategy="cache_dir_index",
    ),
    "java": ScipBinarySpec("java", _SCIP_ENV_VARS["java"], "scip-java", ("index", "--output", "{output}")),
    "ruby": ScipBinarySpec("ruby", _SCIP_ENV_VARS["ruby"], "scip-ruby", ("index", "--output", "{output}")),
    "c": ScipBinarySpec(
        "c",
        _SCIP_ENV_VARS["c"],
        "scip-clang",
        ("--index-output-path", "{output}"),
        required_context_files=("compile_commands.json",),
    ),
    "cpp": ScipBinarySpec(
        "cpp",
        _SCIP_ENV_VARS["cpp"],
        "scip-clang",
        ("--index-output-path", "{output}"),
        required_context_files=("compile_commands.json",),
    ),
}


def scip_binary_spec(language: str) -> ScipBinarySpec | None:
    """Return invocation metadata for a canonical SCIP language."""

    return _SCIP_BINARY_SPECS.get(language)


def scip_binary_specs() -> dict[str, ScipBinarySpec]:
    """Return all supported SCIP binary specs keyed by canonical language."""

    return dict(_SCIP_BINARY_SPECS)


def discover_scip_binary(language: str) -> Path | None:
    """Resolve a supported local SCIP indexer binary if one is installed."""

    spec = scip_binary_spec(language)
    if spec is None:
        return None
    env_var = spec.env_var
    lang = language_by_name(language)
    fallback = lang.scip_indexer if lang is not None and lang.scip_indexer else spec.fallback_command
    candidates = [os.environ.get(env_var, ""), fallback]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate) if Path(candidate).name == candidate else candidate
        if not resolved:
            continue
        path = Path(resolved).expanduser().resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def discover_scip_binaries() -> dict[str, Path]:
    """Return the supported SCIP binaries that are already available locally."""

    discovered: dict[str, Path] = {}
    for language in scip_binary_specs():
        path = discover_scip_binary(language)
        if path is not None:
            discovered[language] = path
    return discovered


__all__ = [
    "ScipBinarySpec",
    "discover_scip_binaries",
    "discover_scip_binary",
    "scip_binary_spec",
    "scip_binary_specs",
]
