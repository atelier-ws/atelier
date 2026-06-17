"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from atelier.core.foundation.store import ContextStore
    from atelier.core.runtime import AtelierRuntimeCore
    from atelier.gateway.adapters.runtime import ContextRuntime


@pytest.fixture(autouse=True)
def _isolate_workspace_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Isolate tests from host workspace env vars and default runtime roots."""
    for env_var in (
        "ATELIER_WORKSPACE_ROOT",
        "CLAUDE_WORKSPACE_ROOT",
        "CURSOR_WORKSPACE_ROOT",
        "VSCODE_CWD",
        "ATELIER_LESSONS_ROOT",
        "ATELIER_STORE_ROOT",
        "ATELIER_MEM_ROOT",
    ):
        monkeypatch.delenv(env_var, raising=False)
    isolated_root = tmp_path / ".atelier"
    monkeypatch.setenv("ATELIER_ROOT", str(isolated_root))
    monkeypatch.setenv("ATELIER_STORE_ROOT", str(isolated_root))
    # Complete the isolation: point the workspace root at tmp_path too. Without
    # this, _workspace_root() falls through to os.getcwd() (the real repo), so
    # the new read/projection workspace-confinement rejects files tests create
    # under tmp_path. Tests that need a specific workspace set it themselves.
    monkeypatch.setenv("ATELIER_WORKSPACE_ROOT", str(tmp_path))
    yield


@pytest.fixture(autouse=True)
def _no_network_sync() -> Iterator[None]:
    """Block all outbound sync_usage calls so no test ever hits atelier.beseam.com."""
    with patch("atelier.core.service.sync.sync_usage", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _no_ollama() -> Iterator[None]:
    """Block real Ollama calls so no test waits on a local LLM.

    Patches _ollama_module() — the single gateway all ollama_client functions
    (summarize, chat) use — so the mock works even for callers that did
    ``from atelier.infra.internal_llm.ollama_client import summarize``.

    Tests that explicitly need LLM behaviour should override via monkeypatch.
    """
    from atelier.infra.internal_llm import OllamaUnavailable

    with patch(
        "atelier.infra.internal_llm.ollama_client._ollama_module",
        side_effect=OllamaUnavailable("ollama blocked in tests"),
    ):
        yield


@pytest.fixture(scope="session")
def retrieval_eval_runtime(tmp_path_factory: pytest.TempPathFactory) -> AtelierRuntimeCore:
    """Initialize atelier runtime and seed blocks once per session for retrieval evaluation."""
    from tests.core.test_retriever_eval import _ensure_eval_blocks_exist, _init_runtime

    # Note: Using tmp_path_factory to get a persistent session directory
    root = tmp_path_factory.mktemp("retrieval_eval_session")
    runtime = _init_runtime(root)
    _ensure_eval_blocks_exist(runtime)
    return runtime


@pytest.fixture()
def store(tmp_path: Path) -> ContextStore:
    from atelier.core.foundation.store import ContextStore

    root = tmp_path / "atelier"
    store = ContextStore(root)
    store.init()
    return store


@pytest.fixture()
def seeded_runtime(tmp_path: Path) -> Iterator[ContextRuntime]:
    import yaml

    from atelier.core.foundation.models import Rubric
    from atelier.core.foundation.parser import parse_block_markdown
    from atelier.gateway.adapters.runtime import ContextRuntime

    rt = ContextRuntime(root=tmp_path / "atelier")
    lessons_root = Path(__file__).resolve().parents[1] / ".lessons"
    blocks_dir = lessons_root / "blocks"
    rubrics_dir = lessons_root / "rubrics"
    for p in sorted(blocks_dir.glob("template_*.md")):
        rt.store.upsert_block(parse_block_markdown(p.read_text(encoding="utf-8")))
    for p in sorted(rubrics_dir.glob("template_*.yaml")):
        rt.store.upsert_rubric(Rubric.model_validate(yaml.safe_load(p.read_text(encoding="utf-8"))))
    yield rt
