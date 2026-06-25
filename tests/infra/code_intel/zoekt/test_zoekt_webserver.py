"""Unit tests for the host-mode zoekt-webserver integration.

All tests are fully offline: no real zoekt binary, no network access.
Subprocesses and urllib are replaced with in-process fakes.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from atelier.infra.code_intel.zoekt.binary import (
    ZoektBinaryResolution,
    discover_zoekt_binary,
)
from atelier.infra.code_intel.zoekt.server import (
    ZoektServer,
    _list_has_loaded_repo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server(tmp_path: Path, *, resolution: ZoektBinaryResolution | None = None) -> ZoektServer:
    """Return a ZoektServer pointed at a temp repo (no real index)."""
    server = ZoektServer(tmp_path, resolution=resolution)
    # Give it a fake binary so _is_ready() returns True
    fake_bin = tmp_path / "zoekt"
    fake_bin.touch(mode=0o755)
    server._host_search_binary = fake_bin
    return server


def _fake_resolution(tmp_path: Path) -> ZoektBinaryResolution:
    fake_bin = tmp_path / "zoekt"
    fake_bin.touch(mode=0o755)
    # Also place zoekt-webserver beside it for _resolve_webserver_binary
    ws_bin = tmp_path / "zoekt-webserver"
    ws_bin.touch(mode=0o755)
    return ZoektBinaryResolution(
        available=True,
        path=fake_bin,
        source="test",
        runtime="binary",
    )


# ---------------------------------------------------------------------------
# _list_has_loaded_repo
# ---------------------------------------------------------------------------


class TestListHasLoadedRepo:
    def test_empty_bytes(self) -> None:
        assert _list_has_loaded_repo(b"") is False

    def test_invalid_json(self) -> None:
        assert _list_has_loaded_repo(b"not-json") is False

    def test_null_repos_list(self) -> None:
        raw = json.dumps({"List": {"Repos": None}}).encode()
        assert _list_has_loaded_repo(raw) is False

    def test_empty_repos_list(self) -> None:
        raw = json.dumps({"List": {"Repos": []}}).encode()
        assert _list_has_loaded_repo(raw) is False

    def test_repo_with_zero_documents(self) -> None:
        raw = json.dumps({"List": {"Repos": [{"Stats": {"Documents": 0}}]}}).encode()
        assert _list_has_loaded_repo(raw) is False

    def test_repo_with_nonzero_documents(self) -> None:
        raw = json.dumps({"List": {"Repos": [{"Stats": {"Documents": 42}}]}}).encode()
        assert _list_has_loaded_repo(raw) is True

    def test_mixed_repos_one_loaded(self) -> None:
        raw = json.dumps(
            {
                "List": {
                    "Repos": [
                        {"Stats": {"Documents": 0}},
                        {"Stats": {"Documents": 7}},
                    ]
                }
            }
        ).encode()
        assert _list_has_loaded_repo(raw) is True


# ---------------------------------------------------------------------------
# _webserver_enabled
# ---------------------------------------------------------------------------


class TestWebserverEnabled:
    def test_default_is_enabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ATELIER_ZOEKT_WEBSERVER", raising=False)
        server = _make_server(tmp_path)
        assert server._webserver_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "OFF"])
    def test_explicit_disable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("ATELIER_ZOEKT_WEBSERVER", value)
        server = _make_server(tmp_path)
        assert server._webserver_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_explicit_enable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("ATELIER_ZOEKT_WEBSERVER", value)
        server = _make_server(tmp_path)
        assert server._webserver_enabled() is True


# ---------------------------------------------------------------------------
# _stop_webserver
# ---------------------------------------------------------------------------


class TestStopWebserver:
    def test_stop_with_no_proc_is_noop(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        assert server._webserver_proc is None
        server._stop_webserver()  # must not raise
        assert server._webserver_proc is None

    def test_stop_terminates_running_proc(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        proc = MagicMock()
        proc.wait = MagicMock(return_value=0)
        server._webserver_proc = proc
        server._webserver_url = "http://127.0.0.1:9999"

        server._stop_webserver()

        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()
        assert server._webserver_proc is None
        assert server._webserver_url is None

    def test_stop_kills_if_terminate_times_out(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        proc = MagicMock()
        proc.wait = MagicMock(side_effect=[subprocess_timeout(), None])
        server._webserver_proc = proc
        server._webserver_url = "http://127.0.0.1:9999"

        import subprocess

        proc.wait.side_effect = [subprocess.TimeoutExpired("zoekt-webserver", 5), None]

        server._stop_webserver()

        proc.kill.assert_called_once()
        assert server._webserver_proc is None


def subprocess_timeout() -> Any:
    import subprocess

    return subprocess.TimeoutExpired("proc", 5)


# ---------------------------------------------------------------------------
# _run_webserver_search
# ---------------------------------------------------------------------------


class TestRunWebserverSearch:
    def _fake_response(self, body: dict[str, Any]) -> MagicMock:
        raw = json.dumps(body).encode()
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.read = MagicMock(return_value=raw)
        return resp

    def test_returns_parsed_json(self, tmp_path: Path) -> None:
        server = _make_server(tmp_path)
        expected = {"Result": {"Files": []}}
        with patch("urllib.request.urlopen", return_value=self._fake_response(expected)):
            result = server._run_webserver_search("http://127.0.0.1:9", {"Q": "foo"})
        assert result == expected

    def test_sends_query_as_json_string(self, tmp_path: Path) -> None:
        """The Q field must be sent as a plain string, not a JSON object."""
        server = _make_server(tmp_path)
        captured: list[bytes] = []

        def fake_urlopen(req: Any, timeout: float) -> Any:
            captured.append(req.data)
            resp = MagicMock()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            resp.read = MagicMock(return_value=b'{"Result":{"Files":[]}}')
            return resp

        with patch("urllib.request.urlopen", fake_urlopen):
            server._run_webserver_search("http://127.0.0.1:9", {"Q": "func.*Test"})

        body = json.loads(captured[0])
        assert body["Q"] == "func.*Test"  # plain string, not nested object


# ---------------------------------------------------------------------------
# _host_search — webserver path + fallback
# ---------------------------------------------------------------------------


class TestHostSearch:
    def _make_ready_server(self, tmp_path: Path) -> ZoektServer:
        """Server with _webserver_url already set (simulating a live webserver)."""
        server = _make_server(tmp_path)
        server._webserver_proc = MagicMock()
        server._webserver_proc.poll = MagicMock(return_value=None)  # still running
        server._webserver_url = "http://127.0.0.1:6070"
        server._webserver_ready.set()  # mark as ready so _ensure_webserver returns URL
        return server

    def test_uses_webserver_when_enabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATELIER_ZOEKT_WEBSERVER", "1")
        server = self._make_ready_server(tmp_path)
        expected = {"Result": {"Files": []}}

        with patch.object(server, "_run_webserver_search", return_value=expected) as mock_ws:
            with patch.object(server, "_run_host_search") as mock_cli:
                result = server._host_search({"Q": "needle"})

        assert result == expected
        mock_ws.assert_called_once()
        mock_cli.assert_not_called()

    def test_falls_back_to_cli_when_webserver_disabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATELIER_ZOEKT_WEBSERVER", "0")
        server = self._make_ready_server(tmp_path)
        cli_result = {"Result": {"Files": [{"FileName": "main.py"}]}}

        with patch.object(server, "_run_webserver_search") as mock_ws:
            with patch.object(server, "_run_host_search", return_value=cli_result) as mock_cli:
                result = server._host_search({"Q": "needle"})

        assert result == cli_result
        mock_ws.assert_not_called()
        mock_cli.assert_called_once()

    def test_falls_back_to_cli_on_webserver_http_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATELIER_ZOEKT_WEBSERVER", "1")
        server = self._make_ready_server(tmp_path)
        cli_result = {"Result": {"Files": []}}

        with patch.object(server, "_run_webserver_search", side_effect=urllib.error.URLError("timeout")):
            with patch.object(server, "_run_host_search", return_value=cli_result) as mock_cli:
                result = server._host_search({"Q": "needle"})

        assert result == cli_result
        mock_cli.assert_called_once()

    def test_dead_proc_cleared_after_webserver_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A dead webserver process must be torn down so next call retries startup."""
        monkeypatch.setenv("ATELIER_ZOEKT_WEBSERVER", "1")
        server = self._make_ready_server(tmp_path)
        # Simulate a dead process
        server._webserver_proc.poll = MagicMock(return_value=1)  # type: ignore[union-attr]
        cli_result = {"Result": {"Files": []}}

        with patch.object(server, "_run_webserver_search", side_effect=OSError("pipe broken")):
            with patch.object(server, "_run_host_search", return_value=cli_result):
                server._host_search({"Q": "needle"})

        # Webserver handles should be cleared
        assert server._webserver_proc is None
        assert server._webserver_url is None


