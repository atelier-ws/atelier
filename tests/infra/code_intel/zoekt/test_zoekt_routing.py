from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from atelier.core.capabilities.tool_supervision.smart_search import smart_search
from atelier.infra.code_intel.zoekt.adapter import reset_zoekt_supervisors
from atelier.infra.code_intel.zoekt.binary import ZoektBinaryResolution, discover_zoekt_binary
from atelier.infra.code_intel.zoekt.client import ZoektClient
from atelier.infra.code_intel.zoekt.server import get_zoekt_server

skip_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker is required for the managed Zoekt runtime"
)


@pytest.fixture(autouse=True)
def _reset_supervisors() -> Iterator[None]:
    reset_zoekt_supervisors()
    yield
    reset_zoekt_supervisors()


def _write_fixture_repo(repo_root: Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "main.py").write_text(
        "def alpha() -> str:\n    return 'needle token'\n\ndef beta() -> str:\n    return 'needle token again'\n",
        encoding="utf-8",
    )


def _write_large_repo(repo_root: Path, *, files: int = 24, lines_per_file: int = 24) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    for index in range(files):
        payload = "".join(
            f"def item_{index}_{line}() -> str: return 'needle token {index}'\n" for line in range(lines_per_file)
        )
        (repo_root / "src" / f"module_{index}.py").write_text(payload, encoding="utf-8")


@skip_docker
@pytest.mark.slow
class TestZoektRouting:
    def test_zoekt_health_resolves_managed_runtime_and_serves_health(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo_root = tmp_path / "repo"
        _write_fixture_repo(repo_root)
        monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
        monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
        monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
        monkeypatch.setenv("ATELIER_ZOEKT_MODE", "managed")

        resolution = discover_zoekt_binary(repo_root)

        assert resolution.available is True
        assert resolution.runtime in {"binary", "docker"}
        if resolution.runtime == "docker":
            assert resolution.image_ref
        else:
            assert resolution.path is not None

        server = get_zoekt_server(repo_root, resolution=resolution)
        health = server.health()

        assert health.ok is True
        assert health.backend == "zoekt"
        expected_runtime_ref = resolution.image_ref or (str(resolution.path) if resolution.path is not None else None)
        assert health.binary_path == expected_runtime_ref


def test_zoekt_managed_bootstrap_provisions_manifest_when_env_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    _write_fixture_repo(repo_root)
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
    monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "managed")

    resolution = discover_zoekt_binary(repo_root)

    assert resolution.available is True
    if resolution.source == "managed":
        assert resolution.path is not None
        assert resolution.runtime == "docker"
        assert resolution.image_ref
        manifest = repo_root / ".atelier" / "bin" / "MANIFEST.json"
        assert manifest.exists()
        payload = manifest.read_text(encoding="utf-8")
        assert "ghcr.io/sourcegraph/zoekt" in payload
    else:
        assert resolution.source == "system-local"
        assert resolution.runtime == "binary"
        assert resolution.path is not None


@skip_docker
def test_zoekt_lifecycle_reuses_one_server_per_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _write_fixture_repo(repo_root)
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
    monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "managed")
    resolution = discover_zoekt_binary(repo_root)

    first = get_zoekt_server(repo_root, resolution=resolution)
    second = get_zoekt_server(repo_root, resolution=resolution)

    first.ensure_started()
    second.ensure_started()

    assert first is second
    assert first.start_count == 1


@skip_docker
def test_zoekt_byte_range_client_preserves_offsets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _write_fixture_repo(repo_root)
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
    monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "managed")
    resolution = discover_zoekt_binary(repo_root)

    server = get_zoekt_server(repo_root, resolution=resolution)
    server.ensure_started()
    client = ZoektClient(server)

    matches = client.search("needle")

    assert matches
    first_match = matches[0].matches[0]
    source = (repo_root / "src" / "main.py").read_bytes()
    assert first_match.byte_start < first_match.byte_end
    assert source[first_match.byte_start : first_match.byte_end] == b"needle"


@skip_docker
def test_zoekt_search_routes_large_repos_with_backend_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _write_large_repo(repo_root)
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
    monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
    monkeypatch.setenv("ATELIER_ZOEKT_LOC_THRESHOLD", "20")
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "managed")

    payload = smart_search(query="needle token", path=str(repo_root), max_files=5, budget_tokens=4000)

    assert payload["backend"] == "zoekt"
    assert isinstance(payload["index_age_seconds"], int)
    assert payload["matches"]


