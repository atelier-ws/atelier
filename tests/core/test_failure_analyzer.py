"""Tests for FailureAnalyzer clustering and proposal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atelier.core.improvement.failure_analyzer import FailureAnalyzer, analyze_failures


def _snap(session_id: str, env: str, error_sig: str, status: str = "failed") -> dict[str, Any]:
    return {
        "session_id": session_id,
        "environment_id": env,
        "status": status,
        "events": [
            {
                "kind": "command_result",
                "at": "2026-01-01T00:00:00+00:00",
                "summary": "pytest",
                "payload": {"ok": False, "error_signature": error_sig},
            }
        ],
    }


def test_analyze_clusters_by_env_and_fingerprint() -> None:
    snaps = [
        _snap("r1", "env_debugging_loop", "errA"),
        _snap("r2", "env_debugging_loop", "errA"),
        _snap("r3", "env_debugging_loop", "errB"),
    ]
    clusters = analyze_failures(snaps)
    assert any(len(c.trace_ids) == 2 for c in clusters)
    assert any(c.fingerprint == "errA" for c in clusters)
    assert any(c.fingerprint == "errB" for c in clusters)


def test_analyzer_proposes_concrete_fields() -> None:
    snaps = [_snap("r1", "env_debugging_loop", "errA")]
    clusters = analyze_failures(snaps)
    assert clusters
    c = clusters[0]
    assert c.suggested_block_title
    assert c.suggested_rubric_check
    assert c.suggested_eval_case


def test_analyzer_loads_from_runs_dir(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "r1.json").write_text(json.dumps(_snap("r1", "x", "sig")), encoding="utf-8")
    fa = FailureAnalyzer(runs)
    clusters = fa.analyze()
    assert clusters and clusters[0].fingerprint == "sig"


def test_done_status_without_error_is_not_clustered() -> None:
    snap = {
        "session_id": "r1",
        "environment_id": "env_debugging_loop",
        "status": "done",
        "events": [],
    }
    clusters = analyze_failures([snap])
    assert clusters == []


def test_errors_seen_can_form_fingerprint_without_event_error_signature() -> None:
    snap = {
        "session_id": "r1",
        "environment_id": "env_debugging_loop",
        "status": "done",
        "events": [],
        "errors_seen": ["Command failed: pytest -q exited with code 1"],
    }
    clusters = analyze_failures([snap])
    assert len(clusters) == 1
    assert "pytest -q" in clusters[0].fingerprint


def test_nonzero_command_exit_produces_fingerprint_without_stderr() -> None:
    snap = {
        "session_id": "r1",
        "environment_id": "env_debugging_loop",
        "status": "done",
        "events": [],
        "commands_run": [{"command": "pytest -q", "exit_code": 1, "stderr": "", "stdout": ""}],
    }
    clusters = analyze_failures([snap])
    assert len(clusters) == 1
    assert clusters[0].fingerprint == "command_exit:pytest:exit_1"


def test_nonzero_command_exit_ignores_leading_env_assignments() -> None:
    snap = {
        "session_id": "r1",
        "environment_id": "env_debugging_loop",
        "status": "done",
        "events": [],
        "commands_run": [{"command": "LOCAL=1 npm run build", "exit_code": 2, "stderr": "", "stdout": ""}],
    }
    clusters = analyze_failures([snap])
    assert clusters == []


def test_low_value_command_exit_is_ignored() -> None:
    snap = {
        "session_id": "r1",
        "environment_id": "env_debugging_loop",
        "status": "done",
        "events": [],
        "commands_run": [{"command": "npm run build", "exit_code": 2, "stderr": "", "stdout": ""}],
    }
    clusters = analyze_failures([snap])
    assert clusters == []


def test_tool_failure_result_summary_forms_fingerprint() -> None:
    snap = {
        "session_id": "r1",
        "environment_id": "env_debugging_loop",
        "status": "done",
        "events": [],
        "tools_called": [{"name": "search", "result_summary": "error: request timed out"}],
    }
    clusters = analyze_failures([snap])
    assert len(clusters) == 1
    assert clusters[0].fingerprint.startswith("tool_failure:search:")


def test_validation_failure_forms_fingerprint() -> None:
    snap = {
        "session_id": "r1",
        "environment_id": "env_debugging_loop",
        "status": "done",
        "events": [],
        "validation_results": [{"name": "pytest", "passed": False, "detail": "2 tests failed"}],
    }
    clusters = analyze_failures([snap])
    assert len(clusters) == 1
    assert clusters[0].fingerprint.startswith("validation_failed:pytest:")
