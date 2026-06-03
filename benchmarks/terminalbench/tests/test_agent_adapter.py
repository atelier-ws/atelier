"""Unit tests for terminalbench.agent_adapter — stream-json parsing and AtelierClaudeAgent.

All tests are in-process only: no Docker, no live claude subprocess, no network.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BENCHMARKS_ROOT = ROOT / "benchmarks"
if str(BENCHMARKS_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_ROOT))

pytest.importorskip("terminal_bench")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TB04_FIELDS = {
    "task_id",
    "mode",
    "rep",
    "model",
    "provider",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "latency_ms",
    "latency_api_ms",
    "num_turns",
    "cost_usd",
    "grader_verdict",
    "grader_is_resolved",
    "grader_failure_mode",
    "trial_started_at",
    "trial_ended_at",
    "is_error",
    "stop_reason",
    "claude_error",
    "stream_log_path",
    "atelier_bench_mode",
    "atelier_root",
    "dataset_name",
    "dataset_version",
}

# Live-captured result line from RESEARCH.md
_RESULT_LINE = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "duration_ms": 3557,
    "duration_api_ms": 2104,
    "num_turns": 1,
    "result": "Two",
    "stop_reason": "end_turn",
    "total_cost_usd": 0.15264875,
    "usage": {
        "input_tokens": 6,
        "cache_creation_input_tokens": 24395,
        "cache_read_input_tokens": 0,
        "output_tokens": 6,
    },
}

_SYSTEM_LINE = {"type": "system", "subtype": "init", "session_id": "abc123"}
_ASSISTANT_LINE = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Two"}]}}


def _write_jsonl(tmp_path: Path, lines: list) -> Path:
    """Write lines as NDJSON to a temp file; each item can be dict or raw string."""
    p = tmp_path / "stream.jsonl"
    parts: list[str] = []
    for line in lines:
        if isinstance(line, dict):
            parts.append(json.dumps(line))
        else:
            parts.append(str(line))
    p.write_text("\n".join(parts), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# parse_stream_jsonl tests
# ---------------------------------------------------------------------------


def test_parse_result_line_happy_path(tmp_path: Path) -> None:
    """parse_stream_jsonl correctly extracts all fields from a well-formed result line."""
    from terminalbench.agent_adapter import parse_stream_jsonl

    log = _write_jsonl(tmp_path, [_SYSTEM_LINE, _ASSISTANT_LINE, _RESULT_LINE])
    result = parse_stream_jsonl(log)

    assert result["input_tokens"] == 6
    assert result["output_tokens"] == 6
    assert result["cache_creation_input_tokens"] == 24395
    assert result["cache_read_input_tokens"] == 0
    assert result["cost_usd"] == pytest.approx(0.15264875)
    assert result["latency_ms"] == 3557
    assert result["latency_api_ms"] == 2104
    assert result["num_turns"] == 1
    assert result["is_error"] is False
    assert result["stop_reason"] == "end_turn"


def test_parse_no_result_line(tmp_path: Path) -> None:
    """parse_stream_jsonl returns {'error': 'no_result_line'} when no result line present."""
    from terminalbench.agent_adapter import parse_stream_jsonl

    log = _write_jsonl(tmp_path, [_SYSTEM_LINE, _ASSISTANT_LINE])
    result = parse_stream_jsonl(log)

    assert result.get("error") == "no_result_line"
    # No KeyError — all zero-valued keys present
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0


def test_parse_malformed_lines(tmp_path: Path) -> None:
    """parse_stream_jsonl silently skips malformed lines and still extracts result."""
    from terminalbench.agent_adapter import parse_stream_jsonl

    log = _write_jsonl(tmp_path, ["not json at all", _RESULT_LINE, "also not json!!!"])
    result = parse_stream_jsonl(log)

    assert "error" not in result
    assert result["input_tokens"] == 6
    assert result["num_turns"] == 1


def test_parse_empty_file(tmp_path: Path) -> None:
    """parse_stream_jsonl returns {'error': 'no_result_line'} for an empty file."""
    from terminalbench.agent_adapter import parse_stream_jsonl

    log = tmp_path / "stream.jsonl"
    log.write_text("", encoding="utf-8")
    result = parse_stream_jsonl(log)

    assert result.get("error") == "no_result_line"


# ---------------------------------------------------------------------------
# AtelierClaudeAgent._env tests
# ---------------------------------------------------------------------------


def test_agent_env_on_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AtelierClaudeAgent(bench_mode='on')._env has ATELIER_BENCH_MODE='on'."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    assert agent._env["ATELIER_BENCH_MODE"] == "on"


def test_agent_env_off_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AtelierClaudeAgent(bench_mode='off')._env has ATELIER_BENCH_MODE='off'."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="off")
    assert agent._env["ATELIER_BENCH_MODE"] == "off"


def test_agent_env_excludes_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """ATELIER_DEV_MODE is never forwarded into the container env (PITFALLS.md #3b)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    monkeypatch.setenv("ATELIER_DEV_MODE", "1")
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    assert "ATELIER_DEV_MODE" not in agent._env


def test_agent_env_includes_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """AtelierClaudeAgent._env propagates ANTHROPIC_API_KEY from os.environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-sentinel-value")
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    assert agent._env["ANTHROPIC_API_KEY"] == "sk-test-sentinel-value"


def test_agent_env_has_background_task_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """AtelierClaudeAgent._env includes FORCE_AUTO_BACKGROUND_TASKS and ENABLE_BACKGROUND_TASKS."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    assert agent._env["FORCE_AUTO_BACKGROUND_TASKS"] == "1"
    assert agent._env["ENABLE_BACKGROUND_TASKS"] == "1"


# ---------------------------------------------------------------------------
# AtelierClaudeAgent._run_agent_commands tests
# ---------------------------------------------------------------------------


def test_run_agent_commands_tees_to_container_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """_run_agent_commands produces a command that tees to CONTAINER_STREAM_LOG."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    from terminalbench.agent_adapter import CONTAINER_STREAM_LOG, AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    commands = agent._run_agent_commands("echo hello")

    assert len(commands) == 1
    assert f"tee {CONTAINER_STREAM_LOG}" in commands[0].command


def test_run_agent_commands_uses_stream_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """_run_agent_commands includes --output-format stream-json flag."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    commands = agent._run_agent_commands("echo hello")

    assert "--output-format stream-json" in commands[0].command


def test_agent_run_commands_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """_run_agent_commands includes --verbose, --dangerously-skip-permissions, --allowedTools."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    from terminalbench.agent_adapter import AtelierClaudeAgent

    agent = AtelierClaudeAgent(bench_mode="on")
    cmd = agent._run_agent_commands("do task")[0].command

    assert "--verbose" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert "--allowedTools" in cmd


def test_agent_run_commands_shlex_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Instructions with spaces and quotes are safely embedded via shlex.quote."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    from terminalbench.agent_adapter import AtelierClaudeAgent

    instruction = 'task with spaces and "quotes"'
    agent = AtelierClaudeAgent(bench_mode="on")
    cmd = agent._run_agent_commands(instruction)[0].command

    # The shlex-quoted version must be present in the command string
    quoted = shlex.quote(instruction)
    assert quoted in cmd, f"Expected shlex-quoted instruction {quoted!r} in command"
    # Verify the quote actually wraps the instruction (i.e., single-quote wrapping applied)
    assert quoted != instruction, "shlex.quote must modify the instruction (add quotes/escaping)"


def test_owned_solver_agent_runs_benchmark_solver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-tests")
    from terminalbench.agent_adapter import AtelierOwnedSolverAgent

    agent = AtelierOwnedSolverAgent(bench_mode="on", model="claude-opus-4.8")
    command = agent._run_agent_commands("solve the task")[0].command

    assert "atelier benchmark solver" in command
    assert "--format stream-json" in command
    assert "--out /logs/owned" in command


# ---------------------------------------------------------------------------
# AdapterResult schema test
# ---------------------------------------------------------------------------


def test_adapter_result_to_dict_has_all_tb04_fields() -> None:
    """AdapterResult.to_dict() exposes all 25 TB-04 required fields."""
    from terminalbench.agent_adapter import AdapterResult

    result = AdapterResult(
        task_id="hello-world",
        mode="on",
        rep=1,
        model="claude-sonnet-4-5",
        provider="claude",
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        latency_ms=1234.5,
        latency_api_ms=987.6,
        num_turns=2,
        cost_usd=0.042,
        grader_verdict="pass",
        grader_is_resolved=True,
        grader_failure_mode=None,
        trial_started_at="2026-01-01T00:00:00Z",
        trial_ended_at="2026-01-01T00:01:00Z",
        is_error=False,
        stop_reason="end_turn",
        claude_error=None,
        stream_log_path="/agent-logs/stream.jsonl",
        atelier_bench_mode="on",
        atelier_root="/tmp/atelier_bench_on_abc",
        dataset_name="terminal-bench-core",
        dataset_version="0.1.1",
    )

    d = result.to_dict()
    missing = TB04_FIELDS - set(d.keys())
    assert not missing, f"AdapterResult.to_dict() is missing TB-04 fields: {missing}"
    assert len(TB04_FIELDS) == 25, "Sanity check: TB04_FIELDS must have exactly 25 entries"
