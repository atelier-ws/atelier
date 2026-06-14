"""WS11 G17 -- streamable-HTTP MCP transport + discovery manifest."""

from __future__ import annotations

from fastapi.testclient import TestClient

from atelier.gateway.adapters.mcp_http import (
    MCP_DISCOVERY_PATH,
    MCP_HTTP_PATH,
    create_mcp_http_app,
)


def _client() -> TestClient:
    return TestClient(create_mcp_http_app())


def test_discovery_manifest_served() -> None:
    resp = _client().get(MCP_DISCOVERY_PATH)
    assert resp.status_code == 200
    manifest = resp.json()
    assert manifest["transport"]["type"] == "streamable-http"
    assert manifest["transport"]["endpoint"] == MCP_HTTP_PATH
    assert isinstance(manifest["tools"], list) and manifest["tools"]


def test_tools_list_over_http() -> None:
    resp = _client().post(
        MCP_HTTP_PATH,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert "read" in names  # a public tool is advertised over HTTP too
    assert "scan" not in names  # hidden tools stay hidden across transports


def test_initialize_over_http() -> None:
    resp = _client().post(
        MCP_HTTP_PATH,
        json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["serverInfo"]["name"]


def test_parse_error_returns_jsonrpc_error() -> None:
    resp = _client().post(MCP_HTTP_PATH, content=b"not json")
    assert resp.status_code == 200
    assert resp.json()["error"]["code"] == -32700
