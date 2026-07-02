from __future__ import annotations

from pathlib import Path

import pytest

from atelier.core.capabilities import vanilla_baseline

try:
    from atelier.gateway.cli.commands.savings import _echo_vs_vanilla_block

    _HAS_VANILLA_BLOCK = True
except ImportError:
    _HAS_VANILLA_BLOCK = False

_FAKE = {
    "calls_saved": 5,
    "cost_saved_usd": 0.5,
    "time_saved_ms": 35000,
    "by_detector": {"grep->read": 3, "edit-batch": 2},
    "window_days": 30,
    "sessions": 2,
    "capped": False,
}

_REASON = (
    "Function _echo_vs_vanilla_block was removed from savings.py in commit 5d28e3ab "
    "(refactor: subprocess delegation and analytics removal). "
    "Re-enable when a replacement vs-vanilla rendering path exists."
)


@pytest.mark.xfail(not _HAS_VANILLA_BLOCK, reason=_REASON, strict=False)
def test_deep_shows_per_pattern_breakdown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(vanilla_baseline, "aggregate_vanilla_baseline", lambda root: dict(_FAKE))
    _echo_vs_vanilla_block(tmp_path, deep=True)
    out = capsys.readouterr().out
    assert "by pattern" in out
    assert "grep->read: 3" in out
    assert "edit-batch: 2" in out
    assert "2 sessions" in out
    # Ordered by hits descending.
    assert out.index("grep->read") < out.index("edit-batch")


@pytest.mark.xfail(not _HAS_VANILLA_BLOCK, reason=_REASON, strict=False)
def test_non_deep_omits_breakdown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(vanilla_baseline, "aggregate_vanilla_baseline", lambda root: dict(_FAKE))
    _echo_vs_vanilla_block(tmp_path, deep=False)
    out = capsys.readouterr().out
    assert "vs vanilla Claude Code" in out
    assert "by pattern" not in out


@pytest.mark.xfail(not _HAS_VANILLA_BLOCK, reason=_REASON, strict=False)
def test_zero_calls_is_silent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(vanilla_baseline, "aggregate_vanilla_baseline", lambda root: {"calls_saved": 0})
    _echo_vs_vanilla_block(tmp_path, deep=True)
    assert capsys.readouterr().out == ""
