from __future__ import annotations

import importlib
from typing import Any

import pytest

from atelier.gateway.adapters import mcp_server


def test_web_fetch_wrapper_renders_content_only(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = importlib.reload(importlib.import_module("atelier.gateway.adapters.web_fetch_mcp_server"))

    def fake_fetch_url(
        url: str,
        *,
        output_format: str,
        max_chars: int,
        timeout_s: float,
        include_meta: bool,
    ) -> dict[str, Any]:
        _ = (url, output_format, max_chars, timeout_s, include_meta)
        return {"content": "# Hello\n\nWorld", "format": "markdown", "tokens_saved": 12}

    monkeypatch.setattr("atelier.core.capabilities.web_fetch.fetch_url", fake_fetch_url)
    monkeypatch.setattr(mcp_server, "_append_workspace_savings", lambda *args, **kwargs: None)

    response = wrapper._handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "web_fetch", "arguments": {"url": "https://example.com"}},
        }
    )
    assert response is not None
    content_item = response["result"]["content"][0]
    assert content_item["type"] == "text"
    assert content_item["text"] == "# Hello\n\nWorld"
    assert content_item["saved"] == {"tokens": 12, "calls": 0}


def test_web_fetch_wrapper_lists_tool_in_stable_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = importlib.reload(importlib.import_module("atelier.gateway.adapters.web_fetch_mcp_server"))
    monkeypatch.delenv("ATELIER_DEV_MODE", raising=False)

    response = wrapper._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert response is not None
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "web_fetch" in names
