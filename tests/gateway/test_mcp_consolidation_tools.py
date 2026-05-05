from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from atelier.core.foundation.models import ConsolidationCandidate
from atelier.core.foundation.store import ReasoningStore
from atelier.gateway.adapters import mcp_server
from atelier.gateway.adapters.mcp_server import _handle


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    response = _handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    assert response is not None
    assert "result" in response, response
    payload = json.loads(response["result"]["content"][0]["text"])
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


@pytest.fixture()
def mcp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    mcp_server._current_ledger = None
    mcp_server._realtime_ctx = None
    return root


def test_consolidation_inbox_and_decide_round_trip(mcp_root: Path) -> None:
    store = ReasoningStore(mcp_root)
    store.init()
    candidate = ConsolidationCandidate(
        id="cc-test",
        kind="duplicate_cluster",
        affected_block_ids=["rb-one", "rb-two"],
        proposed_action="merge",
        proposed_body="Merged checkout retry guidance.",
        evidence={"method": "unit"},
    )
    store.upsert_consolidation_candidate(candidate)

    inbox = _call("atelier_consolidation_inbox", {"limit": 10})

    assert [item["id"] for item in inbox["candidates"]] == ["cc-test"]

    decided = _call(
        "atelier_consolidation_decide",
        {"id": "cc-test", "decision": "approved", "reviewer": "tests"},
    )

    assert decided["decision"] == "approved"
    assert decided["decided_by"] == "tests"
    assert decided["decided_at"] is not None
