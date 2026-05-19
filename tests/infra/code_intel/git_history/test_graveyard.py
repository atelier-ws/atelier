from __future__ import annotations

import importlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_phase4_declares_pygit2_as_pinned_dependency() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"pygit2==1.19.2"' in pyproject


def test_git_history_bootstrap_requires_pygit2_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("atelier.infra.code_intel.git_history")
    monkeypatch.setattr(module, "_PYGIT2", None)
    monkeypatch.setattr(module, "_PYGIT2_IMPORT_ERROR", ImportError("boom"))

    with pytest.raises(module.GitHistoryBootstrapError) as excinfo:
        module.require_pygit2()

    assert "pygit2" in str(excinfo.value)
    assert "GitPython" in str(excinfo.value)
    assert "subprocess" in str(excinfo.value)
