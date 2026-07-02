"""Smoke-test for the rotating savings_segment function."""

import json
import time
from pathlib import Path

import pytest


@pytest.fixture()
def atelier_root(tmp_path: Path) -> Path:
    root = tmp_path / ".atelier"
    root.mkdir()
    (root / "runs").mkdir()
    (root / "reviews").mkdir()
    # Suppress the "login" status tip so status_text is empty in tests.
    (root / "auth.json").write_text(json.dumps({"authenticated": True}))
    # Suppress status tips so no extra frame is injected.
    (root / "plugin_settings.json").write_text(json.dumps({"atelier": {"statusLineTips": False}}))
    return root


def _set_frame(root: Path, counter: int) -> None:
    # Fresh ts so _get_frame_index does NOT auto-advance during the test.
    state = root / "statusline_frame_state.json"
    state.write_text(json.dumps({"counter": counter, "ts": time.time()}))


def _segment(root: Path, counter: int, **kw: object) -> str:
    from atelier.core.capabilities.savings_summary import savings_segment

    _set_frame(root, counter)
    return savings_segment("", atelier_root=root, no_color=True, **kw)  # type: ignore[arg-type]


def test_frame0_shows_cost_savings_carry_combined(atelier_root: Path) -> None:
    # Frame 0: combined — cost always present, savings/carry when nonzero.
    seg = _segment(atelier_root, 0, live_cost_usd=1.234, live_in_tok=10_000, live_cache_tok=50_000, live_out_tok=2_000)
    assert "1.234" in seg
    # Cost-led icon frame: leads with " $" (no text separator prepended).
    assert seg.startswith(" $"), f"expected cost-led output, got: {seg!r}"
    assert "(I:10k C:50k O:2k)" in seg
    assert "↓" in seg  # savings segment present when there is usage


def test_frame1_shows_token_breakdown(atelier_root: Path) -> None:
    # Frame 1: token breakdown detail.
    seg = _segment(atelier_root, 1, live_cost_usd=1.234, live_in_tok=10_000, live_cache_tok=50_000, live_out_tok=2_000)
    assert "I:10k" in seg
    assert "C:50k" in seg
    assert "O:2k" in seg


def test_frame_wraps_when_few_frames(atelier_root: Path) -> None:
    """With only live cost (no savings/carry/historical), frame 0 (cost + I/C/O)
    is the sole frame and is shown for every counter."""
    for i in range(4):
        seg = _segment(atelier_root, i, live_cost_usd=0.5)
        assert "0.500" in seg, f"counter={i}: {seg!r}"
        assert seg.startswith(" $"), f"counter={i}: {seg!r}"


def test_historical_savings_empty(atelier_root: Path) -> None:
    from atelier.core.capabilities.savings_summary import _read_historical_savings

    usd, tok, _calls, _turns, _spend, _carry = _read_historical_savings(7, atelier_root)
    assert usd == 0.0
    assert tok == 0


def test_historical_savings_reads_recent_rows(atelier_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from atelier.core.capabilities.savings_summary import _read_historical_savings

    sidecar = atelier_root / "sessions" / "abc123"
    sidecar.mkdir(parents=True)
    ledger = sidecar / "savings.jsonl"
    now_iso = "2026-06-15T10:00:00"
    old_iso = "2020-01-01T00:00:00"  # definitely outside any window
    rows = [
        json.dumps({"ts": now_iso, "tokens": 1000, "cost_saved_usd": 0.5}),
        json.dumps({"ts": old_iso, "tokens": 9999, "cost_saved_usd": 99.0}),
    ]
    ledger.write_text("\n".join(rows))

    # Patch time.time so "now" is close to now_iso (2026-06-15)
    import time as time_mod

    target_ts = 1781524800.0  # approx 2026-06-15T10:00:00 UTC
    monkeypatch.setattr(time_mod, "time", lambda: target_ts)

    usd7, tok7, _calls7, _turns7, _spend7, _carry7 = _read_historical_savings(7, atelier_root)
    assert tok7 == 1000
    assert abs(usd7 - 0.5) < 1e-6


def test_review_verdict_none(atelier_root: Path) -> None:
    from atelier.core.capabilities.savings_summary import _read_review_verdict

    assert _read_review_verdict("nosuchsession", atelier_root) == ""


def test_review_verdict_needs_fix(atelier_root: Path) -> None:
    from atelier.core.capabilities.savings_summary import _read_review_verdict

    sid = "test-session-001"
    log = atelier_root / "reviews" / f"{sid}.jsonl"
    log.write_text(json.dumps({"verdict": "NEEDS_FIX", "consumed": False}) + "\n")
    assert _read_review_verdict(sid, atelier_root) == "NEEDS_FIX"


def test_review_verdict_consumed_ignored(atelier_root: Path) -> None:
    from atelier.core.capabilities.savings_summary import _read_review_verdict

    sid = "test-session-002"
    log = atelier_root / "reviews" / f"{sid}.jsonl"
    log.write_text(json.dumps({"verdict": "NEEDS_FIX", "consumed": True}) + "\n")
    assert _read_review_verdict(sid, atelier_root) == ""


def test_savings_frames_weighted_and_segment_consistent(atelier_root: Path) -> None:
    """savings_frames returns the full weighted list (frame 0 x3) and
    savings_segment always returns one of its entries — the MCP sidecar and
    the subprocess path can never disagree on frame content."""
    from atelier.core.capabilities.savings_summary import savings_frames, savings_segment

    kw = {"live_cost_usd": 1.234, "live_in_tok": 10_000, "live_cache_tok": 50_000, "live_out_tok": 2_000}
    frames = savings_frames("", atelier_root=atelier_root, no_color=True, **kw)  # type: ignore[arg-type]
    assert len(frames) >= 3
    assert frames[0] == frames[1] == frames[2]  # frame 0 holds 3 slots
    assert "1.234" in frames[0]

    for i in range(len(frames) + 1):
        _set_frame(atelier_root, i)
        seg = savings_segment("", atelier_root=atelier_root, no_color=True, **kw)  # type: ignore[arg-type]
        assert seg in frames, f"counter={i}: {seg!r} not in frames"


def test_segment_pins_review_needs_fix(atelier_root: Path) -> None:
    """NEEDS_FIX verdict must appear on every frame."""
    sid = "pinned-session"
    log = atelier_root / "reviews" / f"{sid}.jsonl"
    log.write_text(json.dumps({"verdict": "NEEDS_FIX", "consumed": False}) + "\n")

    from atelier.core.capabilities.savings_summary import savings_segment

    state = atelier_root / "statusline_frame_state.json"
    for i in range(4):
        state.write_text(json.dumps({"counter": i, "ts": time.time()}))
        seg = savings_segment(sid, atelier_root=atelier_root, no_color=True)
        assert "NEEDS_FIX" in seg, f"frame {i}: {seg!r}"
