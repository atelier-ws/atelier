from __future__ import annotations

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
