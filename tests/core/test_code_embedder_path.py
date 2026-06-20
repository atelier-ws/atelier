from __future__ import annotations

from pathlib import Path

import pytest

from atelier.core.capabilities.code_context.embedding import SemanticSearchRanker
from atelier.core.capabilities.code_context.engine import (
    _LINEAGE_INDEX_VERSION,
    CodeContextEngine,
)
from atelier.core.capabilities.code_context.models import SymbolRecord


class _TaskAwareDummyEmbedder:
    dim = 2
    name = "dummy:code"

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("plain embed() should not be used for code-path embeddings")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(("query", texts))
        return [[1.0, 0.0] for _ in texts]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(("document", texts))
        return [[0.0, 1.0] for _ in texts]


def _symbol() -> SymbolRecord:
    return SymbolRecord(
        symbol_id="sym-1",
        repo_id="repo",
        file_path="src/auth.py",
        language="python",
        symbol_name="issue_access_token",
        qualified_name="src.auth.issue_access_token",
        kind="function",
        signature="def issue_access_token(user_id: str) -> str:",
        start_byte=0,
        end_byte=10,
        start_line=1,
        end_line=2,
        content_hash="abc123",
    )


def test_semantic_search_ranker_uses_task_aware_code_embedder(tmp_path: Path) -> None:
    embedder = _TaskAwareDummyEmbedder()
    ranker = SemanticSearchRanker(tmp_path, store_root=tmp_path, embedder=embedder)

    query_vector = ranker._embed_query("token lookup")
    symbol_vector = ranker._embed_symbol(_symbol(), "issue access token")

    assert query_vector == [1.0, 0.0]
    assert symbol_vector == [0.0, 1.0]
    assert embedder.calls == [
        ("query", ["token lookup"]),
        ("document", ["issue access token"]),
    ]


def test_lineage_ready_preserves_old_chunks_until_full_rebuild_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATELIER_LINEAGE_ENABLED", "1")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "orders.py").write_text("def total() -> int:\n    return 1\n", encoding="utf-8")
    engine = CodeContextEngine(tmp_path, db_path=tmp_path / "code.sqlite")

    with engine._connect() as conn:
        engine._init_schema(conn)
        conn.execute(
            """INSERT INTO commit_chunks
               (commit_sha, author_date, files_touched, symbols_touched,
                summary, summary_model, embedding, index_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("deadbeef", 1, '["src/orders.py"]', None, "old summary", "stub", b"\x00\x00\x80?", 1),
        )
        conn.executemany(
            "INSERT INTO engine_state(key, value) VALUES (?, ?)",
            [
                ("commit_lineage_head", "old-head"),
                ("commit_lineage_watermark", "deadbeef"),
                ("commit_lineage_embedder_name", "local"),
                ("commit_lineage_embedder_dim", "384"),
            ],
        )
        conn.commit()

    monkeypatch.setattr(engine, "_safe_current_head_sha", lambda: "new-head")
    monkeypatch.setattr(
        "atelier.infra.code_intel.git_history.embedder.embedder_name",
        lambda: "ollama:nomic-embed-text",
    )
    monkeypatch.setattr(
        "atelier.infra.code_intel.git_history.embedder.embedding_dim",
        lambda: 768,
    )

    started: list[bool] = []

    class _FakeThread:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def start(self) -> None:
            started.append(True)

    monkeypatch.setattr(
        "atelier.core.capabilities.code_context.engine.threading.Thread",
        _FakeThread,
    )

    engine._ensure_lineage_ready()

    with engine._connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM commit_chunks").fetchone()
        assert row is not None
        assert int(row["n"]) == 1

    assert engine._lineage_rebuild_full is True
    assert engine._lineage_thread is not None
    assert started == [True]
    assert _LINEAGE_INDEX_VERSION >= 2
