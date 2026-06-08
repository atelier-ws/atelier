from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.memory import MemoryService
from atelier.infra.embeddings.null_embedder import NullEmbedder
from atelier.infra.storage.sqlite_memory_store import SqliteMemoryStore


def _service(tmp_path: Path) -> MemoryService:
    return MemoryService(
        store=SqliteMemoryStore(tmp_path / "atelier"),
        embedder=NullEmbedder(),
        redactor=lambda value: value,
    )


def test_store_list_and_get_fact(tmp_path: Path) -> None:
    service = _service(tmp_path)

    stored = service.store_fact(
        agent_id="atelier:code",
        subject="workflow preference",
        fact="Prefer canonical memory operations.",
        citations='User input: "canonical"',
        reason="Keeps host surfaces consistent.",
        scope="user",
    )

    assert stored.fact == "Prefer canonical memory operations."
    assert stored.scope == "user"
    assert service.list_facts(agent_id="atelier:code") == [stored]
    assert service.get_fact(agent_id="atelier:code", fact_id=stored.id) == stored


def test_vote_fact_preserves_response_shape(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.store_fact(
        agent_id="atelier:code",
        subject="workflow preference",
        fact="Prefer canonical memory operations.",
        scope="repository",
    )

    voted = service.vote_fact(
        agent_id="atelier:code",
        fact="Prefer canonical memory operations.",
        direction="upvote",
        reason="Useful across hosts.",
        scope="repository",
    )

    assert voted.fact == "Prefer canonical memory operations."
    assert voted.scope == "repository"
    assert voted.direction == "upvote"


def test_share_fact_uses_visibility_scope_without_overwriting_fact_scope(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "atelier")
    service = MemoryService(store=store, embedder=NullEmbedder(), redactor=lambda value: value)
    stored = service.store_fact(
        agent_id="atelier:code",
        subject="testing",
        fact="Repository facts are not workspace visibility metadata.",
        scope="repository",
    )

    shared = service.share_fact(
        agent_id="atelier:code",
        fact_id=stored.id,
        workspace_id="workspace-1",
        shared_by_user_id="admin@example.com",
    )

    block = next(block for block in store.list_blocks("atelier:code") if block.id == shared.id)
    assert shared.scope == "repository"
    assert block.metadata["scope"] == "repository"
    assert block.metadata["fact_scope"] == "repository"
    assert block.metadata["visibility_scope"] == "shared"
    assert block.metadata["workspace_id"] == "workspace-1"
