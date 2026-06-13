"""Tests for the vs-vanilla replay baseline (vanilla_baseline + detectors)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atelier.core.capabilities import vanilla_baseline as vb
from atelier.core.capabilities.plugin_runtime import (
    detect_bash_grep_chain,
    detect_bash_sql,
    detect_edit_batch,
    detect_failed_edit,
    detect_glob_read,
    detect_grep_read,
    detect_read_batch,
)
from atelier.core.capabilities.pricing import get_model_pricing

_OPUS = "claude-opus-4-1"  # pinned, known rates: in=15 out=75 cR=1.5 cW=18.75


# --------------------------------------------------------------------------- #
# Synthetic transcript builders
# --------------------------------------------------------------------------- #


def _assistant(tool_uses, *, msg_id, model=_OPUS, usage=None, ts="2026-06-13T00:00:00Z"):
    """One assistant transcript line carrying tool_use blocks + usage."""
    content = [
        {"type": "tool_use", "id": tu["id"], "name": tu["name"], "input": tu.get("input", {})} for tu in tool_uses
    ]
    usage = usage or {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_input_tokens": 4000,
        "cache_creation_input_tokens": 500,
    }
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {"id": msg_id, "model": model, "usage": usage, "content": content},
    }


def _user_results(results, ts="2026-06-13T00:00:01Z"):
    """One user transcript line carrying tool_result blocks."""
    content = [
        {"type": "tool_result", "tool_use_id": r["tool_use_id"], "is_error": r.get("is_error", False)} for r in results
    ]
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": content}}


def _write(path: Path, entries) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Per-detector calls_saved (exact)
# --------------------------------------------------------------------------- #


def test_grep_read_two_reads_saves_two(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant([{"id": "g1", "name": "Grep", "input": {"pattern": "foo"}}], msg_id="m1"),
            _assistant(
                [{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}],
                msg_id="m2",
            ),
        ],
    )
    turns = vb.build_turns(t)
    # Grep(1) + Read(2) - 1 = 2
    assert detect_grep_read(turns)["calls_saved"] == 2


def test_glob_read_split_from_grep(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant([{"id": "gl1", "name": "Glob", "input": {"pattern": "**/*.py"}}], msg_id="m1"),
            _assistant([{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}], msg_id="m2"),
        ],
    )
    turns = vb.build_turns(t)
    # Glob is no longer folded into grep_read.
    assert detect_grep_read(turns)["calls_saved"] == 0
    # Glob(1) + Read(2) - 1 = 2
    assert detect_glob_read(turns)["calls_saved"] == 2


def test_failed_edit_chain(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant([{"id": "e1", "name": "Edit"}], msg_id="m1"),
            _user_results([{"tool_use_id": "e1", "is_error": True}]),
            _assistant([{"id": "r1", "name": "Read"}, {"id": "e2", "name": "Edit"}], msg_id="m2"),
        ],
    )
    turns = vb.build_turns(t)
    # failed Edit + (Read, Edit) follow-up = chain of 3 -> 2 saved
    assert detect_failed_edit(turns)["calls_saved"] == 2


def test_bash_sql(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant([{"id": "b1", "name": "Bash", "input": {"command": "psql -c 'select 1'"}}], msg_id="m1"),
            _assistant([{"id": "b2", "name": "Bash", "input": {"command": "sqlite3 db 'select 2'"}}], msg_id="m2"),
        ],
    )
    turns = vb.build_turns(t)
    assert detect_bash_sql(turns)["calls_saved"] == 1


def test_edit_batch(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant(
                [{"id": "e1", "name": "Edit"}, {"id": "e2", "name": "Edit"}, {"id": "e3", "name": "Write"}], msg_id="m1"
            )
        ],
    )
    turns = vb.build_turns(t)
    assert detect_edit_batch(turns)["calls_saved"] == 2


def test_read_batch(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant(
                [{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}, {"id": "r3", "name": "Read"}], msg_id="m1"
            )
        ],
    )
    turns = vb.build_turns(t)
    assert detect_read_batch(turns)["calls_saved"] == 2


def test_bash_grep_chain(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant([{"id": "b1", "name": "Bash", "input": {"command": "grep -rn foo src/"}}], msg_id="m1"),
            _assistant([{"id": "b2", "name": "Bash", "input": {"command": "rg bar lib/"}}], msg_id="m2"),
        ],
    )
    turns = vb.build_turns(t)
    assert detect_bash_grep_chain(turns)["calls_saved"] == 1


def test_single_occurrence_floors_at_zero(tmp_path):
    # One Read, one Bash-grep: each detector floors at n-1 = 0.
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant([{"id": "r1", "name": "Read"}], msg_id="m1"),
            _assistant([{"id": "b1", "name": "Bash", "input": {"command": "grep x y"}}], msg_id="m2"),
        ],
    )
    turns = vb.build_turns(t)
    assert detect_read_batch(turns)["calls_saved"] == 0
    assert detect_bash_grep_chain(turns)["calls_saved"] == 0


# --------------------------------------------------------------------------- #
# build_turns: is_error join + subagent inclusion
# --------------------------------------------------------------------------- #


def test_build_turns_populates_is_error(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant([{"id": "e1", "name": "Edit"}, {"id": "r1", "name": "Read"}], msg_id="m1"),
            _user_results([{"tool_use_id": "e1", "is_error": True}, {"tool_use_id": "r1", "is_error": False}]),
        ],
    )
    turns = vb.build_turns(t)
    tools = {tu["id"]: tu for tu in turns[0]["tool_uses"]}
    assert tools["e1"]["is_error"] is True
    assert tools["r1"]["is_error"] is False


def test_build_turns_includes_subagents(tmp_path):
    main = tmp_path / "sess.jsonl"
    _write(main, [_assistant([{"id": "r1", "name": "Read"}], msg_id="m1")])
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)
    _write(sub_dir / "agent.jsonl", [_assistant([{"id": "r2", "name": "Read"}], msg_id="m2")])

    turns = vb.build_turns(main)
    ids = {tu["id"] for turn in turns for tu in turn["tool_uses"]}
    assert {"r1", "r2"} <= ids


def test_replay_no_double_count_read_shared(tmp_path):
    # A Grep then two Reads: grep_read claims the reads; read_batch must not
    # re-credit the same reads in the shared-consumed replay.
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant([{"id": "g1", "name": "Grep"}], msg_id="m1"),
            _assistant([{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}], msg_id="m2"),
        ],
    )
    out = vb.replay_session(t)
    # grep_read = Grep(1)+Read(2)-1 = 2; read_batch sees no un-consumed reads -> 0.
    assert out["calls_saved"] == 2


# --------------------------------------------------------------------------- #
# pricing math + time
# --------------------------------------------------------------------------- #


def test_price_avoided_call_formula(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant(
                [{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}],
                msg_id="m1",
                usage={
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 4000,
                    "cache_creation_input_tokens": 500,
                },
            ),
            _assistant(
                [{"id": "r3", "name": "Read"}, {"id": "r4", "name": "Read"}],
                msg_id="m2",
                usage={
                    "input_tokens": 2000,
                    "output_tokens": 400,
                    "cache_read_input_tokens": 6000,
                    "cache_creation_input_tokens": 1500,
                },
            ),
        ],
    )
    from atelier.core.capabilities.savings_summary import read_transcript_stats

    stats = read_transcript_stats(t)
    assert stats is not None and stats.turns == 2
    per_call_tokens, per_call_cost = vb.price_avoided_call(stats, stats.model)

    avg_in = stats.input_tokens / 2
    avg_out = stats.output_tokens / 2
    avg_cr = stats.cache_read_tokens / 2
    avg_cw = stats.cache_write_tokens / 2
    expected_tokens = round((avg_in + avg_cr + avg_cw) * 1.3 + avg_out)
    assert per_call_tokens == expected_tokens

    expected_cost = get_model_pricing(_OPUS).request_cost_usd(
        input_tokens=round(avg_in * 1.3),
        cache_read_tokens=round(avg_cr * 1.3),
        cache_write_tokens=round(avg_cw * 1.3),
        output_tokens=round(avg_out),
    )
    assert per_call_cost == pytest.approx(expected_cost)


def test_replay_time_and_cost_aggregation(tmp_path):
    t = _write(
        tmp_path / "s.jsonl",
        [
            _assistant(
                [{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}, {"id": "r3", "name": "Read"}], msg_id="m1"
            ),
        ],
    )
    out = vb.replay_session(t)
    calls = out["calls_saved"]
    assert calls == 2  # 3 reads -> 2 saved
    assert out["time_saved_ms"] == calls * 7000

    from atelier.core.capabilities.savings_summary import read_transcript_stats

    stats = read_transcript_stats(t)
    per_call_tokens, per_call_cost = vb.price_avoided_call(stats, stats.model)
    assert out["tokens_saved"] == round(calls * per_call_tokens)
    assert out["cost_saved_usd"] == round(calls * per_call_cost, 6)


# --------------------------------------------------------------------------- #
# ANTI-DOUBLE-COUNT: vs-vanilla never enters measured saved_usd
# --------------------------------------------------------------------------- #


def test_compute_summary_saved_usd_excludes_vs_vanilla(tmp_path, monkeypatch):
    """A live session with a replayable vs-vanilla number must not inflate the
    measured saved_usd. With no savings sidecar, saved_usd stays 0.0 while the
    vs_vanilla fields are populated separately."""
    session_id = "abc-123"
    projects = tmp_path / "claude" / "projects" / "proj"
    projects.mkdir(parents=True)
    _write(
        projects / f"{session_id}.jsonl",
        [
            _assistant(
                [{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}, {"id": "r3", "name": "Read"}], msg_id="m1"
            ),
        ],
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    from atelier.core.capabilities.savings_summary import compute_savings_summary

    atelier_root = tmp_path / "atelier"
    atelier_root.mkdir()
    summary = compute_savings_summary(session_id, atelier_root=atelier_root)

    # Measured savings are untouched by the counterfactual replay.
    assert summary.saved_usd == 0.0
    assert summary.ctx_saved == 0
    # The separate vs-vanilla fields are populated.
    assert summary.vs_vanilla_calls == 2
    assert summary.vs_vanilla_usd > 0.0


def test_savings_line_appends_two_trailing_fields(tmp_path, monkeypatch):
    """savings_line gains exactly two trailing fields; the leading 14 are intact."""
    session_id = "line-1"
    projects = tmp_path / "claude" / "projects" / "proj"
    projects.mkdir(parents=True)
    _write(
        projects / f"{session_id}.jsonl",
        [_assistant([{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}], msg_id="m1")],
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("ATELIER_HIDE_MISSING_LOGIN", "1")

    from atelier.core.capabilities.savings_summary import savings_line

    atelier_root = tmp_path / "atelier"
    atelier_root.mkdir()
    line = savings_line(session_id, atelier_root=atelier_root)
    fields = line.split("|")
    assert len(fields) == 16
    # Trailing two: vs_vanilla_calls (int) and $vs_vanilla_usd.
    assert fields[14] == "1"  # 2 reads -> 1 saved
    assert fields[15].startswith("$")


def test_aggregate_persists_vs_vanilla_key(tmp_path, monkeypatch):
    session_id = "agg-1"
    projects = tmp_path / "claude" / "projects" / "proj"
    projects.mkdir(parents=True)
    _write(
        projects / f"{session_id}.jsonl",
        [_assistant([{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}], msg_id="m1")],
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    atelier_root = tmp_path / "atelier"
    atelier_root.mkdir()

    out = vb.aggregate_vanilla_baseline(atelier_root, window_days=3650, cap_usd=1000.0)
    assert out["calls_saved"] == 1
    assert out["estimate"] is True

    persisted = json.loads((atelier_root / "lifetime_savings.json").read_text())
    assert "vs_vanilla" in persisted
    assert persisted["vs_vanilla"]["calls_saved"] == 1


def test_aggregate_cost_cap(tmp_path, monkeypatch):
    session_id = "cap-1"
    projects = tmp_path / "claude" / "projects" / "proj"
    projects.mkdir(parents=True)
    _write(
        projects / f"{session_id}.jsonl",
        [_assistant([{"id": "r1", "name": "Read"}, {"id": "r2", "name": "Read"}], msg_id="m1")],
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    atelier_root = tmp_path / "atelier"
    atelier_root.mkdir()

    out = vb.aggregate_vanilla_baseline(atelier_root, window_days=3650, cap_usd=0.0)
    assert out["capped"] is True
    assert out["cost_saved_usd"] == 0.0
