"""Replay real Claude Code transcripts to estimate roundtrips vanilla Claude
Code would have spent that Atelier avoided.

This produces a **comparative / counterfactual** number ("vs vanilla CC"). It is
deliberately kept SEPARATE from the measured token/cost savings: vanilla CC
would have re-sent the full growing context on each avoided roundtrip, so we
price avoided calls at a full-context-resend model and surface the result under
its own clearly-labelled field. It is never folded into ``SavingsSummary``'s
measured ``saved_usd``.

The detectors live in :mod:`atelier.core.capabilities.plugin_runtime` and are
fed turn lists built here by reusing the existing transcript reader machinery
from :mod:`atelier.core.capabilities.savings_summary`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from atelier.core.capabilities.plugin_runtime import (
    baseline_time_saved,
    detect_bash_grep_chain,
    detect_bash_sql,
    detect_edit_batch,
    detect_failed_edit,
    detect_glob_read,
    detect_grep_read,
    detect_read_batch,
    lifetime_savings_path,
)
from atelier.core.capabilities.pricing import get_model_pricing
from atelier.core.capabilities.savings_summary import (
    TranscriptStats,
    _subagent_transcripts,
    read_transcript_stats,
    resolve_model_id,
)

logger = logging.getLogger(__name__)

# Vanilla CC re-sends the full conversation context on each avoided roundtrip,
# and that context grows over the session. This multiplier prices an avoided
# call against a representative grown-context resend rather than the cheap
# (cache-hit) average. Conservative single point estimate.
CONTEXT_GROWTH_MULTIPLIER = 1.3

# Sonnet 4.5 is the fallback model when a transcript has no resolvable model,
# matching estimate_cost_usd's fallback so we never silently price at $0.
_FALLBACK_MODEL = "claude-sonnet-4-5"

# Default aggregation window / safety cap. The lifetime number is comparative,
# so we cap it to avoid an unbounded headline figure.
_DEFAULT_WINDOW_DAYS = 30
_DEFAULT_CAP_USD = 1000.0


def build_turns(transcript_path: str | Path) -> list[dict[str, Any]]:
    """Build a per-turn list for the detectors from a Claude transcript JSONL.

    Mirrors :func:`read_transcript_stats`: dedup assistant turns on ``msg.id``,
    walk ``msg.content[]`` for ``tool_use`` blocks, and include subagent
    (sidechain) transcripts. Each emitted turn is::

        {
            "tool_uses": [{"name", "id", "input", "is_error"}, ...],
            "usage": {input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens},
            "timestamp": "<iso>",
        }

    ``is_error`` is populated by joining each ``tool_use`` to its matching
    ``tool_result`` (on ``tool_use_id``) in the following user turn(s) — nothing
    else in the transcript sets it, so without this join ``detect_failed_edit``
    can never fire.
    """
    p = Path(transcript_path)
    sources: list[Path] = [p]
    sources.extend(_subagent_transcripts(p))

    turns: list[dict[str, Any]] = []
    # Maps tool_use_id -> the tool_use dict awaiting its result.
    pending: dict[str, dict[str, Any]] = {}
    seen_msg_ids: set[str] = set()

    for source in sources:
        try:
            raw_lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in raw_lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                # Malformed JSON in transcript lines is common/expected noise
                continue
            except Exception:
                logging.exception("Recovered from broad exception handler")
                continue
            msg = entry.get("message") or {}
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue

            entry_type = entry.get("type")
            if entry_type == "assistant":
                msg_id = str(msg.get("id") or "").strip()
                if msg_id and msg_id in seen_msg_ids:
                    continue
                if msg_id:
                    seen_msg_ids.add(msg_id)
                tool_uses: list[dict[str, Any]] = []
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    tu_id = str(block.get("id") or "").strip() or None
                    tu: dict[str, Any] = {
                        "name": block.get("name") or "unknown",
                        "id": tu_id,
                        "input": block.get("input") or {},
                        "is_error": False,
                    }
                    tool_uses.append(tu)
                    if tu_id:
                        pending[tu_id] = tu
                usage = msg.get("usage") or {}
                turns.append(
                    {
                        "tool_uses": tool_uses,
                        "usage": {
                            "input_tokens": int(usage.get("input_tokens", 0) or 0),
                            "output_tokens": int(usage.get("output_tokens", 0) or 0),
                            "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
                            "cache_creation_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
                        },
                        "timestamp": str(entry.get("timestamp") or ""),
                    }
                )
            elif entry_type == "user":
                # Join tool_result blocks back to their originating tool_use.
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tid = str(block.get("tool_use_id") or "").strip()
                    target = pending.get(tid)
                    if target is not None and block.get("is_error"):
                        target["is_error"] = True

    return turns


# Labelled detectors, in claim order. The label is the human-readable pattern
# name surfaced by `atelier savings --deep`.
_DETECTORS: tuple[tuple[str, Any], ...] = (
    ("grep->read", detect_grep_read),
    ("glob->read", detect_glob_read),
    ("failed-edit", detect_failed_edit),
    ("read-batch", detect_read_batch),
    ("edit-batch", detect_edit_batch),
    ("bash->sql", detect_bash_sql),
    ("bash-grep-chain", detect_bash_grep_chain),
)


# Mtime-keyed cache for replay_session: the result only changes when the
# transcript file changes (a new Claude turn is appended). Avoids re-running
# all detectors on every statusline poll when the transcript is stable.
_replay_session_cache: dict[str, tuple[float, dict[str, Any]]] = {}  # path_str → (mtime, result)


def replay_session(transcript_path: str | Path) -> dict[str, Any]:
    """Replay one transcript through every detector and sum all hits.

    A shared ``consumed_tool_use_ids`` set is threaded through the detectors so
    a single Read is never double-credited (e.g. by both grep_read and
    read_batch). Returns the final savings shape::

        {"calls_saved", "time_saved_ms", "tokens_saved", "cost_saved_usd"}

    Results are cached by transcript mtime so repeated statusline polls during
    the same Claude turn are fast (< 1ms instead of ~20ms).
    """
    _path = Path(transcript_path)
    try:
        _mtime = _path.stat().st_mtime
    except OSError:
        _mtime = 0.0
    _key = str(_path)
    _cached = _replay_session_cache.get(_key)
    if _cached is not None and _cached[0] == _mtime:
        return _cached[1]
    turns = build_turns(transcript_path)
    consumed: set[str] = set()

    # Order matters only for which detector claims a shared tool_use first; the
    # consumed set keeps the total honest regardless. Navigation chains first,
    # then batches, then bash families.
    by_detector: dict[str, int] = {}
    calls_saved = 0
    for label, detector in _DETECTORS:
        hit = detector(turns, consumed_tool_use_ids=consumed)["calls_saved"]
        if hit:
            by_detector[label] = by_detector.get(label, 0) + hit
        calls_saved += hit

    stats = read_transcript_stats(transcript_path)
    per_call_tokens, per_call_cost = price_avoided_call(stats, stats.model if stats else "")

    _result = {
        "calls_saved": calls_saved,
        "time_saved_ms": baseline_time_saved(calls_saved)["time_saved_ms"],
        "tokens_saved": round(calls_saved * per_call_tokens),
        "cost_saved_usd": round(calls_saved * per_call_cost, 6),
        "by_detector": by_detector,
    }
    _replay_session_cache[_key] = (_mtime, _result)
    return _result


def price_avoided_call(stats: TranscriptStats | None, model: str) -> tuple[int, float]:
    """Price a single avoided roundtrip under a full-context-resend model.

    Vanilla CC re-sends the full (growing) context on each avoided call, so we
    take the session's average per-turn buckets, grow the *input* side by
    :data:`CONTEXT_GROWTH_MULTIPLIER`, and price the result with the existing
    per-model rate card. Output is not grown (the model emits one response
    regardless of context size).
    """
    if stats is None or stats.turns <= 0:
        stats_turns = 1
        avg_in = avg_out = avg_cr = avg_cw = 0.0
    else:
        stats_turns = max(1, stats.turns)
        avg_in = stats.input_tokens / stats_turns
        avg_out = stats.output_tokens / stats_turns
        avg_cr = stats.cache_read_tokens / stats_turns
        avg_cw = stats.cache_write_tokens / stats_turns

    per_call_tokens = round((avg_in + avg_cr + avg_cw) * CONTEXT_GROWTH_MULTIPLIER + avg_out)

    model_id = resolve_model_id(model)
    pricing = get_model_pricing(model_id) if model_id else None
    if pricing is None or not pricing.known or pricing.input <= 0:
        pricing = get_model_pricing(_FALLBACK_MODEL)
    per_call_cost = pricing.request_cost_usd(
        input_tokens=round(avg_in * CONTEXT_GROWTH_MULTIPLIER),
        cache_read_tokens=round(avg_cr * CONTEXT_GROWTH_MULTIPLIER),
        cache_write_tokens=round(avg_cw * CONTEXT_GROWTH_MULTIPLIER),
        output_tokens=round(avg_out),
    )
    return per_call_tokens, per_call_cost


def _transcript_paths_in_window(window_days: int) -> list[Path]:
    """Discover Claude transcript JSONL files modified within *window_days*.

    Main-session transcripts only (``<project>/<uuid>.jsonl``); subagent
    sidechains are pulled in per-session by ``build_turns`` so they are not
    double-counted here.
    """
    claude_root = os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_HOME") or ""
    projects = Path(claude_root) / "projects" if claude_root else Path.home() / ".claude" / "projects"
    if not projects.is_dir():
        return []
    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).timestamp()
    out: list[Path] = []
    try:
        for path in projects.glob("*/*.jsonl"):
            # Skip subagent sidechains; they are merged into their parent session.
            if "subagents" in path.parts:
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    out.append(path)
            except OSError:
                continue
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return []
    return out


def aggregate_vanilla_baseline(
    root: str | Path,
    *,
    window_days: int = _DEFAULT_WINDOW_DAYS,
    cap_usd: float = _DEFAULT_CAP_USD,
) -> dict[str, Any]:
    """Aggregate the vs-vanilla replay across recent sessions and persist it.

    Replays every main-session transcript modified within *window_days*, sums
    the per-session savings, caps ``cost_saved_usd`` at *cap_usd*, and persists
    the result under a NEW ``vs_vanilla`` key in ``lifetime_savings.json`` (no
    schema collision with the measured savings keys).
    """
    calls = 0
    time_ms = 0
    tokens = 0
    cost = 0.0
    sessions = 0
    by_detector: dict[str, int] = {}
    for path in _transcript_paths_in_window(window_days):
        try:
            session = replay_session(path)
        except Exception:
            logging.exception("Recovered from broad exception handler")
            continue
        if session["calls_saved"] <= 0:
            continue
        sessions += 1
        calls += session["calls_saved"]
        time_ms += session["time_saved_ms"]
        tokens += session["tokens_saved"]
        cost += session["cost_saved_usd"]
        for label, hit in session.get("by_detector", {}).items():
            by_detector[label] = by_detector.get(label, 0) + hit

    capped = cost > cap_usd
    if capped:
        cost = cap_usd

    result = {
        "calls_saved": calls,
        "time_saved_ms": time_ms,
        "tokens_saved": tokens,
        "cost_saved_usd": round(cost, 6),
        "by_detector": by_detector,
        "sessions": sessions,
        "window_days": window_days,
        "cap_usd": cap_usd,
        "capped": capped,
        "estimate": True,
        "note": "Comparative estimate: roundtrips vanilla Claude Code would have spent, priced at full-context resend. Not a measured saving.",
    }

    try:
        from atelier.core.capabilities.plugin_runtime import _read_json, _write_json

        path = lifetime_savings_path(root)
        data = _read_json(path, {})
        if not isinstance(data, dict):
            data = {}
        data["vs_vanilla"] = result
        _write_json(path, data)
    except Exception:
        logging.exception("Recovered from broad exception handler")

    return result
