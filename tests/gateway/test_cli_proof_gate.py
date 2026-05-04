"""Tests for atelier_proof_report MCP tool and CLI proof commands (WP-32)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from atelier.gateway.adapters.cli import cli
from atelier.gateway.adapters.mcp_server import TOOLS, _handle

# --------------------------------------------------------------------------- #
# MCP helpers (same pattern as test_mcp_route_contract.py)                    #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Tool registration                                                           #
# --------------------------------------------------------------------------- #


def test_mcp_proof_report_tool_registered() -> None:
    assert "atelier_proof_report" in TOOLS


# --------------------------------------------------------------------------- #
# MCP: run a new proof report                                                 #
# --------------------------------------------------------------------------- #


def test_mcp_proof_report_returns_status_field(mcp_env: Path) -> None:
    resp = _call("atelier_proof_report", {"run_id": "test-mcp-run"})
    result = _result(resp)
    assert "status" in result
    assert result["status"] in ("pass", "fail")


def test_mcp_proof_report_run_id_echoed(mcp_env: Path) -> None:
    resp = _call("atelier_proof_report", {"run_id": "my-run-id"})
    result = _result(resp)
    assert result["run_id"] == "my-run-id"


def test_mcp_proof_report_has_context_reduction_pct(mcp_env: Path) -> None:
    resp = _call("atelier_proof_report", {"run_id": "ctx-run"})
    result = _result(resp)
    assert "context_reduction_pct" in result
    assert isinstance(result["context_reduction_pct"], float)


def test_mcp_proof_report_has_host_enforcement_matrix(mcp_env: Path) -> None:
    resp = _call("atelier_proof_report", {"run_id": "matrix-run"})
    result = _result(resp)
    assert "host_enforcement_matrix" in result
    hosts = {h["host"] for h in result["host_enforcement_matrix"]}
    assert hosts == {"claude", "codex", "copilot", "opencode", "gemini"}


def test_mcp_proof_report_provider_enforced_disabled(mcp_env: Path) -> None:
    resp = _call("atelier_proof_report", {"run_id": "pe-run"})
    result = _result(resp)
    for h in result["host_enforcement_matrix"]:
        assert h["provider_enforced_disabled"] is True


def test_mcp_proof_report_has_feature_boundary_labels(mcp_env: Path) -> None:
    resp = _call("atelier_proof_report", {"run_id": "labels-run"})
    result = _result(resp)
    assert "feature_boundary_labels" in result
    labels = result["feature_boundary_labels"]
    assert labels.get("routing_decision") == "Atelier augmentation"
    assert labels.get("model_selection") == "Host-native"
    assert labels.get("provider_model_override") == "Future-only"


def test_mcp_proof_report_uses_custom_context_reduction(mcp_env: Path) -> None:
    resp = _call(
        "atelier_proof_report",
        {"run_id": "custom-ctx", "context_reduction_pct": 75.0},
    )
    result = _result(resp)
    assert result["context_reduction_pct"] == pytest.approx(75.0, abs=0.01)


def test_mcp_proof_report_no_run_id_returns_error_when_no_report(mcp_env: Path) -> None:
    resp = _call("atelier_proof_report", {})
    result = _result(resp)
    assert "error" in result


def test_mcp_proof_report_load_after_save(mcp_env: Path) -> None:
    # First run and save
    _call("atelier_proof_report", {"run_id": "load-test"})
    # Then load without run_id
    resp = _call("atelier_proof_report", {})
    result = _result(resp)
    assert result["run_id"] == "load-test"


def test_mcp_proof_report_benchmark_cases_have_trace_id(mcp_env: Path) -> None:
    resp = _call("atelier_proof_report", {"run_id": "trace-run"})
    result = _result(resp)
    for case in result["benchmark_cases"]:
        assert case["trace_id"] is not None, f"case {case['case_id']} missing trace_id"


# --------------------------------------------------------------------------- #
# CLI: proof run                                                              #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    return root


def test_cli_proof_run_json_output(cli_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(cli_env),
            "proof",
            "run",
            "--run-id",
            "cli-test-run",
            "--context-reduction-pct",
            "55.0",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["run_id"] == "cli-test-run"
    assert data["status"] in ("pass", "fail")


def test_cli_proof_run_text_output(cli_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(cli_env),
            "proof",
            "run",
            "--run-id",
            "cli-text-run",
            "--context-reduction-pct",
            "55.0",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "run_id=cli-text-run" in result.output
    assert "status=" in result.output


def test_cli_proof_run_writes_report_json(cli_env: Path) -> None:
    runner = CliRunner()
    runner.invoke(
        cli,
        [
            "--root",
            str(cli_env),
            "proof",
            "run",
            "--run-id",
            "save-run",
            "--context-reduction-pct",
            "55.0",
        ],
    )
    json_path = cli_env / "proof" / "proof-report.json"
    assert json_path.exists()
    assert json_path.stat().st_size > 0


# --------------------------------------------------------------------------- #
# CLI: proof report                                                           #
# --------------------------------------------------------------------------- #


def test_cli_proof_report_json_shows_last_run(cli_env: Path) -> None:
    runner = CliRunner()
    # First, run the proof gate to create a report
    runner.invoke(
        cli,
        [
            "--root",
            str(cli_env),
            "proof",
            "run",
            "--run-id",
            "report-run",
            "--context-reduction-pct",
            "55.0",
        ],
    )
    # Then retrieve it
    result = runner.invoke(
        cli,
        ["--root", str(cli_env), "proof", "report", "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["run_id"] == "report-run"


def test_cli_proof_report_error_when_no_report(cli_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--root", str(cli_env), "proof", "report"],
    )
    assert result.exit_code != 0
    assert "No proof report found" in result.output


def test_cli_proof_run_fails_low_context_reduction(cli_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(cli_env),
            "proof",
            "run",
            "--run-id",
            "low-ctx",
            "--context-reduction-pct",
            "30.0",  # below 50% threshold
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "fail"
    assert "context_reduction_pct" in data["failed_thresholds"]


def test_cli_proof_run_passes_with_sufficient_context_reduction(cli_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--root",
            str(cli_env),
            "proof",
            "run",
            "--run-id",
            "high-ctx",
            "--context-reduction-pct",
            "60.0",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "context_reduction_pct" not in data.get("failed_thresholds", [])
