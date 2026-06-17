from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_codex.sh"


def _run_without_codex(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    dirname = shutil.which("dirname")
    assert bash is not None
    assert dirname is not None

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    shutil.copy2(dirname, fake_bin / "dirname")

    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(home), "PATH": str(fake_bin)})
    return subprocess.run(
        [bash, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_codex_print_only_is_side_effect_free_without_cli(tmp_path: Path) -> None:
    result = _run_without_codex(tmp_path, "--print-only")

    assert result.returncode == 0, result.stderr
    assert "Manual Install Steps" in result.stdout
    assert not any((tmp_path / "home").iterdir())


def test_codex_missing_cli_skips_before_staging(tmp_path: Path) -> None:
    result = _run_without_codex(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "=== SKIPPED (codex CLI absent) ===" in result.stdout
    assert not any((tmp_path / "home").iterdir())


def test_codex_installer_avoids_gnu_only_readlink_flag() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert "readlink -f" not in content
    assert "resolve_real_path" in content