# ---------------------------------------------------------------------------
# discover_zoekt_binary: go-bin probe
# ---------------------------------------------------------------------------


class TestDiscoverZoektBinaryGoBin:
    def test_finds_binaries_in_go_bin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Discovery must find zoekt in a Go-install directory even when not on PATH."""
        # Build a fake go/bin dir with all required executables
        go_bin = tmp_path / "go" / "bin"
        go_bin.mkdir(parents=True)
        for name in ("zoekt", "zoekt-index", "zoekt-git-index", "zoekt-webserver"):
            exe = go_bin / name
            exe.write_bytes(b"#!/bin/sh")
            exe.chmod(0o755)

        # Patch _GO_BIN_PROBE_DIRS to include our fake dir and remove real dirs
        monkeypatch.setattr(
            "atelier.infra.code_intel.zoekt.binary._GO_BIN_PROBE_DIRS",
            (go_bin,),
        )
        # shutil.which returns nothing (not on PATH)
        monkeypatch.setenv("ATELIER_ZOEKT_MODE", "installed")
        monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)

        res = discover_zoekt_binary(tmp_path)

        assert res.available is True
        assert res.source == "go-bin"
        assert res.path == (go_bin / "zoekt").resolve()

    def test_skips_incomplete_go_bin_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A dir that has zoekt but is missing zoekt-webserver must not resolve."""
        go_bin = tmp_path / "go" / "bin"
        go_bin.mkdir(parents=True)
        # Only place some of the required binaries
        for name in ("zoekt", "zoekt-index"):
            exe = go_bin / name
            exe.write_bytes(b"#!/bin/sh")
            exe.chmod(0o755)

        monkeypatch.setattr(
            "atelier.infra.code_intel.zoekt.binary._GO_BIN_PROBE_DIRS",
            (go_bin,),
        )
        monkeypatch.setenv("ATELIER_ZOEKT_MODE", "installed")
        monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)

        res = discover_zoekt_binary(tmp_path)

        assert res.available is False

    def test_system_path_takes_precedence_over_go_bin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """shutil.which results (PATH-based) should win over go-bin probing."""
        path_bin = tmp_path / "path_bin"
        path_bin.mkdir()
        path_zoekt = path_bin / "zoekt"
        path_zoekt.write_bytes(b"#!/bin/sh")
        path_zoekt.chmod(0o755)

        go_bin = tmp_path / "go" / "bin"
        go_bin.mkdir(parents=True)

        def fake_which(name: str) -> str | None:
            # Return path_bin versions for all required names
            candidate = path_bin / name
            candidate.write_bytes(b"#!/bin/sh")
            candidate.chmod(0o755)
            return str(candidate)

        monkeypatch.setattr("shutil.which", fake_which)
        monkeypatch.setattr(
            "atelier.infra.code_intel.zoekt.binary._GO_BIN_PROBE_DIRS",
            (go_bin,),
        )
        monkeypatch.setenv("ATELIER_ZOEKT_MODE", "installed")
        monkeypatch.delenv("ATELIER_ZOEKT_BIN", raising=False)

        res = discover_zoekt_binary(tmp_path)

        assert res.available is True
        assert res.source == "system-local"  # PATH wins
