"""Integration tests for the WS1 edit-loop verify gate wired into tool_smart_edit."""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier.gateway.adapters import mcp_server

_CLEAN_TS = "export const x = 1;\n"
_BROKEN_TS = "export const x = ;;;{\n"


def test_verify_gate_rolls_back_syntax_break(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "mod.ts"
    target.write_text(_CLEAN_TS, encoding="utf-8")

    result = mcp_server.tool_smart_edit(
        {
            "edits": [
                {"file_path": "mod.ts", "old_string": "export const x = 1;", "new_string": "export const x = ;;;{"}
            ],
            "verify": True,
            "verify_rollback": True,
        }
    )

    assert result.get("rolled_back") is True
    gate = result.get("mechanical_checks", {})
    assert gate.get("passed") is False
    assert gate.get("scope") == "mechanical"
    assert gate.get("behavioral_tests_run") is False
    assert "verify" not in result
    counterexamples = result.get("counterexamples") or []
    assert any(c.get("check") == "parse" for c in counterexamples)
    # File restored to its pre-edit content.
    assert target.read_text(encoding="utf-8") == _CLEAN_TS


def test_verify_gate_passes_clean_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "mod.ts"
    target.write_text(_CLEAN_TS, encoding="utf-8")

    result = mcp_server.tool_smart_edit(
        {
            "edits": [
                {"file_path": "mod.ts", "old_string": "export const x = 1;", "new_string": "export const x = 2;"}
            ],
            "verify": True,
            "verify_rollback": True,
        }
    )

    assert not result.get("rolled_back")
    gate = result.get("mechanical_checks", {})
    assert gate == {
        "passed": True,
        "checks": ["typecheck"],
        "scope": "mechanical",
        "behavioral_tests_run": False,
    }
    assert "verify" not in result
    assert "export const x = 2;" in target.read_text(encoding="utf-8")


def test_default_path_has_no_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # verify defaults to False and ATELIER_EDIT_VERIFY is unset: behaviour unchanged.
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("ATELIER_EDIT_VERIFY", raising=False)
    target = tmp_path / "mod.ts"
    target.write_text(_CLEAN_TS, encoding="utf-8")

    result = mcp_server.tool_smart_edit(
        {"edits": [{"file_path": "mod.ts", "old_string": "export const x = 1;", "new_string": "export const x = ;;;{"}]}
    )

    assert "verify" not in result
    assert "mechanical_checks" not in result
    assert not result.get("rolled_back")
    # No gate -> the (broken) edit is written through.
    assert target.read_text(encoding="utf-8") == _BROKEN_TS
