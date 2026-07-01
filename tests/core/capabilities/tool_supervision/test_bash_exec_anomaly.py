from __future__ import annotations

import re
from pathlib import Path

import pytest

from atelier.core.capabilities.tool_supervision.bash_exec import _compact_result, _extract_anomaly_windows


def test_extract_anomaly_windows_returns_none_when_nothing_matches() -> None:
    text = "\n".join(f"line {i}: all good" for i in range(50))
    assert _extract_anomaly_windows(text, max_chars=6000) is None


def test_extract_anomaly_windows_keeps_a_marker_buried_in_the_middle() -> None:
    lines = [f"line {i}: doing routine work" for i in range(300)]
    lines[150] = "FATAL: connection to db refused at line 150"
    text = "\n".join(lines)
    result = _extract_anomaly_windows(text, max_chars=6000)
    assert result is not None
    assert "FATAL: connection to db refused" in result
    # Only a window around the hit is kept, not the whole 300-line log.
    assert len(result) < len(text)


def test_compact_result_generic_command_surfaces_a_buried_fatal_line() -> None:
    lines = [f"line {i}: doing routine work" for i in range(300)]
    lines[150] = "FATAL: connection to db refused at line 150"
    stdout = "\n".join(lines) + "\ndone"
    result = _compact_result(
        command="python3 migrate.py",
        raw_stdout=stdout,
        raw_stderr="",
        exit_code=0,
        duration_ms=10,
        max_lines=200,
    )
    assert "FATAL: connection to db refused" in result.stdout


def test_compact_result_generic_command_unaffected_when_clean() -> None:
    """No anomaly marker anywhere -> falls back to the existing head+tail path
    unchanged; a clean run's output shape doesn't change."""
    lines = [f"line {i}: all good" for i in range(300)]
    stdout = "\n".join(lines)
    result = _compact_result(
        command="python3 build.py",
        raw_stdout=stdout,
        raw_stderr="",
        exit_code=0,
        duration_ms=10,
        max_lines=200,
    )
    assert "lines omitted" in result.stdout
    assert "line 0:" in result.stdout
    assert "line 299:" in result.stdout


def test_compact_result_spills_full_output_when_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bare "(N lines omitted)" marker used to discard the middle for good.
    With T7 spill enabled (default), the untouched raw stdout is persisted and a
    recovery hint names the path, so the dropped lines stay reachable via `read`.
    """
    monkeypatch.setenv("ATELIER_MCP_SPILL_DIR", str(tmp_path / "spill"))
    monkeypatch.delenv("ATELIER_TOOL_OUTPUT_SPILL", raising=False)  # default on
    lines = [f"line {i}: all good" for i in range(300)]
    stdout = "\n".join(lines)
    result = _compact_result(
        command="python3 build.py",
        raw_stdout=stdout,
        raw_stderr="",
        exit_code=0,
        duration_ms=10,
        max_lines=200,
    )
    assert result.lines_omitted > 0
    assert "line 100: all good" not in result.stdout  # dropped from the summary
    assert "spilled to" in result.spill_hint
    match = re.search(r"spilled to (\S+\.txt);", result.spill_hint)
    assert match is not None
    recovered = Path(match.group(1)).read_text(encoding="utf-8")
    assert "line 100: all good" in recovered  # recoverable from the full spill


def test_compact_result_no_spill_hint_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "0")
    lines = [f"line {i}: all good" for i in range(300)]
    result = _compact_result(
        command="python3 build.py",
        raw_stdout="\n".join(lines),
        raw_stderr="",
        exit_code=0,
        duration_ms=10,
        max_lines=200,
    )
    assert result.lines_omitted > 0
    assert result.spill_hint == ""


def test_compact_result_no_spill_hint_when_nothing_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_TOOL_OUTPUT_SPILL", raising=False)
    result = _compact_result(
        command="echo hi",
        raw_stdout="hi\n",
        raw_stderr="",
        exit_code=0,
        duration_ms=1,
        max_lines=200,
    )
    assert result.lines_omitted == 0
    assert result.spill_hint == ""
