"""N11 — platform/WSL native FS-watch policy guard (availability safety).

A recursive native FS watch on a WSL2 ``/mnt`` drive (or when the operator
sets ``ATELIER_DISABLE_FS_WATCH``) can stall MCP startup; these tests prove the
guard disables native inotify and that the watcher still works via the
poll/git-state signature fallback (``refresh`` never crashes when watching is
off).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier.infra.code_intel.scip.watcher import (
    ScipArtifactWatcher,
    _InotifyWatcher,
    native_fs_watch_disabled,
)


def test_env_kill_switch_disables_watch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATELIER_DISABLE_FS_WATCH", "1")
    assert native_fs_watch_disabled(tmp_path) is True


def test_env_falsey_value_keeps_watch_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATELIER_DISABLE_FS_WATCH", "0")
    assert native_fs_watch_disabled(tmp_path) is False


def test_wsl_mount_path_disables_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_DISABLE_FS_WATCH", raising=False)
    assert native_fs_watch_disabled(Path("/mnt/c/Users/dev/project")) is True
    assert native_fs_watch_disabled(Path("/mnt")) is True


def test_non_wsl_path_keeps_watch_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ATELIER_DISABLE_FS_WATCH", raising=False)
    # A path that merely contains 'mnt' but is not under /mnt must not match.
    assert native_fs_watch_disabled(tmp_path) is False


def test_disabled_inotify_watcher_is_a_safe_noop(tmp_path: Path) -> None:
    watcher = _InotifyWatcher(enabled=False)
    # No fd opened; native ops are inert.
    assert watcher.drain() is False
    watcher.sync_paths([tmp_path])  # must not raise
    watcher.close()  # must not raise


def test_refresh_falls_back_to_poll_state_when_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATELIER_DISABLE_FS_WATCH", "1")
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    seen: list[tuple[str, str]] = []

    def _state_sync(key: str, signature: str) -> bool:
        seen.append((key, signature))
        return True

    watcher = ScipArtifactWatcher(
        repo_root=tmp_path,
        cache_root=lambda: cache_root,
        state_sync=_state_sync,
    )
    assert watcher._fs_watch_enabled is False
    # The poll/git-state signature path still runs and never crashes.
    assert watcher.refresh([]) is True
    assert seen and seen[0][0] == "scip_artifact_signature"


def test_refresh_works_when_watch_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ATELIER_DISABLE_FS_WATCH", raising=False)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    watcher = ScipArtifactWatcher(
        repo_root=tmp_path,
        cache_root=lambda: cache_root,
        state_sync=lambda _key, _sig: False,
    )
    assert watcher._fs_watch_enabled is True
    assert watcher.refresh([]) is False
