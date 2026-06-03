from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from atelier.gateway.adapters import mcp_server
from atelier.gateway.cli import cli


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    response = mcp_server._handle(request)
    assert isinstance(response, dict)
    return response


def _result(response: dict[str, Any]) -> dict[str, Any]:
    assert "result" in response, response
    payload = json.loads(response["result"]["content"][0]["text"])
    assert isinstance(payload, dict)
    return payload


@pytest.fixture()
def workflow_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    runner = CliRunner().invoke(cli, ["--root", str(root), "init"])
    assert runner.exit_code == 0, runner.output
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ATELIER_DEV_MODE", "1")
    mcp_server._current_ledger = None
    mcp_server._realtime_ctx = None
    mcp_server._remote_client = None
    return root


def test_workflow_run_tool_delegates_to_owned_runner(workflow_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
        seen["arguments"] = arguments
        return {"run_id": "run-123", "status": "success", "step_count": 2, "artifact_ids": []}

    monkeypatch.setattr(mcp_server, "_run_owned_workflow", fake_run_workflow)

    payload = _result(
        _call(
            "workflow_run",
            {
                "workflow": {
                    "workflow_id": "owned-review-loop",
                    "steps": [
                        {
                            "step_id": "read_spec",
                            "kind": "tool",
                            "tool": "read",
                            "args": {"path": "README.md"},
                        }
                    ],
                }
            },
        )
    )

    assert payload == {
        "run_id": "run-123",
        "status": "success",
        "step_count": 2,
        "artifact_ids": [],
    }
    assert seen["arguments"]["workflow"]["workflow_id"] == "owned-review-loop"


def test_workflow_run_tool_returns_runner_receipt_shape(workflow_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mcp_server,
        "_run_owned_workflow",
        lambda arguments: {
            "run_id": "run-456",
            "status": "failed",
            "step_count": 3,
            "failed_step_id": "review",
            "artifact_ids": ["trace-1"],
        },
    )

    payload = _result(
        _call(
            "workflow_run",
            {
                "workflow": {
                    "workflow_id": "owned-review-loop",
                    "steps": [
                        {
                            "step_id": "read_spec",
                            "kind": "tool",
                            "tool": "read",
                            "args": {"path": "README.md"},
                        }
                    ],
                }
            },
        )
    )

    assert payload["run_id"] == "run-456"
    assert payload["status"] == "failed"
    assert payload["step_count"] == 3
    assert payload["failed_step_id"] == "review"
    assert payload["artifact_ids"] == ["trace-1"]
