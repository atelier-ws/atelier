"""Pro entitlement gates on CLI control surfaces (recall, router, zoekt).

Free installs (no `atelier_pro` overlay, not signed in) must block these
commands with an upsell; a Pro install (overlay + Pro plan) opens the gate.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from atelier.core.capabilities import pro_bridge
from atelier.core.capabilities.licensing import entitlements
from atelier.gateway.cli import cli
from tests.helpers import deny_oauth, grant_oauth_pro, init_store_at


def _invoke(root: Path, *args: str) -> Result:
    return CliRunner().invoke(cli, ["--root", str(root), *args])


def _install_overlay() -> None:
    pkg = types.ModuleType("atelier_pro")
    pkg.FEATURES = frozenset({"session_recall", "model_routing", "code_search"})  # type: ignore[attr-defined]
    sys.modules["atelier_pro"] = pkg
    pro_bridge.reset_cache()


def _remove_overlay() -> None:
    sys.modules.pop("atelier_pro", None)
    pro_bridge.reset_cache()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    _remove_overlay()
    # Isolate the auth store away from any real ~/.atelier and force signed-out.
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "lic"))
    deny_oauth(monkeypatch)
    yield
    _remove_overlay()
    entitlements.reload()


GATED = [
    ("recall", "search", "hello"),
    ("router", "start"),
    ("zoekt", "index"),
    ("knowledge", "extract"),
    ("swarm", "start"),
    ("memory", "find", "hello"),
]


@pytest.mark.parametrize("args", GATED)
def test_free_install_blocks_pro_cli(tmp_path: Path, args: tuple[str, ...]) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    res = _invoke(root, *args)
    assert res.exit_code != 0
    assert "Atelier Pro feature" in res.output


def test_pro_install_opens_recall_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    grant_oauth_pro(monkeypatch)
    _install_overlay()
    entitlements.reload()

    root = tmp_path / "a"
    init_store_at(str(root))
    res = _invoke(root, "recall", "search", "hello")
    # Gate opened: the command ran (no matches in an empty index) instead of the upsell.
    assert "Atelier Pro feature" not in res.output
    assert res.exit_code == 0, res.output
