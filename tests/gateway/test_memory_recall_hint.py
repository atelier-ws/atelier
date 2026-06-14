from __future__ import annotations

from typing import Any

import pytest

from atelier.gateway.adapters import mcp_server


class _FakeRecall:
    def __init__(self, passages: list[dict[str, Any]]) -> None:
        self._passages = passages

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {"passages": self._passages}


class _FakeService:
    def __init__(self, passages: list[dict[str, Any]]) -> None:
        self._passages = passages

    def recall(self, **_kwargs: Any) -> _FakeRecall:
        return _FakeRecall(self._passages)


def test_empty_recall_gets_helpful_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "_memory_service", lambda: _FakeService([]))
    out = mcp_server._memory_recall(None, "anything")
    assert "hint" in out
    assert "store_fact" in out["hint"]


def test_nonempty_recall_has_no_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "_memory_service", lambda: _FakeService([{"text": "x"}]))
    out = mcp_server._memory_recall(None, "anything")
    assert "hint" not in out
    assert out["passages"] == [{"text": "x"}]
