"""Tests for MCP remote mode (P5).

Validates that:
- Local mode still works as before.
- Remote mode routes the 5 supported tools through RemoteClient.
- Response shape is the same whether local or remote.
- Service unavailable returns a structured error dict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from atelier.gateway.adapters.mcp_server import _REMOTE_TOOLS, _handle

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_MCP_MODE", raising=False)


@pytest.fixture()
def remote_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_MODE", "remote")
    # Reset the module-level cache between tests.
    import atelier.gateway.adapters.mcp_server as m

    m._remote_client = None


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    return _handle(req)  # type: ignore[return-value]


def _mock_client(return_values: dict[str, dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    for method_name, retval in return_values.items():
        getattr(client, method_name).return_value = retval
    return client


# --------------------------------------------------------------------------- #
# Local mode                                                                  #
# --------------------------------------------------------------------------- #


def test_mcp_local_mode_still_works(local_mode: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_reasoning_context works in local mode with an empty store."""
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / ".atelier"))

    from atelier.infra.storage.sqlite_store import SQLiteStore

    st = SQLiteStore(tmp_path / ".atelier")
    st.init()

    resp = _call_tool("atelier_get_reasoning_context", {"task": "deploy the app"})
    assert resp["result"]["content"][0]["type"] == "text"
    text = resp["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert "context" in payload


def test_initialize_request_returns_server_info(local_mode: None) -> None:
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
    }
    resp = _handle(req)
    assert resp is not None
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "atelier-reasoning"


def test_tools_list_returns_all_tools(local_mode: None) -> None:
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = _handle(req)
    assert resp is not None
    tools = {t["name"] for t in resp["result"]["tools"]}
    for remote_tool in _REMOTE_TOOLS:
        assert remote_tool in tools
    assert "atelier_get_reasoning_context" in tools
    assert "atelier_compress_context" in tools


# --------------------------------------------------------------------------- #
# Remote mode — happy path                                                    #
# --------------------------------------------------------------------------- #


def test_remote_check_plan_same_shape(remote_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """check_plan in remote mode returns the same top-level keys."""
    expected = {
        "status": "pass",
        "warnings": [],
        "suggested_plan": [],
        "matched_blocks": [],
    }
    client = _mock_client({"check_plan": expected})

    import atelier.gateway.adapters.mcp_server as m

    m._remote_client = client

    resp = _call_tool("atelier_check_plan", {"task": "deploy", "plan": ["step 1"]})
    assert resp is not None
    assert "result" in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "status" in payload
    assert payload["status"] == "pass"


def test_remote_get_reasoning_context_same_shape(remote_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {"context": "Here are the relevant procedures."}
    client = _mock_client({"get_reasoning_context": expected})

    import atelier.gateway.adapters.mcp_server as m

    m._remote_client = client

    resp = _call_tool("atelier_get_reasoning_context", {"task": "publish product"})
    assert "result" in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["context"] == "Here are the relevant procedures."


def test_remote_record_trace_same_shape(remote_mode: None, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {"id": "trace-abc-123"}
    client = _mock_client({"record_trace": expected})

    import atelier.gateway.adapters.mcp_server as m

    m._remote_client = client

    resp = _call_tool(
        "atelier_record_trace",
        {"agent": "test", "domain": "e2e", "task": "deploy", "status": "success"},
    )
    assert "result" in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "id" in payload


# --------------------------------------------------------------------------- #
# Remote mode — error handling                                                #
# --------------------------------------------------------------------------- #


def test_remote_service_unavailable_returns_structured_error(
    remote_mode: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the remote service is unreachable, the MCP handler returns a JSON-RPC error."""
    from urllib.error import URLError

    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise URLError("Connection refused")

    import atelier.gateway.adapters.mcp_server as m
    import atelier.gateway.adapters.remote_client as rc

    # Create a real RemoteClient whose underlying urlopen will fail.
    real_client = rc.RemoteClient(base_url="http://127.0.0.1:1")  # port 1 is always closed
    m._remote_client = real_client

    # Monkeypatch urlopen to raise immediately.
    with patch("urllib.request.urlopen", side_effect=URLError("Connection refused")):
        resp = _call_tool("check_plan", {"task": "t", "plan": ["s"]})

    # The MCP wrapper must return a structured error, not raise.
    assert resp is not None
    # Either the result contains an "ok": False dict OR it's a JSON-RPC error.
    if "error" in resp:
        assert "message" in resp["error"]
    else:
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload.get("ok") is False or "error" in payload


# --------------------------------------------------------------------------- #
# Remote client unit tests                                                    #
# --------------------------------------------------------------------------- #


def test_remote_client_routes_correctly() -> None:
    """RemoteClient methods call the right paths."""
    from unittest.mock import patch as _patch

    from atelier.gateway.adapters.remote_client import RemoteClient

    client = RemoteClient(base_url="http://localhost:8787", api_key="key")

    captured: list[tuple[str, str]] = []

    def _fake_request(self: Any, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        captured.append((method, path))
        return {"ok": True}

    with _patch.object(RemoteClient, "_request", _fake_request):
        client.get_reasoning_context({"task": "t"})
        client.check_plan({"task": "t", "plan": []})
        client.rescue_failure({"task": "t", "error": "e"})
        client.run_rubric_gate({"rubric_id": "r", "checks": {}})
        client.record_trace({"agent": "a", "domain": "d", "task": "t", "status": "success"})

    paths = [p for _, p in captured]
    assert "/v1/reasoning/context" in paths
    assert "/v1/reasoning/check-plan" in paths
    assert "/v1/reasoning/rescue" in paths
    assert "/v1/rubrics/run" in paths
    assert "/v1/traces" in paths
