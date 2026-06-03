from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
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


def test_workflow_run_executes_agent_steps_by_default(workflow_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_resolve_swarm_runner_command(
        *,
        runner: str | None,
        runner_model: str | None,
        runner_args: list[str] | tuple[str, ...],
        child_command: list[str] | tuple[str, ...],
        prompt_template: str,
    ) -> list[str]:
        seen["runner"] = runner
        seen["runner_model"] = runner_model
        seen["prompt"] = prompt_template
        return ["fake-runner", prompt_template]

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        seen["command"] = command
        seen["cwd"] = cwd
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"verdict":"PASS","checklist":["done"],"missing":[]}',
            stderr="",
        )

    monkeypatch.setattr(mcp_server, "resolve_swarm_runner_command", fake_resolve_swarm_runner_command)
    monkeypatch.setattr("subprocess.run", fake_run)

    payload = mcp_server._run_owned_workflow(
        {
            "workflow": {
                "workflow_id": "owned-review-loop",
                "steps": [
                    {
                        "step_id": "agent_step",
                        "kind": "agent",
                        "prompt": "Inspect README.md and return a JSON verdict.",
                    }
                ],
            }
        }
    )

    assert payload["status"] == "success"
    assert payload["step_count"] == 1
    assert seen["runner"] == mcp_server._workflow_runner_profile()
    assert seen["runner_model"] == "claude-opus-4.8"
    assert seen["cwd"].name == "workspace"
    assert "Inspect README.md" in seen["prompt"]


def test_workflow_run_applies_explicit_owned_route(workflow_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    monkeypatch.setattr(
        mcp_server,
        "_select_owned_execution_route",
        lambda **_kwargs: SimpleNamespace(
            mode="explicit",
            provider="openai",
            model="gpt-4o",
            runner="codex",
            transport="openai",
        ),
    )
    monkeypatch.setattr(
        mcp_server,
        "execute_owned_prompt",
        lambda prompt, **kwargs: (
            seen.update({"prompt": prompt, "decision": kwargs["decision"]})
            or SimpleNamespace(
                output='{"verdict":"PASS","checklist":["done"],"missing":[]}',
                receipt=SimpleNamespace(
                    to_dict=lambda: {
                        "status": "done",
                        "mode": "explicit",
                        "selected_provider": "openai",
                        "selected_model": "gpt-4o",
                        "selected_runner": "codex",
                        "selected_transport": "openai",
                        "executed_provider": "openai",
                        "executed_model": "gpt-4o",
                        "executed_runner": "codex",
                        "executed_transport": "openai",
                        "request_id": "req-1",
                        "input_tokens": 21,
                        "output_tokens": 7,
                        "cache_read_input_tokens": 5,
                        "cache_write_input_tokens": 0,
                        "duration_seconds": 1.2,
                        "cost_usd": 0.0,
                        "rerouted": False,
                        "attempts": [],
                        "error": "",
                    },
                    executed_model="gpt-4o",
                    input_tokens=21,
                    output_tokens=7,
                    cache_read_input_tokens=5,
                    cache_write_input_tokens=0,
                    modeled_cache_read_input_tokens=0,
                    stable_prefix_hash="",
                    prefix_invalidated_reason="",
                    cache_evidence="none",
                    duration_seconds=1.2,
                    cost_usd=0.0,
                ),
            )
        ),
    )

    payload = mcp_server._run_owned_workflow(
        {
            "workflow": {
                "workflow_id": "owned-review-loop",
                "steps": [
                    {
                        "step_id": "agent_step",
                        "kind": "agent",
                        "prompt": "Inspect README.md and return a JSON verdict.",
                    }
                ],
            },
            "route": {
                "mode": "explicit",
                "provider": "openai",
                "model": "gpt-4o",
                "runner": "codex",
            },
        }
    )

    assert payload["status"] == "success"
    state = mcp_server._read_workspace_session_state()
    step_output = state["workflow"]["task_outputs"]["agent_step"]
    assert seen["decision"].runner == "codex"
    assert seen["decision"].transport == "openai"
    assert step_output["execution_receipt"]["executed_transport"] == "openai"


def test_workflow_run_auto_route_failure_does_not_fallback_to_native_subprocess(
    workflow_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from atelier.core.capabilities.cross_vendor_routing.router import NoFeasibleRouteError

    monkeypatch.setattr(
        mcp_server,
        "_select_owned_execution_route",
        lambda **_kwargs: (_ for _ in ()).throw(NoFeasibleRouteError("no owned route")),
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("native subprocess should not run")),
    )

    payload = mcp_server._run_owned_workflow(
        {
            "workflow": {
                "workflow_id": "owned-review-loop",
                "steps": [
                    {
                        "step_id": "agent_step",
                        "kind": "agent",
                        "prompt": "Inspect README.md and return a JSON verdict.",
                    }
                ],
            },
            "route": {"mode": "auto"},
        }
    )

    assert payload["status"] == "failed"
    state = mcp_server._read_workspace_session_state()
    step_output = state["workflow"]["task_outputs"]["agent_step"]
    assert "owned route selection failed" in step_output["error"]
    assert step_output["execution_receipt"]["mode"] == "auto"
    assert step_output["execution_receipt"]["status"] == "failed"


def test_workflow_run_pauses_for_plan_review_and_resumes_on_approval(
    workflow_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_resolve_swarm_runner_command(
        *,
        runner: str | None,
        runner_model: str | None,
        runner_args: list[str] | tuple[str, ...],
        child_command: list[str] | tuple[str, ...],
        prompt_template: str,
    ) -> list[str]:
        return ["fake-runner", prompt_template]

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        prompt = command[-1]
        calls.append(prompt)
        if "Draft the implementation plan." in prompt:
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="plan ready", stderr="")
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="applied", stderr="")

    monkeypatch.setattr(mcp_server, "resolve_swarm_runner_command", fake_resolve_swarm_runner_command)
    monkeypatch.setattr("subprocess.run", fake_run)

    workflow = {
        "workflow_id": "review-gated",
        "steps": [
            {"step_id": "plan", "kind": "agent", "prompt": "Draft the implementation plan."},
            {
                "step_id": "execute",
                "kind": "agent",
                "prompt": "Apply the approved plan.",
                "requires_plan_review": True,
            },
        ],
    }

    paused = mcp_server._run_owned_workflow({"workflow": workflow})
    assert paused["status"] == "awaiting_review"
    assert paused["paused_step_id"] == "execute"

    resumed = mcp_server._run_owned_workflow({"workflow": workflow, "plan_review": {"decision": "approve"}})
    assert resumed["status"] == "success"
    assert calls == ["Draft the implementation plan.", "Apply the approved plan."]
