from __future__ import annotations

import json
from pathlib import Path

import pytest

from atelier.gateway.adapters.mcp_server import (
    _emit_model_recommendation,
    _model_recommendation_state,
    _route_outcome_calibration,
    _workspace_session_state_file,
)
from atelier.infra.runtime.run_ledger import RunLedger


@pytest.fixture()
def workflow_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))
    return root


def test_model_recommendation_state_prefers_persisted_workflow_phase(workflow_env: Path) -> None:
    path = _workspace_session_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"workflow": {"current_step": "planning", "session_phase": "transition", "sticky_window": 1}}),
        encoding="utf-8",
    )
    led = RunLedger(root=workflow_env)

    state = _model_recommendation_state(led, {})

    assert state["workflow_step"] == "planning"
    assert state["session_phase"] == "transition"


def test_legacy_route_stickiness_resets_when_workflow_step_changes(workflow_env: Path) -> None:
    path = _workspace_session_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"workflow": {"current_step": "planning", "session_phase": "transition", "sticky_window": 2}}),
        encoding="utf-8",
    )
    led = RunLedger(root=workflow_env)

    first = _emit_model_recommendation("read", {"task": "explain briefly"}, led)
    second = _emit_model_recommendation("Agent", {"task": "design an end-to-end migration plan"}, led)

    assert first["decision"] == "baseline"
    assert second["decision"] == "sticky"
    assert second["tier"] == "cheap"

    path.write_text(
        json.dumps({"workflow": {"current_step": "execution", "session_phase": "execute", "sticky_window": 2}}),
        encoding="utf-8",
    )

    third = _emit_model_recommendation("Agent", {"task": "design an end-to-end migration plan"}, led)

    assert third["decision"] == "baseline"
    assert third["tier"] == "expensive"


def test_route_outcome_calibration_uses_workspace_outcomes(workflow_env: Path) -> None:
    path = _workspace_session_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "workflow": {"current_step": "planning", "session_phase": "transition", "sticky_window": 1},
                "route_outcomes": [
                    {
                        "tool": "read",
                        "recommendation_followed": True,
                        "scored_state": {"session_phase": "transition"},
                        "outcome_window": {"outcome_score": 0.9},
                    },
                    {
                        "tool": "read",
                        "recommendation_followed": False,
                        "scored_state": {"session_phase": "transition"},
                        "outcome_window": {"outcome_score": 0.4},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _route_outcome_calibration("read", {"session_phase": "transition"})

    assert payload["route_outcome_score_delta"] == 0.5
    assert payload["route_outcome_samples"] == 2
