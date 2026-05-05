from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from atelier.core.capabilities.memory_arbitration import arbitrate
from atelier.core.foundation.memory_models import MemoryBlock
from atelier.infra.embeddings.null_embedder import NullEmbedder


class _MemoryStore:
    def __init__(self, blocks: list[MemoryBlock]) -> None:
        self.blocks = blocks

    def list_blocks(
        self, agent_id: str, *, include_tombstoned: bool = False, limit: int = 500
    ) -> list[MemoryBlock]:
        _ = (include_tombstoned, limit)
        return [block for block in self.blocks if block.agent_id == agent_id]


def test_arbitration_adds_when_no_similar_blocks() -> None:
    decision = arbitrate(
        MemoryBlock(agent_id="atelier:code", label="style", value="prefer compact patches"),
        _MemoryStore([]),
        NullEmbedder(),
    )
    assert decision.op == "ADD"


def test_arbitration_emits_per_op_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted_ops: list[str] = []

    class _Counter:
        def __init__(self, name: str, description: str, labels: list[str]) -> None:
            _ = (name, description, labels)

        def labels(self, *, op: str) -> _Counter:
            emitted_ops.append(op)
            return self

        def inc(self) -> None:
            return None

    monkeypatch.setitem(sys.modules, "prometheus_client", SimpleNamespace(Counter=_Counter))
    monkeypatch.delattr(
        "atelier.core.capabilities.memory_arbitration.arbiter._emit_arbitration_metric.counter",
        raising=False,
    )

    arbitrate(
        MemoryBlock(agent_id="atelier:code", label="style", value="prefer compact patches"),
        _MemoryStore([]),
        NullEmbedder(),
    )

    assert emitted_ops == ["ADD"]


def test_arbitration_uses_ollama_json_for_similar_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = MemoryBlock(
        agent_id="atelier:code", label="style", value="prefer compact scoped patches"
    )
    new_fact = MemoryBlock(
        agent_id="atelier:code", label="style", value="prefer compact scoped edits"
    )
    monkeypatch.setattr(
        "atelier.core.capabilities.memory_arbitration.arbiter.chat",
        lambda messages, json_schema=None: {
            "op": "UPDATE",
            "target_block_id": existing.id,
            "merged_value": "prefer compact scoped patches and edits",
            "reason": "same preference",
        },
    )

    decision = arbitrate(new_fact, _MemoryStore([existing]), NullEmbedder())

    assert decision.op == "UPDATE"
    assert decision.target_block_id == existing.id
    assert decision.merged_value == "prefer compact scoped patches and edits"
