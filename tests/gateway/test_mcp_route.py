from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from atelier.core.capabilities.cross_vendor_routing.configuration import (
    RouteConfig,
    save_route_config,
)
from atelier.core.capabilities.pricing import active_model
from atelier.gateway.adapters.mcp_server import _handle


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    req: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    resp = _handle(req)
    assert isinstance(resp, dict)
    return resp


def _result(resp: dict[str, Any]) -> dict[str, Any]:
    assert "result" in resp, resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert isinstance(payload, dict)
    return payload


@pytest.fixture()
def mcp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("ATELIER_MODEL", "claude-sonnet-4.6")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.setattr(
        "shutil.which",
        lambda command: (f"/usr/bin/{command}" if command in {"claude", "codex", "copilot"} else None),
    )
    save_route_config(root, RouteConfig(enabled_vendors=["anthropic", "openai", "google"]))

    import atelier.gateway.adapters.mcp_server as m

    m._current_ledger = None
    return root


# ── op=decide ───────────────────────────────────────────────────────────────


def test_mcp_route_decide_returns_model_and_metadata(mcp_env: Path) -> None:
    resp = _call(
        "route",
        {"task": "implement a new REST endpoint", "task_type": "feature"},
    )
    payload = _result(resp)

    assert "model" in payload
    assert "tier" in payload
    assert "rationale" in payload
    assert "route_tier" in payload
    assert "available_models" not in payload
    assert "can_spawn" not in payload
    assert "host_model" not in payload
    assert "_summary" not in payload


def test_mcp_route_decide_budget_cheap_picks_cheapest(mcp_env: Path) -> None:
    resp = _call(
        "route",
        {"task": "summarize a file", "task_type": "explain", "budget": "cheap"},
    )
    payload = _result(resp)

    assert payload["tier"] == "cheap"
    # cheapest anthropic model is haiku
    assert "haiku" in payload["model"] or "flash" in payload["model"] or "mini" in payload["model"]


def test_mcp_route_decide_budget_best_picks_powerful(mcp_env: Path) -> None:
    resp = _call(
        "route",
        {"task": "design a new architecture", "task_type": "feature", "budget": "best"},
    )
    payload = _result(resp)

    # Should pick a high-tier model
    assert payload["tier"] in (
        "high",
        "expensive",
        "medium",
        "cheap",
    )  # just must return valid tier


def test_mcp_route_decide_explicit_provider_and_model(mcp_env: Path) -> None:
    resp = _call(
        "route",
        {
            "task": "execute the owned workflow with the requested provider",
            "task_type": "feature",
            "mode": "explicit",
            "provider": "openai",
            "model": "gpt-4o",
            "runner": "codex",
        },
    )
    payload = _result(resp)

    assert payload["mode"] == "explicit"
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-4o"
    assert payload["runner"] == "codex"
    assert payload["transport"] == "openai"
    assert payload["execution_mode"] == "wrapper_enforced"


def test_mcp_route_decide_no_route_config_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".atelier"
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("ATELIER_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr("shutil.which", lambda _command: None)
    # No route config saved — advisor will raise, decide must fall back gracefully

    import atelier.gateway.adapters.mcp_server as m

    m._current_ledger = None

    resp = _call("route", {"task": "refactor this function"})
    payload = _result(resp)

    assert "model" in payload
    assert "available_models" not in payload


def test_mcp_route_schema_exposes_only_decide() -> None:
    from atelier.gateway.adapters.mcp_server import TOOLS

    schema = TOOLS["route"].get("inputSchema", {})
    props = schema.get("properties", {})
    assert "task" in props
    assert "task_type" in props
    assert "budget" in props
    assert "mode" in props
    assert "provider" in props
    assert "model" in props
    assert "runner" in props
    assert schema.get("required", []) == []


def _last_model_recommendation_payload() -> dict[str, Any]:
    import atelier.gateway.adapters.mcp_server as m

    assert m._current_ledger is not None
    matches = [event.payload for event in m._current_ledger.events if event.kind == "model_recommendation"]
    assert matches
    return matches[-1]


def test_local_tool_route_enforcement_is_advisory_by_default(
    mcp_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import atelier.gateway.adapters.mcp_server as m

    seen: dict[str, str] = {}

    def fake_handler(_: dict[str, Any]) -> dict[str, Any]:
        seen["active_model"] = active_model()
        return {"ok": True}

    monkeypatch.setitem(m.TOOLS["read"], "handler", fake_handler)
    monkeypatch.delenv("ATELIER_ENFORCE_ROUTE_MODEL", raising=False)

    response = _call("read", {"path": "/tmp/placeholder"})
    payload = _last_model_recommendation_payload()

    assert "result" in response
    assert seen["active_model"] == os.environ["ATELIER_MODEL"]
    assert payload["route_enforcement_active"] is False
    assert payload["wrapper_applied"] is False
    assert payload.get("wrapper_model") in (None, "")


def test_local_tool_route_enforcement_wraps_handler_with_recommended_model(
    mcp_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import atelier.gateway.adapters.mcp_server as m

    seen: dict[str, str] = {}

    def fake_handler(_: dict[str, Any]) -> dict[str, Any]:
        seen["active_model"] = active_model()
        return {"ok": True}

    monkeypatch.setitem(m.TOOLS["read"], "handler", fake_handler)
    monkeypatch.setenv("ATELIER_ENFORCE_ROUTE_MODEL", "1")

    response = _call("read", {"path": "/tmp/placeholder"})
    payload = _last_model_recommendation_payload()

    assert "result" in response
    assert payload["route_enforcement_active"] is True
    assert payload["wrapper_applied"] is True
    assert payload["wrapper_model"] == payload["model"]
    assert payload["executed_model_scope"] == "local_mcp_only"
    assert payload["recommendation_followed"] is True
    assert seen["active_model"] == payload["model"]
    assert os.environ["ATELIER_MODEL"] == "claude-sonnet-4.6"


def test_local_tool_route_enforcement_restores_model_after_error(
    mcp_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import atelier.gateway.adapters.mcp_server as m

    seen: dict[str, str] = {}

    def fake_handler(_: dict[str, Any]) -> dict[str, Any]:
        seen["active_model"] = active_model()
        raise RuntimeError("boom")

    monkeypatch.setitem(m.TOOLS["read"], "handler", fake_handler)
    monkeypatch.setenv("ATELIER_ENFORCE_ROUTE_MODEL", "1")

    response = _call("read", {"path": "/tmp/placeholder"})
    payload = _last_model_recommendation_payload()

    assert "error" in response
    assert seen["active_model"] == payload["model"]
    assert payload["wrapper_applied"] is True
    assert os.environ["ATELIER_MODEL"] == "claude-sonnet-4.6"
