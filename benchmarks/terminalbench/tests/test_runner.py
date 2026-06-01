"""Unit tests for terminalbench.runner — RunRecord, write_records, write_transcript.

All tests are in-process only: no Docker, no live claude subprocess, no network.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

pytest.importorskip("terminalbench.agent_adapter")
pytest.importorskip("terminalbench.runner")

from terminalbench.agent_adapter import AdapterResult
from terminalbench.runner import RunRecord, write_records, write_transcript

# ---------------------------------------------------------------------------
# TB-04 field set (shared with test_agent_adapter.py)
# ---------------------------------------------------------------------------

TB04_FIELDS = {
    "task_id",
    "mode",
    "rep",
    "model",
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter_result(
    task_id: str = "hello-world",
    mode: str = "on",
    rep: int = 1,
) -> AdapterResult:
    """Return a minimal but fully-populated AdapterResult for tests."""
    return AdapterResult(
        task_id=task_id,
        mode=mode,
        rep=rep,
        model="claude-sonnet-4-5",
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=10,
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
        atelier_bench_mode=mode,
        atelier_root="/tmp/atelier_bench_on_abc",
        dataset_name="terminal-bench-core",
        dataset_version="0.1.1",
    )


def _make_run_record(**overrides: object) -> RunRecord:
    """Return a RunRecord derived from _make_adapter_result with optional overrides."""
    result = _make_adapter_result()
    record = RunRecord(
        task_id=result.task_id,
        mode=result.mode,
        rep=result.rep,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_creation_input_tokens=result.cache_creation_input_tokens,
        cache_read_input_tokens=result.cache_read_input_tokens,
        latency_ms=result.latency_ms,
        latency_api_ms=result.latency_api_ms,
        num_turns=result.num_turns,
        cost_usd=result.cost_usd,
        grader_verdict=result.grader_verdict,
        grader_is_resolved=result.grader_is_resolved,
        grader_failure_mode=result.grader_failure_mode,
        trial_started_at=result.trial_started_at,
        trial_ended_at=result.trial_ended_at,
        is_error=result.is_error,
        stop_reason=result.stop_reason,
        claude_error=result.claude_error,
        stream_log_path=result.stream_log_path,
        atelier_bench_mode=result.atelier_bench_mode,
        atelier_root=result.atelier_root,
        dataset_name=result.dataset_name,
        dataset_version=result.dataset_version,
        transcript_path=None,
    )
    if overrides:
        record = dataclasses.replace(record, **overrides)
    return record


# ---------------------------------------------------------------------------
# RunRecord tests
# ---------------------------------------------------------------------------


def test_run_record_to_jsonl_roundtrip() -> None:
    """RunRecord.to_jsonl() round-trips through json.loads with all fields preserved."""
    record = _make_run_record()
    jsonl = record.to_jsonl()
    parsed = json.loads(jsonl)

    assert parsed["task_id"] == record.task_id
    assert parsed["mode"] == record.mode
    assert parsed["transcript_path"] is None
    assert parsed["input_tokens"] == 100
    assert parsed["cost_usd"] == pytest.approx(0.042)


def test_write_records_creates_file(tmp_path: Path) -> None:
    """write_records creates a JSONL file at the specified path."""
    dest = tmp_path / "runs.jsonl"
    write_records([_make_run_record()], dest)

    assert dest.exists()
    parsed = json.loads(dest.read_text().strip())
    assert parsed["task_id"] == "hello-world"


def test_write_records_multiple_rows(tmp_path: Path) -> None:
    """write_records with 3 records produces exactly 3 non-empty JSONL lines."""
    records = [
        _make_run_record(task_id="hello-world"),
        _make_run_record(task_id="fix-git"),
        _make_run_record(task_id="csv-to-parquet"),
    ]
    dest = tmp_path / "runs.jsonl"
    write_records(records, dest)

    lines = [ln for ln in dest.read_text().splitlines() if ln.strip()]
    assert len(lines) == 3
    task_ids = {json.loads(ln)["task_id"] for ln in lines}
    assert task_ids == {"hello-world", "fix-git", "csv-to-parquet"}


def test_write_records_appends_to_existing_jsonl(tmp_path: Path) -> None:
    dest = tmp_path / "runs.jsonl"
    write_records([_make_run_record(task_id="hello-world")], dest)
    write_records([_make_run_record(task_id="fix-git")], dest)

    lines = [ln for ln in dest.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert [json.loads(line)["task_id"] for line in lines] == ["hello-world", "fix-git"]


# ---------------------------------------------------------------------------
# write_transcript tests
# ---------------------------------------------------------------------------


def test_write_transcript_naming(tmp_path: Path) -> None:
    """write_transcript creates file named <task_id>__<mode>__rep<N>.json."""
    result = _make_adapter_result(task_id="fix-git", mode="off", rep=3)
    path = write_transcript(result, tmp_path)

    assert path.name == "fix-git__off__rep3.json"


def test_write_transcript_content_valid_json(tmp_path: Path) -> None:
    """Transcript file content is valid JSON with all 25 TB-04 fields present."""
    result = _make_adapter_result(task_id="fix-git", mode="on", rep=1)
    path = write_transcript(result, tmp_path)

    content = path.read_text(encoding="utf-8")
    parsed = json.loads(content)

    missing = TB04_FIELDS - set(parsed.keys())
    assert not missing, f"Transcript JSON missing TB-04 fields: {missing}"
    assert len(TB04_FIELDS) == 25, "Sanity: TB04_FIELDS must have exactly 25 entries"


def test_write_transcript_atomic(tmp_path: Path) -> None:
    """write_transcript leaves no .tmp file after successful write."""
    result = _make_adapter_result(task_id="fix-git", mode="on", rep=1)
    write_transcript(result, tmp_path)

    tmp_file = tmp_path / "fix-git__on__rep1.json.tmp"
    assert not tmp_file.exists(), ".tmp file must be removed after atomic write"
    assert (tmp_path / "fix-git__on__rep1.json").exists()


def test_write_transcript_creates_parent_dirs(tmp_path: Path) -> None:
    """write_transcript creates the output directory tree if it doesn't exist."""
    out = tmp_path / "a" / "b" / "c"
    assert not out.exists()

    result = _make_adapter_result(task_id="hello-world", mode="on", rep=1)
    write_transcript(result, out)

    assert out.exists()
    assert (out / "hello-world__on__rep1.json").exists()
