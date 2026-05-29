from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from atelier.core.runtime import AtelierRuntimeCore
from atelier.gateway.cli import cli


def _init_root(root: Path) -> None:
    result = CliRunner().invoke(cli, ["--root", str(root), "init"])
    assert result.exit_code == 0, result.output


def test_smart_read_cache_disabled_env_bypasses_hits(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root = tmp_path / ".atelier"
    _init_root(root)
    target = tmp_path / "module.py"
    target.write_text("def stable_gid():\n    return 'gid'\n", encoding="utf-8")

    monkeypatch.setenv("ATELIER_CACHE_DISABLED", "1")
    runtime = AtelierRuntimeCore(root)

    first = runtime.smart_read(target, max_lines=20)
    second = runtime.smart_read(target, max_lines=20)

    assert first["cached"] is False
    assert second["cached"] is False
    assert runtime.capability_status()["tool_supervision"]["cache_enabled"] is False
