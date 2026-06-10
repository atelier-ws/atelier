"""Tests for avoided-call pricing and context-carry credit."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from atelier.core.capabilities.pricing import get_model_pricing
from atelier.core.capabilities.savings_summary import (
    _carry_credit,
    _read_claude_session_savings,
    read_transcript_stats,
)

MODEL = "claude-sonnet-4-5"


def _write_sidecar(root: Path, session_id: str, rows: list[dict[str, Any]]) -> None:
    d = root / "session_stats" / "claude"
    d.mkdir(parents=True)
    (d / f"{session_id}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _usage_line(msg_id: str, ts: str) -> dict[str, Any]:
    return {
        "timestamp": ts,
        "message": {
            "id": msg_id,
            "model": MODEL,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }


def test_read_claude_session_savings_includes_calls_usd(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path,
        "s1",
        [
            {"tool": "edit", "tokens": 0, "calls": 5, "calls_usd": 0.12, "model": ""},
            {"tool": "read", "tokens": 1000, "calls": 0, "model": MODEL},
        ],
    )
    priced, calls, usd, unpriced = _read_claude_session_savings("s1", tmp_path)
    pricing = get_model_pricing(MODEL)
    assert pricing is not None and pricing.known
    assert calls == 5
    assert priced == 1000
    assert unpriced == 0
    assert usd == pytest.approx(0.12 + pricing.input / 1_000_000 * 1000)


def test_carry_credit_counts_only_later_turns(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    row_ts = (base + timedelta(minutes=1)).isoformat()
    _write_sidecar(
        tmp_path,
        "s1",
        [
            # 1000 tokens saved before two later turns -> 2 carry turns.
            {"tool": "read", "tokens": 1000, "calls": 0, "model": MODEL, "ts": row_ts},
            # Compaction rows never carry (already dropped from context).
            {"kind": "compaction", "tokens": 50_000, "usd": 0.01, "model": MODEL, "ts": row_ts},
            # Unknown-model rows contribute nothing (never guess a rate).
            {"tool": "grep", "tokens": 1000, "calls": 0, "model": "mystery-model-x", "ts": row_ts},
        ],
    )
    turn_ts = [
        base.isoformat(),  # before the row - no carry
        (base + timedelta(minutes=2)).isoformat(),
        (base + timedelta(minutes=3)).isoformat(),
    ]
    carry_tokens, carry_usd = _carry_credit("s1", tmp_path, turn_ts)
    pricing = get_model_pricing(MODEL)
    assert pricing is not None
    assert carry_tokens == 2000
    assert carry_usd == pytest.approx(pricing.tokens_to_usd(2000, "cache_read"), abs=1e-9)
    assert carry_usd > 0


def test_carry_credit_handles_naive_row_timestamps(tmp_path: Path) -> None:
    # mcp_server writes naive utcnow().isoformat() rows; transcripts use "Z".
    _write_sidecar(
        tmp_path,
        "s1",
        [{"tool": "read", "tokens": 500, "calls": 0, "model": MODEL, "ts": "2026-01-01T12:01:00"}],
    )
    carry_tokens, carry_usd = _carry_credit("s1", tmp_path, ["2026-01-01T12:02:00Z"])
    assert carry_tokens == 500
    assert carry_usd > 0


def test_carry_credit_empty_without_transcript_turns(tmp_path: Path) -> None:
    _write_sidecar(
        tmp_path,
        "s1",
        [{"tool": "read", "tokens": 500, "calls": 0, "model": MODEL, "ts": "2026-01-01T12:01:00"}],
    )
    assert _carry_credit("s1", tmp_path, []) == (0, 0.0)
    assert _carry_credit("", tmp_path, ["2026-01-01T12:02:00Z"]) == (0, 0.0)


def test_read_transcript_stats_collects_turn_timestamps(tmp_path: Path) -> None:
    lines = [
        _usage_line("m1", "2026-01-01T12:00:00Z"),
        _usage_line("m2", "2026-01-01T12:01:00Z"),
        # Duplicate message id -> deduped, timestamp not double-counted.
        _usage_line("m2", "2026-01-01T12:01:30Z"),
    ]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    stats = read_transcript_stats(p)
    assert stats is not None
    assert stats.turn_timestamps == ["2026-01-01T12:00:00Z", "2026-01-01T12:01:00Z"]


def test_price_avoided_calls_usd_uses_cache_read_rate() -> None:
    from atelier.gateway.adapters.mcp_server import _price_avoided_calls_usd

    pricing = get_model_pricing(MODEL)
    assert pricing is not None
    expected = pricing.tokens_to_usd(3 * 100_000, "cache_read")
    assert expected > 0
    assert _price_avoided_calls_usd(MODEL, 3, 100_000) == pytest.approx(expected)
    assert _price_avoided_calls_usd("", 3, 100_000) == 0.0
    assert _price_avoided_calls_usd(MODEL, 3, 0) == 0.0
    assert _price_avoided_calls_usd(MODEL, 0, 100_000) == 0.0
