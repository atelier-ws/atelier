from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from atelier.infra.code_intel.languages import language_by_name
from atelier.infra.code_intel.scip.binaries import (
    discover_scip_binaries,
    discover_scip_binary,
    scip_binary_spec,
    scip_binary_specs,
)
from atelier.infra.code_intel.scip.indexer import ScipIndexer


def _fake_executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize(
    ("language", "env_var", "fallback"),
    [
        ("python", "ATELIER_SCIP_PYTHON_BIN", "scip-python"),
        ("typescript", "ATELIER_SCIP_TYPESCRIPT_BIN", "scip-typescript"),
        ("javascript", "ATELIER_SCIP_TYPESCRIPT_BIN", "scip-typescript"),
        ("go", "ATELIER_SCIP_GO_BIN", "scip-go"),
        ("rust", "ATELIER_SCIP_RUST_BIN", "rust-analyzer"),
        ("java", "ATELIER_SCIP_JAVA_BIN", "scip-java"),
        ("ruby", "ATELIER_SCIP_RUBY_BIN", "scip-ruby"),
        ("c", "ATELIER_SCIP_CLANG_BIN", "scip-clang"),
        ("cpp", "ATELIER_SCIP_CLANG_BIN", "scip-clang"),
    ],
)
def test_scip_registry_env_vars_and_fallbacks(language: str, env_var: str, fallback: str) -> None:
    spec = scip_binary_spec(language)

    assert spec is not None
    assert spec.env_var == env_var
    assert spec.fallback_command == fallback
    assert language_by_name(language).scip_indexer == fallback


def test_rust_uses_rust_analyzer_binary_with_scip_subcommand(tmp_path: Path) -> None:
    spec = scip_binary_spec("rust")
    assert spec is not None

    command = spec.command(tmp_path / "rust-analyzer", tmp_path / "rust.scip", tmp_path)

    assert command == [str(tmp_path / "rust-analyzer"), "scip", str(tmp_path)]


def test_discover_scip_binary_prefers_explicit_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = _fake_executable(tmp_path / "custom-scip-go")
    monkeypatch.setenv("ATELIER_SCIP_GO_BIN", str(fake_bin))

    assert discover_scip_binary("go") == fake_bin.resolve()


def test_discover_scip_binaries_iterates_supported_specs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in {
        "scip-python",
        "scip-typescript",
        "scip-go",
        "rust-analyzer",
        "scip-java",
        "scip-ruby",
        "scip-clang",
    }:
        _fake_executable(bin_dir / command)
    monkeypatch.setenv("PATH", str(bin_dir))
    for spec in scip_binary_specs().values():
        monkeypatch.delenv(spec.env_var, raising=False)

    discovered = discover_scip_binaries()

    assert set(discovered) == set(scip_binary_specs())
    assert discovered["c"] == discovered["cpp"]


def test_index_language_reports_missing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("atelier.infra.code_intel.scip.indexer.discover_scip_binary", lambda language: None)

    result = ScipIndexer(tmp_path, "repo").index_language("go")

    assert result.status == "missing_binary"
    assert result.artifact_path is None


def test_index_language_skips_missing_clang_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = _fake_executable(tmp_path / "scip-clang")
    monkeypatch.setattr("atelier.infra.code_intel.scip.indexer.discover_scip_binary", lambda language: fake_bin)

    result = ScipIndexer(tmp_path, "repo").index_language("c")

    assert result.status == "missing_context"
    assert "compile_commands.json" in result.message


def test_index_language_success_is_discoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = _fake_executable(tmp_path / "scip-python")
    monkeypatch.setattr("atelier.infra.code_intel.scip.indexer.discover_scip_binary", lambda language: fake_bin)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[-1])
        output_path.write_text("fake scip", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("atelier.infra.code_intel.scip.indexer.subprocess.run", fake_run)

    indexer = ScipIndexer(tmp_path, "repo")
    result = indexer.index_language("python")

    assert result.status == "indexed"
    assert result.artifact_path == (tmp_path / ".atelier" / "cache" / "scip" / "repo" / "python.scip").resolve()
    assert [artifact.path for artifact in indexer.discover_artifacts()] == [result.artifact_path]


def test_index_language_normalizes_rust_directory_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = _fake_executable(tmp_path / "rust-analyzer")
    monkeypatch.setattr("atelier.infra.code_intel.scip.indexer.discover_scip_binary", lambda language: fake_bin)

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        output_dir = Path(command[-1])
        (output_dir / "index.scip").write_text("fake scip", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("atelier.infra.code_intel.scip.indexer.subprocess.run", fake_run)

    result = ScipIndexer(tmp_path, "repo").index_language("rust")

    assert result.status == "indexed"
    assert result.artifact_path == (tmp_path / ".atelier" / "cache" / "scip" / "repo" / "rust.scip").resolve()


def test_index_language_reports_subprocess_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = _fake_executable(tmp_path / "scip-python")
    monkeypatch.setattr("atelier.infra.code_intel.scip.indexer.discover_scip_binary", lambda language: fake_bin)
    monkeypatch.setattr(
        "atelier.infra.code_intel.scip.indexer.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 2, stdout="", stderr="boom"),
    )

    result = ScipIndexer(tmp_path, "repo").index_language("python")

    assert result.status == "failed"
    assert result.message == "boom"