@skip_docker
def test_zoekt_search_falls_back_for_small_repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _write_fixture_repo(repo_root)
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
    monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
    monkeypatch.setenv("ATELIER_ZOEKT_LOC_THRESHOLD", "10000")
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "managed")

    payload = smart_search(query="needle token", path=str(repo_root), max_files=5, budget_tokens=4000)

    assert payload["backend"] == "ripgrep"
    assert payload["index_age_seconds"] is None


@skip_docker
def test_zoekt_search_falls_back_when_backend_is_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _write_large_repo(repo_root)
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
    monkeypatch.setenv("ATELIER_ZOEKT_LOC_THRESHOLD", "20")
    monkeypatch.setenv("ATELIER_ZOEKT_BIN", str(tmp_path / "missing-zoekt-webserver"))
    monkeypatch.setenv("ATELIER_ZOEKT_BIN_SHA256", "deadbeef")
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "installed")

    payload = smart_search(query="needle token", path=str(repo_root), max_files=5, budget_tokens=4000)

    assert payload["backend"] == "ripgrep"
    assert payload["matches"]


@skip_docker
def test_zoekt_search_routes_large_repos_with_managed_bootstrap_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    _write_large_repo(repo_root)
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
    monkeypatch.setenv("ATELIER_ZOEKT_LOC_THRESHOLD", "20")
    monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "managed")

    payload = smart_search(query="needle token", path=str(repo_root), max_files=5, budget_tokens=4000)

    assert payload["backend"] == "zoekt"
    assert isinstance(payload["index_age_seconds"], int)
    assert payload["matches"]


@skip_docker
def test_zoekt_search_keeps_backend_metadata_on_warm_repeat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    _write_large_repo(repo_root)
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(repo_root))
    monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
    monkeypatch.setenv("ATELIER_ZOEKT_LOC_THRESHOLD", "20")
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "managed")

    first = smart_search(query="needle token", path=str(repo_root), max_files=5, budget_tokens=4000)
    second = smart_search(query="needle token", path=str(repo_root), max_files=5, budget_tokens=4000)

    assert first["backend"] == "zoekt"
    assert second["backend"] == "zoekt"
    assert isinstance(first["index_age_seconds"], int)
    assert isinstance(second["index_age_seconds"], int)
    assert second["index_age_seconds"] >= first["index_age_seconds"]


def test_default_mode_disables_zoekt_without_runtime_probes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.infra.code_intel.zoekt import binary

    repo_root = tmp_path / "repo"
    _write_fixture_repo(repo_root)
    monkeypatch.delenv("ATELIER_ZOEKT_MODE", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)
    monkeypatch.delenv("ATELIER_ZOEKT_BIN_SHA256", raising=False)
    monkeypatch.setattr(
        binary.shutil,
        "which",
        lambda _name: (_ for _ in ()).throw(AssertionError("default mode must not probe PATH")),
    )

    resolution = discover_zoekt_binary(repo_root)

    assert resolution.available is False
    assert resolution.reason == "ATELIER_ZOEKT_MODE=off"
    assert not (repo_root / ".atelier" / "bin" / "MANIFEST.json").exists()


def test_supervisor_caches_missing_runtime_and_route_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.infra.code_intel.zoekt import adapter

    repo_root = tmp_path / "repo"
    _write_large_repo(repo_root)
    calls = {"discover": 0, "lines": 0}

    def unavailable(_repo_root: Path) -> ZoektBinaryResolution:
        calls["discover"] += 1
        return ZoektBinaryResolution(available=False, reason="not installed")

    supervisor = adapter.ZoektSupervisor(repo_root)
    monkeypatch.setenv("ATELIER_ZOEKT_MODE", "installed")
    monkeypatch.setattr(adapter, "discover_zoekt_binary", unavailable)
    monkeypatch.setattr(
        supervisor._indexer,
        "line_count",
        lambda _path: calls.__setitem__("lines", calls["lines"] + 1) or 1_000_000,
    )

    assert supervisor.should_route(repo_root) is False
    assert supervisor.should_route(repo_root) is False
    assert calls == {"discover": 1, "lines": 0}
