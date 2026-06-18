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
    d = root / "sessions" / session_id
    d.mkdir(parents=True)
    (d / "savings.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


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


def test_routing_rows_summed_separately_from_context(tmp_path: Path) -> None:
    from atelier.core.capabilities.savings_summary import _read_session_routing_usd

    _write_sidecar(
        tmp_path,
        "s1",
        [
            {"kind": "routing", "usd": 0.012, "tool": "edit", "model": MODEL, "ts": "2026-06-16T10:00:00+00:00"},
            {"kind": "routing", "usd": 0.008, "tool": "read", "model": MODEL, "ts": "2026-06-16T10:01:00+00:00"},
            {"tool": "read", "tokens": 5000, "calls": 0, "model": MODEL, "ts": "2026-06-16T10:02:00+00:00"},
        ],
    )
    # Routing rows are summed by the dedicated reader (0.012 + 0.008).
    assert _read_session_routing_usd("s1", tmp_path) == pytest.approx(0.02)
    # ...and ignored by the context-savings reader (no token or usd leak).
    priced, calls, usd, _unpriced = _read_claude_session_savings("s1", tmp_path)
    assert priced == 5000
    assert calls == 0
    pricing = get_model_pricing(MODEL)
    assert pricing is not None and pricing.known
    assert usd == pytest.approx(pricing.input / 1_000_000 * 5000)


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


def test_carry_credit_stops_at_next_compaction(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    _write_sidecar(
        tmp_path,
        "s1",
        [
            {
                "tool": "read",
                "tokens": 1000,
                "calls": 0,
                "model": MODEL,
                "ts": (base + timedelta(minutes=1)).isoformat(),
            },
            {
                "kind": "compaction",
                "tokens": 50_000,
                "usd": 0.01,
                "model": MODEL,
                "ts": (base + timedelta(minutes=3)).isoformat(),
            },
        ],
    )
    turn_ts = [
        (base + timedelta(minutes=2)).isoformat(),
        (base + timedelta(minutes=4)).isoformat(),
        (base + timedelta(minutes=5)).isoformat(),
    ]
    carry_tokens, carry_usd = _carry_credit("s1", tmp_path, turn_ts)
    pricing = get_model_pricing(MODEL)
    assert pricing is not None
    assert carry_tokens == 1000
    assert carry_usd == pytest.approx(pricing.tokens_to_usd(1000, "cache_read"), abs=1e-9)


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


def test_carry_credit_attributes_subagent_rows_to_their_own_window(tmp_path: Path) -> None:
    """A token a subagent saved carries across that subagent's own later turns,
    not the main thread's — even though its sidecar row lands in the parent's
    savings.jsonl (the shared MCP process keys by the parent session id)."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def at(minutes: int, seconds: int = 0) -> str:
        return (base + timedelta(minutes=minutes, seconds=seconds)).isoformat()

    _write_sidecar(
        tmp_path,
        "s1",
        [
            {"tool": "read", "tokens": 1000, "calls": 0, "model": MODEL, "ts": at(0, 30)},
            {"tool": "read", "tokens": 500, "calls": 0, "model": MODEL, "ts": at(10, 30)},
        ],
    )
    main_turns = [at(0), at(1), at(30)]
    subagent_turns = [[at(10), at(11), at(12)]]
    carry_tokens, carry_usd = _carry_credit("s1", tmp_path, main_turns, subagent_turns)
    pricing = get_model_pricing(MODEL)
    assert pricing is not None
    # main row (12:00:30) -> 2 later MAIN turns (12:01, 12:30) => 1000 * 2.
    # subagent row (12:10:30, inside [12:10, 12:12]) -> 2 later SUBAGENT turns
    # (12:11, 12:12) => 500 * 2. Under the old main-only logic the subagent row
    # would have counted only 1 later main turn (12:30) => 500.
    assert carry_tokens == 3000
    assert carry_usd == pytest.approx(pricing.tokens_to_usd(3000, "cache_read"), abs=1e-9)


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


def test_read_transcript_stats_prices_1h_cache_writes_and_long_context(tmp_path: Path) -> None:
    """1h-TTL cache writes bill at $20/M (not $12.50) and >200k-context
    messages bill the whole request at the long-context premium."""
    base_msg = {
        "timestamp": "2026-01-01T12:00:00Z",
        "message": {
            "id": "small",
            "model": "claude-fable-5",
            "usage": {
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 1_000_000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 1_000_000,
                },
            },
        },
    }
    p = tmp_path / "sess.jsonl"
    p.write_text(json.dumps(base_msg) + "\n", encoding="utf-8")
    stats = read_transcript_stats(p)
    assert stats is not None
    # context = 2M > 200k threshold -> premium: in 1M*$20 + cW1h 1M*$20*(25/12.5)=$40
    assert stats.est_cost_usd == pytest.approx(20.0 + 40.0)

    # Same usage but under the threshold: in 1M*$10 + cW1h 1M*$20
    small = json.loads(json.dumps(base_msg))
    small["message"]["usage"]["input_tokens"] = 100_000
    small["message"]["usage"]["cache_creation_input_tokens"] = 50_000
    small["message"]["usage"]["cache_creation"]["ephemeral_1h_input_tokens"] = 50_000
    p.write_text(json.dumps(small) + "\n", encoding="utf-8")
    stats = read_transcript_stats(p)
    assert stats is not None
    assert stats.est_cost_usd == pytest.approx(0.1 * 10.0 + 0.05 * 20.0)


def test_read_transcript_stats_includes_subagent_usage(tmp_path: Path) -> None:
    """Subagent transcripts (<session>/subagents/*.jsonl) count toward tokens/cost,
    but not toward turns or tool calls."""
    p = tmp_path / "sess.jsonl"
    p.write_text(json.dumps(_usage_line("m1", "2026-01-01T12:00:00Z")) + "\n", encoding="utf-8")
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)
    (sub_dir / "agent-a1.jsonl").write_text(
        json.dumps(_usage_line("sub1", "2026-01-01T12:00:30Z")) + "\n", encoding="utf-8"
    )

    stats = read_transcript_stats(p)
    assert stats is not None
    # Usage buckets include both the main turn and the subagent turn.
    assert stats.input_tokens == 20
    assert stats.output_tokens == 10
    # Turns/timestamps remain main-transcript-only.
    assert stats.turns == 1
    assert stats.turn_timestamps == ["2026-01-01T12:00:00Z"]
    # Subagent assistant turns are bucketed separately for per-window carry.
    assert stats.subagent_turn_timestamps == [["2026-01-01T12:00:30Z"]]


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


def test_sidecar_routes_to_active_bridge_session_after_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Savings must route to the *active* session (the workspace bridge), not the
    MCP process's launch-time CLAUDE_CODE_SESSION_ID.

    The MCP server is long-lived: after a /clear the env var still names the
    dead launch session while the bridge (rewritten by SessionStart) names the
    live one. The Stop hook / statusline read by the live session, so the writer
    must agree or every post-clear session reports zero savings.
    """
    from atelier.gateway.adapters import mcp_server as m

    monkeypatch.setattr(m, "_atelier_root", lambda: tmp_path)

    # MCP launched in 'launch-sid'; the user then /cleared into 'active-sid'.
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "launch-sid")
    monkeypatch.setattr(m, "_read_workspace_session_bridge", lambda: ("active-sid", "claude-sonnet-4-5"))

    # Per-process identity (telemetry/ledger) still follows the env var ...
    assert m._claude_session_id() == "launch-sid"
    # ... but savings route to the live session the readers will look under.
    assert m._get_host_session_sidecar_path() == tmp_path / "sessions" / "active-sid" / "savings.jsonl"

    # Before SessionStart writes the bridge (first calls / hookless launchers),
    # fall back to the launch env var so early savings are still recorded.
    monkeypatch.setattr(m, "_read_workspace_session_bridge", lambda: ("", ""))
    assert m._get_host_session_sidecar_path() == tmp_path / "sessions" / "launch-sid" / "savings.jsonl"
