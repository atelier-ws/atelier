"""Tests for the ContextCompressor and the preserved-fields invariants."""

from __future__ import annotations

from atelier.infra.runtime.context_compressor import ContextCompressor
from atelier.infra.runtime.run_ledger import RunLedger


def test_compressor_preserves_latest_error_and_alerts() -> None:
    led = RunLedger(task="t")
    led.record_command("pytest", ok=False, error_signature="errA")
    led.record_command("pytest", ok=False, error_signature="errA")  # repeated
    led.record_command("ruff", ok=False, error_signature="errB")
    led.record_alert("repeated_command_failure", "high", "pytest x2")
    led.record_alert("noise", "low", "ignore me")

    state = ContextCompressor().compress(led)
    # Distinct error fingerprints captured (deduped)
    assert "errA" in state.error_fingerprints
    assert "errB" in state.error_fingerprints
    # Low severity alert dropped
    assert all("noise" not in m for m in state.high_severity_alerts)
    # High severity alert preserved
    assert any("repeated_command_failure" in m for m in state.high_severity_alerts)
    # Blocker reflects latest alert
    assert state.current_blocker is not None


def test_compressor_tracks_files_with_last_action() -> None:
    led = RunLedger(task="t")
    led.record_file_event("a.py", "edit")
    led.record_file_event("a.py", "revert")
    led.record_file_event("b.py", "edit")
    state = ContextCompressor().compress(led)
    assert state.files_changed["a.py"] == "revert"
    assert state.files_changed["b.py"] == "edit"


def test_compressor_prompt_block_renders() -> None:
    led = RunLedger(task="t")
    led.record_command("pytest", ok=False, error_signature="x")
    state = ContextCompressor().compress(led)
    text = state.to_prompt_block()
    assert "Atelier compact state" in text
