from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from atelier.gateway.adapters import mcp_server
from atelier.gateway.adapters.mcp_server import TOOLS, _handle
from atelier.infra.storage.memory_store import MemorySidecarUnavailable


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
    return response


def _payload(response: dict[str, Any]) -> Any:
    assert "result" in response, response
    return json.loads(response["result"]["content"][0]["text"])


@pytest.fixture()
def mcp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    mcp_server._current_ledger = None
    mcp_server._realtime_ctx = None
    return root


def test_memory_tools_are_registered() -> None:
    assert "atelier_memory_upsert_block" in TOOLS
    assert "atelier_memory_get_block" in TOOLS


def test_memory_upsert_and_get_round_trip(mcp_root: Path) -> None:
    _ = mcp_root
    result = _payload(
        _call(
            "atelier_memory_upsert_block",
            {
                "agent_id": "atelier:code",
                "label": "scratch",
                "value": "hello",
                "pinned": True,
                "metadata": {"source": "test"},
            },
        )
    )
    assert result["version"] == 1

    block = _payload(
        _call("atelier_memory_get_block", {"agent_id": "atelier:code", "label": "scratch"})
    )
    assert block["id"] == result["id"]
    assert block["value"] == "hello"
    assert block["pinned"] is True


def test_memory_get_returns_null_on_miss(mcp_root: Path) -> None:
    _ = mcp_root
    assert (
        _payload(
            _call("atelier_memory_get_block", {"agent_id": "atelier:code", "label": "missing"})
        )
        is None
    )


def test_memory_stale_version_maps_to_409(mcp_root: Path) -> None:
    _ = mcp_root
    _payload(
        _call(
            "atelier_memory_upsert_block",
            {"agent_id": "atelier:code", "label": "scratch", "value": "v1"},
        )
    )
    _payload(
        _call(
            "atelier_memory_upsert_block",
            {
                "agent_id": "atelier:code",
                "label": "scratch",
                "value": "v2",
                "expected_version": 1,
            },
        )
    )
    response = _call(
        "atelier_memory_upsert_block",
        {
            "agent_id": "atelier:code",
            "label": "scratch",
            "value": "stale",
            "expected_version": 1,
        },
    )
    assert response["error"]["code"] == 409


def test_memory_sidecar_unavailable_maps_to_503(
    monkeypatch: pytest.MonkeyPatch, mcp_root: Path
) -> None:
    _ = mcp_root

    class DownStore:
        def get_block(self, agent_id: str, label: str) -> None:
            _ = (agent_id, label)
            raise MemorySidecarUnavailable("sidecar down")

    monkeypatch.setattr(mcp_server, "_memory_store", lambda: DownStore())
    response = _call(
        "atelier_memory_upsert_block",
        {"agent_id": "atelier:code", "label": "scratch", "value": "hello"},
    )
    assert response["error"]["code"] == 503


def test_memory_upsert_rejects_likely_secret_leakage(mcp_root: Path) -> None:
    _ = mcp_root
    response = _call(
        "atelier_memory_upsert_block",
        {
            "agent_id": "atelier:code",
            "label": "leak",
            "value": "AKIAIOSFODNN7EXAMPLE secretvalue",
        },
    )
    assert "error" in response
    assert "likely secret leakage" in response["error"]["message"]
