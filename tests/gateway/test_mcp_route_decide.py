from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from atelier.gateway.adapters.mcp_server import TOOLS, _handle


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

    import atelier.gateway.adapters.mcp_server as m

    m._current_ledger = None
    return root


def test_mcp_route_decide_tool_registered() -> None:
    assert "atelier_route_decide" in TOOLS


def test_mcp_route_decide_returns_decision(mcp_env: Path) -> None:
    resp = _call(
        "atelier_route_decide",
        {
            "user_goal": "Summarize docs updates",
            "repo_root": ".",
            "task_type": "docs",
            "risk_level": "low",
            "changed_files": ["README.md"],
            "step_type": "plan",
            "step_index": 0,
            "evidence_summary": {"confidence": 0.95, "estimated_input_tokens": 120},
        },
    )
    payload = _result(resp)

    assert payload["step_type"] == "plan"
    assert payload["risk_level"] == "low"
    assert payload["tier"] in {"cheap", "mid", "premium", "deterministic"}
    assert "reason" in payload
