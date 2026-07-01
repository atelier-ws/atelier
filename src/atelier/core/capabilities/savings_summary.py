"""Unified savings/cost computation for all hooks and host integrations.

Single source of truth for:
- Claude transcript discovery and per-model cost parsing
- Session savings aggregation (live events + session_stats)
- savings --line output formatting (consumed by statusline.sh via ``atelier savings --line``)

Previously this logic was spread across:
- integrations/claude/plugin/scripts/statusline.sh (inline Python heredoc)
- integrations/claude/plugin/hooks/stop.py (_read_transcript_stats, _estimate_cost_usd, etc.)
- plugin_runtime.py (load_live_savings_summary)
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------

# Map display names (as returned by Claude Code's context_window.model.display_name)
# to canonical model IDs (as used by the Anthropic API / LiteLLM catalog).
_DISPLAY_NAME_MODEL_MAP: dict[str, str] = {
    "opus 4.8": "claude-opus-4-8",
    "opus 4.7": "claude-opus-4-7",
    "opus 4.6": "claude-opus-4-6",
    "opus 4.5": "claude-opus-4-5",
    "opus 4.1": "claude-opus-4-1",
    "opus 4": "claude-opus-4-0",
    "sonnet 4.7": "claude-sonnet-4-7",
    "sonnet 4.6": "claude-sonnet-4-6",
    "sonnet 4": "claude-sonnet-4-0",
    "haiku 4.7": "claude-haiku-4-7",
    "haiku 4.6": "claude-haiku-4-6",
    "haiku 4.5": "claude-haiku-4-5",
}


def is_real_model(raw: object) -> bool:
    """Return True when *raw* is a genuine model identifier (not a placeholder)."""
    if not isinstance(raw, str):
        return False
    candidate = raw.strip()
    return bool(candidate and not candidate.startswith("<") and candidate not in {"_default", "unknown", "none"})


def resolve_model_id(raw: str | None) -> str:
    """Map a display name (``"Opus 4.7"``) to a canonical model id when possible.

    Falls back to returning *raw* unchanged when it already looks canonical
    (e.g. ``"claude-opus-4-7"``).
    """
    if not raw:
        return ""
    key = raw.strip().lower()
    # Strip a trailing descriptor like " (1m context)" so display variants
    # ("Opus 4.8 (1M context)") still resolve to the canonical id.
    key = re.sub(r"\s*\([^)]*\)\s*$", "", key).strip()
    if key in _DISPLAY_NAME_MODEL_MAP:
        return _DISPLAY_NAME_MODEL_MAP[key]
    return raw.strip()


def estimate_cost_usd(
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    cache_write_1h_tokens: int = 0,
    long_context: bool = False,
) -> float:
    """Estimate cost using the per-model rate card.

    ``cache_write_tokens`` is the 5m-TTL portion when ``cache_write_1h_tokens``
    is supplied (1h writes bill at a higher rate). ``long_context=True`` prices
    the bucket at the model's >200k per-request premium rates.

    Falls back to Sonnet 4.6 rates when the model is unknown so we never
    silently show $0 for an active session.
    """
    try:
        from atelier.core.capabilities.pricing import get_model_pricing

        pricing = get_model_pricing(model_id) if model_id else None
        if pricing is None or not pricing.known or pricing.input <= 0:
            pricing = get_model_pricing("claude-sonnet-4-5")
        return pricing.request_cost_usd(
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cache_read_tokens=int(cache_read_tokens or 0),
            cache_write_tokens=int(cache_write_tokens or 0),
            cache_write_1h_tokens=int(cache_write_1h_tokens or 0),
            long_context=long_context,
        )
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return ((input_tokens or 0) * 3 + (output_tokens or 0) * 15) / 1_000_000


# ---------------------------------------------------------------------------
# Claude transcript helpers
# ---------------------------------------------------------------------------


def claude_transcript_candidates(session_id: str) -> list[Path]:
    """Return all Claude transcript JSONL paths for *session_id*, newest first.

    Searches:
    - ``$CLAUDE_CONFIG_DIR/projects/*/<session_id>.jsonl``
    - ``$CLAUDE_CONFIG_DIR/projects/*/*/subagents/<session_id>.jsonl``
    - Falls back to ``~/.claude/projects/...``
    """
    session_id = session_id.strip()
    if not session_id:
        return []
    claude_root = os.environ.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_HOME") or ""
    projects = Path(claude_root) / "projects" if claude_root else Path.home() / ".claude" / "projects"
    if not projects.is_dir():
        return []
    paths: list[Path] = []
    try:
        paths.extend(projects.glob(f"*/{session_id}.jsonl"))
        paths.extend(projects.glob(f"*/*/subagents/{session_id}.jsonl"))
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return []
    return sorted((p for p in paths if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)


_CTX_TAIL_BYTES = 65536


def transcript_context_state(session_id: str) -> tuple[int, str]:
    """Return (live context tokens, model) for a Claude session.

    Context = the most recent assistant turn's input + cache reads + cache
    writes — i.e. what the next turn will re-read. Tail-reads the newest
    transcript so it is cheap enough to call from per-tool-call hooks.
    Returns ``(0, "")`` when the session or usage cannot be located.
    """
    candidates = claude_transcript_candidates(session_id)
    if not candidates:
        return 0, ""
    newest = candidates[0]
    try:
        with newest.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - _CTX_TAIL_BYTES))
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return 0, ""
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue  # first tail line may be partial
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message") or {}
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(usage, dict):
            continue
        ctx = (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
        )
        if ctx <= 0:
            continue
        model = str(msg.get("model") or "").strip()
        return ctx, model
    return 0, ""


@dataclass
class TranscriptStats:
    """Parsed statistics from a Claude transcript JSONL file."""

    tool_calls: int = 0
    # Distinct assistant turns (one per assistant message id with usage).
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    est_cost_usd: float = 0.0
    model: str = ""
    models_used: list[str] = field(default_factory=list)
    tools_used: dict[str, int] = field(default_factory=dict)
    # Per-model token buckets: {model_id: {in, out, cR, cW}} for weighted pricing.
    per_model: dict[str, dict[str, int]] = field(default_factory=dict)
    # Last model seen in transcript (most recent turn). Differs from `model`
    # (first seen) for resumed sessions where user switched models mid-session.
    last_model: str = ""
    # ISO timestamps of assistant turns with usage — drives the carry credit.
    turn_timestamps: list[str] = field(default_factory=list)
    # Per-subagent assistant-turn timestamps (one inner list per subagent
    # transcript). Drives per-window carry: a token a subagent saved carries
    # across that subagent's own later turns, not the main thread's.
    subagent_turn_timestamps: list[list[str]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens

    def savings_input_rate(self) -> float | None:
        """Weighted $/input-token rate across all models used in this session.

        Saved tokens are context tokens NOT sent to the model — they would have
        been charged as NEW INPUT tokens.  We weight each model's input rate by
        the number of input tokens it actually processed.
        """
        from atelier.core.capabilities.pricing import get_model_pricing

        if not self.per_model:
            return None
        total_input = sum(b.get("in", 0) for b in self.per_model.values())
        if total_input <= 0:
            for m in self.per_model:
                p = get_model_pricing(m)
                if p and p.known and p.input > 0:
                    return p.input / 1_000_000
            return None
        weighted = 0.0
        for m, b in self.per_model.items():
            p = get_model_pricing(m)
            if p and p.known and p.input > 0:
                weighted += p.input / 1_000_000 * b.get("in", 0)
        return weighted / total_input if weighted > 0 else None


# --- stop-hook savings block embedded in the transcript -------------------
# The stop hook writes its session summary into the conversation, so the
# numbers persist inside the session file itself. The middle dot appears
# either raw (·) or JSON-escaped (·) depending on nesting depth.
_STOP_SEP = r"(?:\\u00b7|·)"
_STOP_EST_COST_RE = re.compile(r"est\. cost: ~\$([0-9][0-9.,]*)")
_STOP_SAVINGS_RE = re.compile(
    rf"savings: \$([0-9][0-9.,]*) {_STOP_SEP} ([0-9,]+) tokens saved {_STOP_SEP} ([0-9,]+) calls avoided"
)
_STOP_CARRY_RE = re.compile(
    rf"context carry: \$([0-9][0-9.,]*)"
    rf"(?:{_STOP_SEP} ([0-9,]+) tokens)?"  # token count optional in older hook format
)
# Older format: carry embedded inline in the savings line as "· incl. context carry $X"
_STOP_CARRY_INLINE_RE = re.compile(r"incl\. context carry \$([0-9][0-9.,]*)")
_STOP_CALLS_RE = re.compile(rf"([0-9,]+) turns {_STOP_SEP} ([0-9,]+) tool calls")


@dataclass
class TranscriptSavingsBlock:
    """Savings summary recovered from a stop-hook block inside a transcript."""

    est_cost_usd: float = 0.0
    saved_usd: float = 0.0
    saved_tokens: int = 0
    calls_avoided: int = 0
    carry_usd: float = 0.0
    carry_tokens: int = 0
    # Main-transcript counters from the same block; consumers can cross-check
    # these against trace-derived numbers to catch import regressions.
    turns: int = 0
    tool_calls: int = 0


def read_transcript_savings_block(transcript_path: str | Path) -> TranscriptSavingsBlock | None:
    """Parse the LAST stop-hook savings block embedded in a transcript JSONL.

    Only hook attachment entries (``type: "attachment"`` with attachment type
    ``hook_system_message`` / ``hook_success``) are considered — never free
    conversation text, which may quote savings blocks from other sessions.
    This recovers savings, context carry, and the estimated cost from the
    session file alone — no Atelier-local sidecars or run ledger required —
    so it also works on session files copied from another machine.
    Returns ``None`` when no block is present (session never displayed one).
    """
    p = Path(transcript_path)
    last_text = ""
    try:
        with p.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if "savings:" not in raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "attachment":
                    continue
                attachment = entry.get("attachment") or {}
                if not isinstance(attachment, dict):
                    continue
                if attachment.get("type") not in {"hook_system_message", "hook_success"}:
                    continue
                text = attachment.get("content") or attachment.get("stdout") or ""
                if isinstance(text, str) and _STOP_SAVINGS_RE.search(text):
                    last_text = text
    except OSError:
        return None
    if not last_text:
        return None

    def _usd(raw: str) -> float:
        return float(raw.replace(",", ""))

    def _num(raw: str) -> int:
        return int(raw.replace(",", ""))

    block = TranscriptSavingsBlock()
    savings = _STOP_SAVINGS_RE.search(last_text)
    if savings:
        block.saved_usd = _usd(savings.group(1))
        block.saved_tokens = _num(savings.group(2))
        block.calls_avoided = _num(savings.group(3))
    carry = _STOP_CARRY_RE.search(last_text)
    if carry:
        block.carry_usd = _usd(carry.group(1))
        block.carry_tokens = _num(carry.group(2)) if carry.group(2) else 0
    elif carry_inline := _STOP_CARRY_INLINE_RE.search(last_text):
        # Older format: carry was part of savings line, no token count available
        block.carry_usd = _usd(carry_inline.group(1))
    cost = _STOP_EST_COST_RE.search(last_text)
    if cost:
        block.est_cost_usd = _usd(cost.group(1))
    calls = _STOP_CALLS_RE.search(last_text)
    if calls:
        block.turns = _num(calls.group(1))
        block.tool_calls = _num(calls.group(2))
    return block


def _subagent_transcripts(transcript_path: Path) -> list[Path]:
    """Return subagent (sidechain) transcripts recorded for a session.

    Claude Code stores Agent-tool transcripts under
    ``<project>/<session-id>/subagents/*.jsonl`` next to the main
    ``<session-id>.jsonl``. Their usage is billed to the session (and is
    included in Claude's own ``cost.total_cost_usd``), so pricing must
    include them.
    """
    subagent_dir = transcript_path.parent / transcript_path.stem / "subagents"
    if not subagent_dir.is_dir():
        return []
    return sorted(subagent_dir.glob("*.jsonl"))


def _long_context_threshold(model: str, cache: dict[str, int]) -> int:
    """Per-request long-context threshold for *model* (0 = no premium), cached."""
    if model not in cache:
        try:
            from atelier.core.capabilities.pricing import get_model_pricing

            cache[model] = get_model_pricing(resolve_model_id(model)).long_context_threshold()
        except Exception:
            logging.exception("Recovered from broad exception handler")
            cache[model] = 0
    return cache[model]


def _bucket_cost_usd(model_id: str, b: dict[str, int]) -> float:
    """Price one per-model bucket: base portion + >200k premium portion.

    ``in``/``out``/``cR``/``cW`` are totals; ``*_lc`` keys hold the subset from
    messages over the long-context threshold; ``cW1`` is the 1h-TTL cache-write
    subset of ``cW``.
    """
    lc = {k: b.get(f"{k}_lc", 0) for k in ("in", "out", "cR", "cW", "cW1")}
    cw1 = b.get("cW1", 0)
    cost = estimate_cost_usd(
        model_id=model_id,
        input_tokens=b["in"] - lc["in"],
        output_tokens=b["out"] - lc["out"],
        cache_read_tokens=b["cR"] - lc["cR"],
        cache_write_tokens=(b["cW"] - cw1) - (lc["cW"] - lc["cW1"]),
        cache_write_1h_tokens=cw1 - lc["cW1"],
    )
    if any(lc.values()):
        cost += estimate_cost_usd(
            model_id=model_id,
            input_tokens=lc["in"],
            output_tokens=lc["out"],
            cache_read_tokens=lc["cR"],
            cache_write_tokens=lc["cW"] - lc["cW1"],
            cache_write_1h_tokens=lc["cW1"],
            long_context=True,
        )
    return cost


# Mtime-keyed cache for read_transcript_stats: the transcript only grows when
# Claude makes a new turn, so repeated statusline polls during the same turn
# can reuse the parsed result (< 1ms instead of ~15ms for large transcripts).
_transcript_stats_cache: dict[str, tuple[int, "TranscriptStats | None"]] = {}  # path → (mtime_ns, result)


def read_transcript_stats(transcript_path: str | Path) -> "TranscriptStats | None":
    """Parse a Claude transcript JSONL and return session stats.

    Cost is computed per model per turn because users can switch models
    mid-conversation (e.g. Opus → Sonnet).  Each token bucket is priced with
    its own rate card and summed.

    Token buckets and cost also include the session's subagent transcripts
    (``<session-id>/subagents/*.jsonl``) — their usage is billed to the
    session. Turn count, tool counts, and the session model fields remain
    main-transcript-only.

    Results are cached by mtime_ns so repeated statusline polls during the same
    Claude turn are fast (< 1ms instead of ~15ms).
    """
    p = Path(transcript_path)
    if not p.exists():
        return None
    try:
        _mtime_ns = p.stat().st_mtime_ns
    except OSError:
        _mtime_ns = 0
    _key = str(p)
    _cached = _transcript_stats_cache.get(_key)
    if _cached is not None and _cached[0] == _mtime_ns:
        return _cached[1]

    tool_calls = 0
    turns = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    tools_used: dict[str, int] = {}
    model_id = ""
    last_model_id = ""  # tracks most recently seen model (for resumed sessions)
    per_model: dict[str, dict[str, int]] = {}
    turn_timestamps: list[str] = []
    subagent_turn_timestamps: list[list[str]] = []
    seen_usage_message_ids: set[str] = set()
    seen_tool_use_ids: set[str] = set()
    lc_thresholds: dict[str, int] = {}

    sources: list[tuple[Path, bool]] = [(p, True)]
    sources.extend((sub, False) for sub in _subagent_transcripts(p))

    try:
        for source, is_main in sources:
            sub_ts: list[str] = []
            for raw in source.read_text(encoding="utf-8", errors="replace").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                except Exception:
                    logging.exception("Recovered from broad exception handler")
                    continue

                msg = entry.get("message") or {}
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or "").strip()

                candidate = msg.get("model") or entry.get("model") or ""
                if is_main and is_real_model(candidate):
                    candidate_str = str(candidate).strip()
                    if not model_id:
                        model_id = candidate_str
                    last_model_id = candidate_str

                usage = msg.get("usage") or {}
                if not isinstance(usage, dict):
                    continue
                in_t = int(usage.get("input_tokens", 0) or 0)
                out_t = int(usage.get("output_tokens", 0) or 0)
                cr_t = int(usage.get("cache_read_input_tokens", 0) or 0)
                cw_t = int(usage.get("cache_creation_input_tokens", 0) or 0)
                cache_creation = usage.get("cache_creation") or {}
                cw1_t = (
                    int(cache_creation.get("ephemeral_1h_input_tokens", 0) or 0)
                    if isinstance(cache_creation, dict)
                    else 0
                )
                cw1_t = min(cw1_t, cw_t)
                has_usage = bool(in_t or out_t or cr_t or cw_t)
                count_usage = has_usage
                if has_usage and msg_id:
                    if msg_id in seen_usage_message_ids:
                        count_usage = False
                    else:
                        seen_usage_message_ids.add(msg_id)
                if count_usage:
                    input_tokens += in_t
                    output_tokens += out_t
                    cache_read_tokens += cr_t
                    cache_write_tokens += cw_t
                    # A turn = one assistant message with non-zero usage.
                    # Dedup on msg_id (same dedup as token accumulation).
                    ts_raw = str(entry.get("timestamp") or "")
                    if is_main:
                        turns += 1
                        if ts_raw:
                            turn_timestamps.append(ts_raw)
                    elif ts_raw:
                        # Subagent assistant turn — bucketed per subagent so
                        # carry credit attributes a subagent-saved token to that
                        # subagent's own context window, not the main thread's.
                        sub_ts.append(ts_raw)

                    turn_model = str(msg.get("model") or entry.get("model") or "").strip()
                    if is_real_model(turn_model):
                        bucket = per_model.setdefault(
                            turn_model,
                            {"in": 0, "out": 0, "cR": 0, "cW": 0, "cW1": 0}
                            | {f"{k}_lc": 0 for k in ("in", "out", "cR", "cW", "cW1")},
                        )
                        bucket["in"] += in_t
                        bucket["out"] += out_t
                        bucket["cR"] += cr_t
                        bucket["cW"] += cw_t
                        bucket["cW1"] += cw1_t
                        # Per-request long-context premium: the whole message
                        # bills at premium rates once its context crosses the
                        # model's threshold (e.g. 200k).
                        threshold = _long_context_threshold(turn_model, lc_thresholds)
                        if threshold and (in_t + cr_t + cw_t) > threshold:
                            bucket["in_lc"] += in_t
                            bucket["out_lc"] += out_t
                            bucket["cR_lc"] += cr_t
                            bucket["cW_lc"] += cw_t
                            bucket["cW1_lc"] += cw1_t

                if not is_main:
                    continue
                for index, block in enumerate(msg.get("content") or []):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name") or "unknown"
                    tool_use_id = str(block.get("id") or "").strip()
                    tool_key = tool_use_id or (f"{msg_id}:{index}:{name}" if msg_id else "")
                    if tool_key:
                        if tool_key in seen_tool_use_ids:
                            continue
                        seen_tool_use_ids.add(tool_key)
                    tools_used[name] = tools_used.get(name, 0) + 1
                    tool_calls += 1
            if not is_main and sub_ts:
                subagent_turn_timestamps.append(sub_ts)
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return None

    resolved_model = resolve_model_id(model_id)
    resolved_last_model = resolve_model_id(last_model_id) if last_model_id else resolved_model

    if per_model:
        est_cost_usd = sum(_bucket_cost_usd(resolve_model_id(m), b) for m, b in per_model.items())
    else:
        est_cost_usd = estimate_cost_usd(
            model_id=resolved_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

    _result = TranscriptStats(
        tool_calls=tool_calls,
        turns=turns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        est_cost_usd=est_cost_usd,
        model=resolved_model,
        last_model=resolved_last_model,
        models_used=(
            sorted(resolve_model_id(m) for m in per_model)
            if per_model
            else ([resolved_model] if resolved_model else [])
        ),
        tools_used=tools_used,
        per_model={resolve_model_id(m): b for m, b in per_model.items()} if per_model else {},
        turn_timestamps=turn_timestamps,
        subagent_turn_timestamps=subagent_turn_timestamps,
    )
    _transcript_stats_cache[_key] = (_mtime_ns, _result)
    return _result


# ---------------------------------------------------------------------------
# Savings aggregation
# ---------------------------------------------------------------------------


@dataclass
class SavingsSummary:
    saved_usd: float = 0.0
    ctx_saved: int = 0
    smart_calls: int = 0
    carry_tokens: int = 0  # saved tokens x later turns (context-carry volume)
    carry_usd: float = 0.0  # carry volume priced at the per-row cache-read rate
    routing_saved_usd: float = 0.0
    est_cost_usd: float = 0.0  # baseline cost from terminated session transcript
    total_tokens: int = 0  # cumulative session tokens (in+out+cR+cW) from transcript
    display_input_tokens: int = 0  # cumulative fresh input = input + cache_write
    display_cache_tokens: int = 0  # cumulative cache reads
    display_output_tokens: int = 0  # cumulative output
    status_text: str = ""
    saved_pct: float = 0.0
    carry_pct: float = 0.0
    # N4 — per-tool exact in/out token ledger (additive; not part of the
    # pipe-delimited savings_line). Keyed by tool name -> {calls, input_tokens,
    # output_tokens}.
    tool_token_ledger: dict[str, dict[str, int]] = field(default_factory=dict)
    tool_ledger_input_tokens: int = 0
    tool_ledger_output_tokens: int = 0
    # Comparative "vs vanilla Claude Code" replay (roundtrips vanilla CC would
    # have spent that Atelier avoided, priced at full-context resend). This is a
    # SEPARATE counterfactual estimate and is intentionally NOT added into
    # saved_usd or any measured-savings field.
    vs_vanilla_calls: int = 0
    vs_vanilla_usd: float = 0.0


def _price_savings_row(ev: dict[str, Any]) -> tuple[int, float, int, float, int]:
    """Price ONE ``savings.jsonl`` row — the single rule every surface shares.

    Returns ``(priced_tokens, priced_usd, calls, calls_usd, unpriced_tokens)``.

    The statusline, stop hook, ``atelier savings`` CLI, dashboard, and web
    Savings page all run rows through this one function so their realized-savings
    numbers agree.  The rule mirrors the long-standing live/statusline pricing:

    * ``calls`` and the avoided-call credit are counted for every row.  The
      credit was priced at write time and is stored as ``calls_usd`` (or the
      older ``calls_cost_saved_usd``).
    * tokens above the 2M per-call sanity cap are dropped (pre-fce2110
      inflation bug).
    * ``kind == "compaction"`` rows carry a pre-computed ``usd`` (cache-read
      rate) for ``tokens`` dropped from context — credited as-is, never
      re-priced at the input rate.
    * every other row uses the pre-priced ``cost_saved_usd`` the dispatcher
      wrote (priced at the model in use at write time); rows that predate that
      field are re-priced at the row model's input rate.  Rows with neither a
      stored cost nor a priceable model are returned as ``unpriced_tokens`` so
      the caller can apply a single weighted fallback without distorting the
      usd/token ratio.
    """
    from atelier.core.capabilities.pricing import get_model_pricing

    tokens = max(0, int(ev.get("tokens") or ev.get("tokens_saved") or 0))
    calls = max(0, int(ev.get("calls") or ev.get("calls_saved") or 0))
    calls_usd = max(0.0, float(ev.get("calls_usd") or ev.get("calls_cost_saved_usd") or 0.0))
    if tokens > 2_000_000:
        tokens = 0
    if str(ev.get("kind") or "") == "compaction":
        comp_usd = max(0.0, float(ev.get("usd") or 0.0))
        if tokens > 0 and comp_usd > 0:
            return tokens, comp_usd, calls, calls_usd, 0
        return 0, 0.0, calls, calls_usd, 0
    if tokens <= 0:
        return 0, 0.0, calls, calls_usd, 0
    # Prefer the cost the dispatcher pre-priced at write time; re-price only the
    # legacy rows that predate that field.
    stored = ev.get("cost_saved_usd")
    if stored is not None:
        return tokens, max(0.0, float(stored or 0.0)), calls, calls_usd, 0
    model_raw = str(ev.get("model") or "").strip()
    pricing = get_model_pricing(resolve_model_id(model_raw)) if model_raw else None
    if pricing is not None and pricing.known and pricing.input > 0:
        return tokens, pricing.input / 1_000_000 * tokens, calls, calls_usd, 0
    return 0, 0.0, calls, calls_usd, tokens


def _find_savings_sidecar(session_id: str, root: Path) -> Path:
    """Locate savings.jsonl for *session_id* under the canonical session dir.

    Host-agnostic: :func:`~atelier.core.foundation.paths.find_session_dir`
    globs by session id alone. When no directory exists yet (first write for
    a brand-new session), falls back to today's dir for the detected host so
    the caller's ``path.parent.mkdir(parents=True, exist_ok=True)`` creates
    the right tree.
    """
    from atelier.core.foundation.paths import detect_host, find_session_dir, session_dir

    existing = find_session_dir(root, session_id)
    if existing is not None:
        return existing / "savings.jsonl"
    return session_dir(root, detect_host(), session_id) / "savings.jsonl"


def _read_claude_session_savings(session_id: str, atelier_root: Path) -> tuple[int, int, float, int]:
    """Return ``(tokens_saved, calls_saved, usd_saved, unpriced_tokens)``.

    Every row is priced through :func:`_price_savings_row` — the shared rule the
    statusline, stop hook, CLI, dashboard, and web Savings page all use — so the
    per-session live total and the windowed totals never disagree.  Rows with no
    priceable model are returned via ``unpriced_tokens`` so the caller can apply
    a single weighted fallback rate without distorting the usd/token ratio.
    """
    if not session_id:
        return 0, 0, 0.0, 0
    path = _find_savings_sidecar(session_id, atelier_root)
    if not path.exists():
        return 0, 0, 0.0, 0

    priced_tokens = 0
    calls_total = 0
    usd_total = 0.0
    unpriced_tokens = 0
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            except Exception:
                logging.exception("Recovered from broad exception handler")
                continue
            pt, usd, c, calls_usd, up = _price_savings_row(ev)
            priced_tokens += pt
            usd_total += usd + calls_usd
            calls_total += c
            unpriced_tokens += up
    except OSError:
        pass
    return priced_tokens, calls_total, usd_total, unpriced_tokens


def _read_session_routing_usd(session_id: str, atelier_root: Path) -> float:
    """Sum model-routing savings from the per-session sidecar.

    The MCP server appends a ``kind == "routing"`` row (priced at decision time)
    to ``sessions/<id>/savings.jsonl`` for every routing saving. Kept separate
    from context savings so it drives the statusline's distinct routing line
    without inflating ``saved_usd`` — and read from the small per-session file
    rather than scanning the large ``live_savings_events.jsonl`` on every render.
    """
    if not session_id:
        return 0.0
    path = _find_savings_sidecar(session_id, atelier_root)
    if not path.exists():
        return 0.0
    total = 0.0
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if str(ev.get("kind") or "") == "routing":
                total += max(0.0, float(ev.get("usd") or 0.0))
    except OSError:
        pass
    return round(total, 6)


def _resolve_workspace_session_id(workspace: str | None, root_path: Path) -> str:
    """Read the active session_id from workspace/session_state.json.

    Used as fallback when the caller-supplied session_id has no savings
    (e.g. subagent sessions that don't have their own MCP sidecar).
    """
    if not workspace:
        return ""

    try:
        from atelier.core.foundation.paths import workspace_key

        ws_hash = workspace_key(Path(workspace).resolve())
        state_path = root_path / "workspaces" / ws_hash / "session_state.json"
        if not state_path.is_file():
            return ""
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return str(data.get("session_id") or "")
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return ""


def _carry_credit(
    session_id: str,
    atelier_root: Path,
    turn_timestamps: list[str],
    subagent_turn_timestamps: list[list[str]] | None = None,
) -> tuple[int, float]:
    """Context-carry credit for saved tokens, attributed per context window.

    A token kept out of context at turn N is also NOT re-read at the cache-read
    rate on every later assistant turn that re-sends that window. Each subagent
    runs in its *own* context window: a token a subagent saved carries across
    that subagent's own later turns only — the main thread never re-reads it
    (the subagent's context is discarded on return) and neither do sibling
    subagents (fresh contexts). So a savings row is credited against the turns
    of the window it was generated in: if its timestamp falls inside a
    subagent's lifetime it carries over that subagent's turns; otherwise over
    the main thread's turns (until the next compaction drops it).

    Subagent rows land in the *parent* session's savings.jsonl (the shared MCP
    process keys by the parent session id and cannot tell a subagent call from
    a main-loop call), so attribution is reconstructed here from the row
    timestamp and the per-subagent turn windows parsed from the transcript.

    Fully measured: row timestamps from the sidecar, turn timestamps from the
    transcript, rates from the per-row model. Rows with unknown models
    contribute nothing. Returned separately — never folded into saved_usd.
    """
    if not session_id:
        return 0, 0.0
    path = _find_savings_sidecar(session_id, atelier_root)
    if not path.exists():
        return 0, 0.0
    import bisect
    from datetime import datetime

    def _parse(ts: str) -> datetime | None:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt

    main_turns = sorted(t for t in (_parse(x) for x in turn_timestamps) if t is not None)

    # One (start, end, sorted_turns) window per subagent transcript, sorted
    # latest-start-first so an overlapping row (parallel subagents) is
    # attributed to the most-recently-spawned containing window — a
    # deterministic tiebreak.
    sub_windows: list[tuple[datetime, datetime, list[datetime]]] = []
    for sub in subagent_turn_timestamps or []:
        ts_list = sorted(t for t in (_parse(x) for x in sub) if t is not None)
        if ts_list:
            sub_windows.append((ts_list[0], ts_list[-1], ts_list))
    sub_windows.sort(key=lambda w: w[0], reverse=True)

    if not main_turns and not sub_windows:
        return 0, 0.0
    from atelier.core.capabilities.pricing import get_model_pricing

    carry_tokens = 0
    carry_usd = 0.0
    try:
        events: list[dict[str, Any]] = []
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict):
                events.append(ev)

        compactions = sorted(
            ts
            for ev in events
            if str(ev.get("kind") or "") == "compaction"
            if (ts := _parse(str(ev.get("ts") or ""))) is not None
        )
        for ev in events:
            if str(ev.get("kind") or "") == "compaction":
                continue  # dropped from context — nothing left to carry
            t = max(0, int(ev.get("tokens") or ev.get("tokens_saved") or 0))
            if t <= 0 or t > 2_000_000:
                continue
            row_dt = _parse(str(ev.get("ts") or ""))
            if row_dt is None:
                continue
            window = next((w for w in sub_windows if w[0] <= row_dt <= w[1]), None)
            if window is not None:
                # Subagent-saved token: carries across that subagent's own
                # later turns (the window bounds the count implicitly).
                sub_t = window[2]
                n_after = len(sub_t) - bisect.bisect_right(sub_t, row_dt)
            else:
                # Main-thread token: carries across later main turns, until the
                # next main-session compaction drops it from context.
                first_turn = bisect.bisect_right(main_turns, row_dt)
                next_compaction = bisect.bisect_right(compactions, row_dt)
                last_turn = (
                    bisect.bisect_left(main_turns, compactions[next_compaction])
                    if next_compaction < len(compactions)
                    else len(main_turns)
                )
                n_after = max(0, last_turn - first_turn)
            if n_after <= 0:
                continue
            pricing = get_model_pricing(resolve_model_id(str(ev.get("model") or "").strip()))
            if pricing is None or not pricing.known or pricing.cache_read <= 0:
                continue
            carry_tokens += t * n_after
            carry_usd += pricing.tokens_to_usd(t * n_after, "cache_read")
    except OSError:
        return 0, 0.0
    return carry_tokens, round(carry_usd, 6)


def _last_call_tokens_saved(session_id: str, root: Path) -> int:
    """Return the most recent per-call token saving from the session sidecar.

    Scans the last 40 rows of ``sessions/<id>/savings.jsonl`` in reverse and
    returns the first non-zero ``tokens`` value — the delta from the most
    recent tool call that saved something. Returns 0 when absent.
    """
    if not session_id:
        return 0
    path = _find_savings_sidecar(session_id, root)
    if not path.exists():
        return 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for raw in reversed(lines[-40:]):
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "session_end":
                continue
            t = int(row.get("tokens") or 0)
            if t > 0:
                return t
    except OSError:
        pass
    return 0


def compute_savings_summary(
    session_id: str = "",
    *,
    atelier_root: str | Path | None = None,
    workspace: str | None = None,
) -> SavingsSummary:
    """Aggregate savings for a session.

    Token savings come from ``sessions/<session_id>/savings.jsonl`` —
    the MCP dispatcher appends one row per tool call there (keyed by the
    Claude session UUID that SessionStart writes to session_state.json).

    If ``session_id`` has no savings and ``workspace`` is provided, falls back
    to the session_id stored in the workspace's session_state.json (for
    subagent scenarios where the subagent doesn't have its own sidecar).

    Cost baseline (``est_cost_usd``) still comes from the Claude transcript
    since Claude Code does preserve token-usage entries there.
    """
    result = SavingsSummary()
    # A missing live session id means Claude has not bound this statusline frame
    # to a concrete session yet. In that state we must not borrow savings from
    # the workspace's previous session, or brand-new sessions appear to start
    # with non-zero savings before the first prompt.
    if not session_id:
        return result
    root_path: Path
    if atelier_root is not None:
        root_path = Path(atelier_root)
    else:
        env_root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
        root_path = Path(env_root) if env_root else Path.home() / ".atelier"

    # --- savings rows (primary source) ---
    priced_tokens, calls, row_usd, unpriced_tokens = (
        _read_claude_session_savings(session_id, root_path) if session_id else (0, 0, 0.0, 0)
    )

    # Fallback: subagent sessions have no sidecar — look for parent session in transcript.
    # Discriminator: a *subagent* transcript has NO entries whose sessionId matches
    # the current session_id (all lines reference the parent session).  A main
    # session (post-compact, post-clear, fresh) has at least one own entry;
    # skipping those prevents borrowing stale savings from a prior session whose
    # sessionId happens to appear early in a resumed/compacted transcript.
    if priced_tokens == 0 and unpriced_tokens == 0 and calls == 0:
        # Extract parent session_id from subagent transcript if possible
        parent_id = None
        for cand in claude_transcript_candidates(session_id):
            try:
                candidate_parent: str | None = None
                has_own_entries = False
                with cand.open(encoding="utf-8") as f:
                    for line in f:
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        entry_sid = entry.get("sessionId")
                        if not entry_sid:
                            continue
                        if entry_sid == session_id:
                            # Found an entry owned by this session — it's a main
                            # session, not a subagent. Bail immediately.
                            has_own_entries = True
                            break
                        candidate_parent = entry_sid
                if not has_own_entries and candidate_parent:
                    parent_id = candidate_parent
                    break
            except Exception:
                logging.exception("Recovered from broad exception handler")
                continue

        if parent_id and parent_id != session_id:
            priced_tokens, calls, row_usd, unpriced_tokens = _read_claude_session_savings(parent_id, root_path)
            if priced_tokens > 0 or unpriced_tokens > 0 or calls > 0:
                session_id = parent_id  # use the found session for transcript lookup too

    result.smart_calls = calls
    # Per-session model-routing savings: a separate display line, read cheaply
    # from the sidecar (kind="routing" rows) and never folded into saved_usd.
    result.routing_saved_usd = _read_session_routing_usd(session_id, root_path)

    # --- cost baseline + model from transcript ---
    paths = claude_transcript_candidates(session_id) if session_id else []
    stats = read_transcript_stats(paths[0]) if paths else None
    if stats is not None:
        result.est_cost_usd = stats.est_cost_usd
        result.total_tokens = stats.total_tokens
        result.display_input_tokens = stats.input_tokens + stats.cache_write_tokens
        result.display_cache_tokens = stats.cache_read_tokens
        result.display_output_tokens = stats.output_tokens
    # --- context-carry credit (separate display line; never in saved_usd) ---
    if stats is not None and (stats.turn_timestamps or stats.subagent_turn_timestamps):
        result.carry_tokens, result.carry_usd = _carry_credit(
            session_id, root_path, stats.turn_timestamps, stats.subagent_turn_timestamps
        )

    # --- price unpriced tokens at the session's weighted input rate ---
    # Per-row prices are exact (model captured at write time).  For rows that
    # arrived without a model (older format, or before the SessionStart bridge
    # registered one), apply the transcript's weighted input rate so the user
    # sees a single, consistent (usd / tokens) ratio.  If we can't derive any
    # rate, those tokens are dropped from the display entirely — never count
    # something we can't price.
    extra_usd = 0.0
    extra_tokens = 0
    if unpriced_tokens > 0:
        rate: float | None = stats.savings_input_rate() if stats is not None else None
        if rate is None:
            try:
                from atelier.core.capabilities.pricing import get_model_pricing

                for mid in (stats.last_model if stats else "", "claude-sonnet-4-5"):
                    if not mid:
                        continue
                    pricing = get_model_pricing(resolve_model_id(mid))
                    if pricing is not None and pricing.known and pricing.input > 0:
                        rate = pricing.input / 1_000_000
                        break
            except Exception:
                logging.exception("Recovered from broad exception handler")
                rate = None
        if rate and rate > 0:
            extra_usd = rate * unpriced_tokens
            extra_tokens = unpriced_tokens

    result.ctx_saved = priced_tokens + extra_tokens
    result.saved_usd = row_usd + extra_usd

    # --- vs vanilla Claude Code (separate counterfactual; never in saved_usd) ---
    if paths:
        try:
            from atelier.core.capabilities.vanilla_baseline import replay_session

            vs = replay_session(paths[0])
            result.vs_vanilla_calls = int(vs.get("calls_saved", 0) or 0)
            result.vs_vanilla_usd = float(vs.get("cost_saved_usd", 0.0) or 0.0)
        except Exception:
            logging.exception("Recovered from broad exception handler")

    total_baseline = result.saved_usd + result.carry_usd + result.est_cost_usd
    if total_baseline > 0:
        result.saved_pct = (result.saved_usd / total_baseline) * 100
        result.carry_pct = (result.carry_usd / total_baseline) * 100

    # --- N4: per-tool exact in/out token ledger (additive surface) ---
    try:
        from atelier.core.capabilities.tool_token_ledger import load_tool_token_ledger

        ledger = load_tool_token_ledger(root_path)
        result.tool_token_ledger = {name: counts.to_dict() for name, counts in ledger.per_tool.items()}
        result.tool_ledger_input_tokens = ledger.total_input_tokens()
        result.tool_ledger_output_tokens = ledger.total_output_tokens()
    except Exception:
        logging.exception("Recovered from broad exception handler")

    return result


_STATUS_TIPS: tuple[str, ...] = (
    "`/atelier:explore` — investigate code read-only with a cheaper sub-model",
    "`/atelier:plan` — produce a concrete plan before coding; skip wrong-direction work",
    "`/atelier:review` — adversarial code review; finds what is wrong, not just what was done",
    "`/atelier:research` — fetch and synthesize web sources with full citations",
    "`/atelier:solve` — own a concrete task end-to-end autonomously",
    "`/atelier:execute` — apply an accepted plan with surgical, minimal edits",
    "`/atelier:auto` — autonomous runs; no plan gates, no prompts",
    "`/atelier:bare` — strips `Workflow` + `ScheduleWakeup`; saves ~6k tokens vs auto",
    "`/atelier:recall` — recall what Atelier learned from your past sessions",
    "`/atelier:settings` — change plugin settings in plain English",
    "`/atelier:ux-review` — verify implemented UI against design gates in a real browser",
    "`/atelier:perf-review` — verify a change's runtime perf against measured gates",
    "`/atelier:orchestrate` — choose subagent vs isolated execution for a single run",
    "`/atelier:swarms` — launch multi-worktree swarm runs",
    "`/atelier:benchmark` — benchmark Atelier vs vanilla Claude on your own repo",
)


def _status_tip() -> str:
    """A rotating feature tip (changes ~every 90s so it isn't flickery)."""
    return _STATUS_TIPS[int(time.time() // 90) % len(_STATUS_TIPS)]


def _colorize_tip(text: str, c_dim: str, c_tool: str, c_reset: str) -> str:
    """Highlight backtick-wrapped tool/command names; wrap the rest in dim.

    ``text`` is left unmodified when all color strings are empty (no-color mode).
    """
    colored = re.sub(
        r"`([^`]+)`",
        lambda m: f"{c_reset}{c_tool}{m.group(1)}{c_reset}{c_dim}",
        text,
    )
    return f"{c_dim}{colored}{c_reset}"


def _resolve_status_text(atelier_root: str | Path | None = None) -> str:
    """Return update / login / subscription warning text for the statusline.

    Falls back to a rotating feature tip (when ``statusLineTips`` is enabled)
    so the lowest-priority slot coaches the user toward Atelier features.
    """
    root = Path(atelier_root) if atelier_root else None
    if root is None:
        root_env = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or ""
        root = Path(root_env) if root_env else None
    if root is None:
        return ""

    def _read(name: str) -> dict[str, Any]:
        p = root / name
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return {}

    auth = _read("auth.json")
    if ((not auth) or auth.get("authenticated") is False) and os.environ.get("ATELIER_HIDE_MISSING_LOGIN") != "1":
        return "login"
    update = _read("update.json")
    if update.get("toVersion") and update.get("toVersion") != update.get("fromVersion"):
        return f"update {update.get('toVersion')}"
    subscription = _read("subscription.json")
    if subscription.get("warning"):
        return str(subscription.get("message") or "subscription")[:40]
    # Lowest priority: a rotating feature tip, when statusLineTips is enabled.
    raw = _read("plugin_settings.json")
    nested = raw.get("atelier")
    settings = nested if isinstance(nested, dict) else raw
    if settings.get("statusLineTips", True) is not False:
        return _status_tip()
    return ""


def _fmt_tok(n: int) -> str:
    """Format token count: <1k literal, <1M as Nk, >=1M as N.NM."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n // 1000}k"
    return str(n)


def load_usage_breakdown(root: str | Path) -> dict[str, Any]:
    """Aggregate project-wide token usage and cost from atelier.db."""
    root_path = Path(root)
    db_path = root_path / "atelier.db"
    if not db_path.exists():
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_usd": 0.0,
            "breakdown": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
        }

    from atelier.core.capabilities.pricing import usage_cost_breakdown_usd, usage_cost_usd

    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    total_cost = 0.0
    breakdown = {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}

    try:
        from atelier.core.foundation.store import ContextStore

        # Token/model rows come straight from atelier.db's traces table (see
        # ContextStore.token_rows) -- json_extract on the payload, not a full
        # Trace parse per row.
        for row in ContextStore(root_path).token_rows():
            inp = int(row["input_tokens"] or 0)
            out = int(row["output_tokens"] or 0)
            cr = int(row["cached_input_tokens"] or 0)
            model_id = resolve_model_id(row["model"]) or "claude-sonnet-4-5"

            input_tokens += inp
            output_tokens += out
            cache_read_tokens += cr

            total_cost += usage_cost_usd(model_id, input_tokens=inp, output_tokens=out, cache_read_tokens=cr)
            b = usage_cost_breakdown_usd(model_id, input_tokens=inp, output_tokens=out, cache_read_tokens=cr)
            breakdown["input"] += b["input"]
            breakdown["output"] += b["output"]
            breakdown["cache_read"] += b["cache_read"]
            breakdown["cache_write"] += b["cache_write"]

    except Exception:
        logging.exception("Failed to load usage breakdown from DB")

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cost_usd": round(total_cost, 6),
        "breakdown": {k: round(v, 6) for k, v in breakdown.items()},
    }


def savings_line(
    session_id: str = "",
    *,
    atelier_root: str | Path | None = None,
    workspace: str | None = None,
) -> str:
    """Return the pipe-delimited savings line consumed by statusline.sh.

    Format:
    ``$<saved_usd>|<tokens_saved>|<calls_saved>|<status_text>|$<routing_saved_usd>|<est_cost_usd>|<total_tokens>|<display_input_tokens>|<display_cache_tokens>|<display_output_tokens>|$<carry_usd>|<carry_tokens>|<carry_pct>%|<saved_pct>%|<vs_vanilla_calls>|$<vs_vanilla_usd>``

    The two trailing fields are the comparative "vs vanilla Claude Code" replay
    (roundtrips avoided and their estimated full-context-resend cost). They are
    separate from the measured savings and are appended last so statusline.sh's
    positional parsing of the existing fields stays byte-identical.
    """
    summary = compute_savings_summary(session_id, atelier_root=atelier_root, workspace=workspace)
    summary.status_text = _resolve_status_text(atelier_root)
    return (
        f"${summary.saved_usd:.3f}|{_fmt_tok(summary.ctx_saved)}|{summary.smart_calls}"
        f"|{summary.status_text}|${summary.routing_saved_usd:.3f}"
        f"|{summary.est_cost_usd:.3f}|{summary.total_tokens}"
        f"|{summary.display_input_tokens}|{summary.display_cache_tokens}|{summary.display_output_tokens}"
        f"|${summary.carry_usd:.3f}|{_fmt_tok(summary.carry_tokens)}|{summary.carry_pct:.0f}%"
        f"|{summary.saved_pct:.0f}%"
        f"|{summary.vs_vanilla_calls}|${summary.vs_vanilla_usd:.3f}"
    )


# ---------------------------------------------------------------------------
# Rotating statusline segment  (replaces the multi-field --line parse in bash)
# ---------------------------------------------------------------------------

_SEGMENT_INTERVAL_S: int = 5  # seconds before advancing to the next frame


# Spend cache freshness: an active session's transcript changes every turn, so
# re-pricing it on every statusline render would be wasteful. Reuse cached
# per-turn costs for this long even when the transcript mtime moved.
_SPEND_CACHE_TTL_S = 60.0

# In-memory TTL cache for _read_historical_savings and _first_savings_ts:
# the statusline refreshes every ~5s but savings data only changes when a
# new tool call completes. Cache keyed on root_str (and days for the
# historical cache); entries expire after this many seconds.
_HISTORICAL_SAVINGS_CACHE_TTL_S: float = 60.0
_historical_savings_cache: dict[tuple[int, str], tuple[float, tuple[float, int, int, int, float, float]]] = {}
_first_savings_ts_cache: dict[str, tuple[float, float]] = {}  # root_str → (cached_at, result)


def _transcript_turn_costs(transcript_path: str | Path) -> list[tuple[float, float]]:
    """Per-assistant-turn ``(epoch_ts, cost_usd)`` for a transcript + subagents.

    Summing the costs reconciles with :func:`read_transcript_stats`'s
    ``est_cost_usd`` (same per-turn, per-model pricing incl. the long-context
    premium); the timestamps let callers window spend the *same* per-turn way
    savings rows are windowed, instead of attributing a whole session's cost at
    its end. Usage is de-duplicated by message id across the main and subagent
    transcripts, matching the stats parser.
    """
    from datetime import datetime

    p = Path(transcript_path)
    if not p.exists():
        return []
    sources: list[Path] = [p, *_subagent_transcripts(p)]
    seen_ids: set[str] = set()
    lc_thresholds: dict[str, int] = {}
    out: list[tuple[float, float]] = []
    for source in sources:
        try:
            lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            msg = entry.get("message") or {}
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage") or {}
            if not isinstance(usage, dict):
                continue
            in_t = int(usage.get("input_tokens", 0) or 0)
            out_t = int(usage.get("output_tokens", 0) or 0)
            cr_t = int(usage.get("cache_read_input_tokens", 0) or 0)
            cw_t = int(usage.get("cache_creation_input_tokens", 0) or 0)
            if not (in_t or out_t or cr_t or cw_t):
                continue
            msg_id = str(msg.get("id") or "").strip()
            if msg_id:
                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)
            try:
                dt = datetime.fromisoformat(str(entry.get("timestamp") or "").replace("Z", "+00:00"))
                ts_epoch = (dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt).timestamp()
            except (ValueError, TypeError, OSError, OverflowError):
                continue
            model = str(msg.get("model") or entry.get("model") or "").strip()
            cache_creation = usage.get("cache_creation") or {}
            cw1_t = (
                int(cache_creation.get("ephemeral_1h_input_tokens", 0) or 0) if isinstance(cache_creation, dict) else 0
            )
            cw1_t = min(cw1_t, cw_t)
            threshold = _long_context_threshold(model, lc_thresholds) if model else 0
            long_ctx = bool(threshold and (in_t + cr_t + cw_t) > threshold)
            cost = estimate_cost_usd(
                model_id=resolve_model_id(model),
                input_tokens=in_t,
                output_tokens=out_t,
                cache_read_tokens=cr_t,
                cache_write_tokens=cw_t - cw1_t,
                cache_write_1h_tokens=cw1_t,
                long_context=long_ctx,
            )
            out.append((ts_epoch, cost))
    return out


def _session_windowed_spend(session_id: str, root: Path, cutoff: float) -> float | None:
    """Actual spend for *session_id*'s turns at/after *cutoff*, from the transcript.

    Windows spend the same per-turn way savings rows are windowed, so a session
    that ran across several days contributes only its in-window turns to each
    window (fixing the "7d spend == 1d spend" artifact of end-of-session
    attribution). Per-turn ``(ts, cost)`` pairs are cached in
    ``sessions/<id>/spend_cache.json`` keyed on transcript mtime (short TTL for
    the still-growing active session) so the statusline does not re-parse the
    transcript every render. Returns ``None`` when no transcript exists so the
    caller can fall back to ``session_end`` rows.
    """
    if not session_id:
        return None
    candidates = claude_transcript_candidates(session_id)
    if not candidates:
        return None
    transcript = candidates[0]
    try:
        mtime = transcript.stat().st_mtime
    except OSError:
        return None
    now = time.time()
    cache_path = _find_savings_sidecar(session_id, root).with_name("spend_cache.json")
    turns: list[Any] | None = None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            isinstance(cached, dict)
            and isinstance(cached.get("turns"), list)
            and (
                cached.get("transcript_mtime") == mtime
                or (now - float(cached.get("computed_at") or 0)) < _SPEND_CACHE_TTL_S
            )
        ):
            turns = cached["turns"]
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        turns = None
    if turns is None:
        turns = [[ts, cost] for ts, cost in _transcript_turn_costs(transcript)]
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"transcript_mtime": mtime, "computed_at": now, "turns": turns}),
                encoding="utf-8",
            )
        except OSError:
            pass
    total = 0.0
    for item in turns:
        try:
            ts, cost = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if ts >= cutoff:
            total += cost
    return total


def _invalidate_historical_savings_cache() -> None:
    """Clear the in-memory savings cache so the next statusline read picks up new rows."""
    _historical_savings_cache.clear()


def _read_historical_savings(
    days: int, root: Path
) -> tuple[float, int, int, int, float, float]:  # (usd, tok, calls, turns, spend, carry)
    """Sum windowed savings (tokens, calls, usd) and actual spend from sessions/**/savings.jsonl.

    Savings are summed per row (priced via :func:`_price_savings_row`, filtered
    by row ts). Spend is the session's actual cost: a ``kind=="session_end"`` row
    when the stop hook recorded one (finished sessions), otherwise back-filled
    from the Claude transcript's est_cost (cached, see :func:`_session_windowed_spend`)
    so a window still reflects the spend of sessions that ran before session_end
    tracking existed — keeping 7d/30d spend from collapsing to the stop hook's
    ~1 day of coverage.

    Uses file mtime as a cheap pre-filter so we skip files entirely outside the
    window before reading a byte. Results are cached in-process for
    ``_HISTORICAL_SAVINGS_CACHE_TTL_S`` seconds; invalidated on every savings write.

    Returns (savings_usd, tokens_saved, calls_saved, turns_saved, spend_usd, carry_usd).
    """
    sessions_dir = root / "sessions"
    if not sessions_dir.exists():
        return 0.0, 0, 0, 0, 0.0, 0.0
    # In-memory TTL cache: skip the full scan when the statusline polls frequently.
    _cache_key = (days, str(root))
    _now = time.time()
    _cached = _historical_savings_cache.get(_cache_key)
    if _cached is not None:
        _cached_ts, _cached_val = _cached
        if _now - _cached_ts < _HISTORICAL_SAVINGS_CACHE_TTL_S:
            return _cached_val  # type: ignore[return-value]
    cutoff = _now - days * 86_400
    total_usd = 0.0
    total_tok = 0
    total_calls = 0
    total_turns = 0
    total_spend = 0.0
    total_carry = 0.0
    try:
        from datetime import datetime

        def _epoch(ts_str: str) -> float | None:
            try:
                # Rows are stamped naive-UTC (datetime.utcnow); pin the zone so
                # the epoch matches time.time() exactly.
                return datetime.fromisoformat(ts_str).replace(tzinfo=UTC).timestamp()
            except (ValueError, TypeError, OSError, OverflowError):
                return None

        for p in sessions_dir.glob("**/savings.jsonl"):
            # Fast path: skip files not touched since before the window.
            try:
                if p.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            session_end_window = 0.0
            session_carry_window = 0.0
            try:
                with p.open(encoding="utf-8") as fh:
                    for raw in fh:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            row = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        ts = _epoch(str(row.get("ts", "")))
                        if ts is None:
                            continue
                        # session_end carries the whole-session cost at end time;
                        # used only as a fallback when the transcript is gone.
                        if row.get("kind") == "session_end":
                            if ts >= cutoff:
                                session_end_window += float(row.get("est_cost_usd") or 0)
                                session_carry_window += float(row.get("carry_usd") or 0)
                            continue
                        if ts < cutoff:
                            continue
                        # Price every row through the shared rule so the windowed
                        # 7d/30d totals reconcile exactly with the live
                        # per-session statusline/stop-hook figure.
                        pt, row_usd, row_calls, row_calls_usd, up = _price_savings_row(row)
                        row_usd += row_calls_usd
                        row_tok = pt + up
                        total_usd += row_usd
                        total_tok += row_tok
                        total_calls += row_calls
                        if row_usd > 0 or row_tok > 0:
                            total_turns += 1
            except OSError:
                continue
            # Skip the transcript glob for finished sessions: session_end carries the
            # accurate whole-session cost; _session_windowed_spend's transcript scan
            # is only needed for still-active sessions (no session_end row yet).
            if session_end_window > 0:
                total_spend += session_end_window
                total_carry += session_carry_window
            else:
                windowed_spend = _session_windowed_spend(p.parent.name, root, cutoff)
                total_spend += windowed_spend if windowed_spend is not None else 0.0
                total_carry += session_carry_window
    except Exception:
        logging.exception("Recovered reading historical savings")
    _result = (total_usd, total_tok, total_calls, total_turns, total_spend, total_carry)
    _historical_savings_cache[_cache_key] = (_now, _result)
    return _result


@dataclass
class WindowSavings:
    """Realized savings over a trailing window, from ``sessions/*/savings.jsonl``."""

    saved_usd: float = 0.0
    tokens_saved: int = 0
    calls_saved: int = 0
    turns: int = 0
    spend_usd: float = 0.0
    carry_usd: float = 0.0

    @property
    def would_have_cost_usd(self) -> float:
        """What the window would have cost without the realized savings."""
        return self.saved_usd + self.spend_usd

    @property
    def saved_pct(self) -> float:
        """Realized savings as a share of the would-have-cost baseline."""
        whc = self.would_have_cost_usd
        return round(100.0 * self.saved_usd / whc, 2) if whc > 0 else 0.0


def aggregate_window_savings(root: str | Path, *, days: int) -> WindowSavings:
    """Realized savings over the last *days* from the canonical per-session ledger.

    Single source of truth for every windowed savings surface (CLI breakdown,
    web Savings page, dashboard).  Built from ``sessions/*/savings.jsonl`` and
    priced with :func:`_price_savings_row`, so it always reconciles with the
    statusline/stop-hook live total.
    """
    usd, tok, calls, turns, spend, carry = _read_historical_savings(int(days), Path(root))
    return WindowSavings(
        saved_usd=round(usd, 6),
        tokens_saved=int(tok),
        calls_saved=int(calls),
        turns=int(turns),
        spend_usd=round(spend, 6),
        carry_usd=round(carry, 6),
    )


def _first_savings_ts(root: Path) -> float:
    """Return the mtime of the oldest per-session savings file, or 0.0 if none exist.

    Result is cached in-process for _HISTORICAL_SAVINGS_CACHE_TTL_S seconds; the
    oldest session only gets older over time so staleness is harmless.
    """
    _root_str = str(root)
    _now = time.time()
    _entry = _first_savings_ts_cache.get(_root_str)
    if _entry is not None:
        _cached_at, _cached_result = _entry
        if _now - _cached_at < _HISTORICAL_SAVINGS_CACHE_TTL_S:
            return _cached_result
    sessions_dir = root / "sessions"
    if not sessions_dir.exists():
        return 0.0
    earliest = 0.0
    try:
        for p in sessions_dir.glob("**/savings.jsonl"):
            try:
                mt = p.stat().st_mtime
                if earliest == 0.0 or mt < earliest:
                    earliest = mt
            except OSError:
                continue
    except Exception:
        logging.exception("Recovered reading first-savings ts")
    _first_savings_ts_cache[_root_str] = (_now, earliest)
    return earliest


def _read_review_verdict(session_id: str, root: Path) -> str:
    """Return 'NEEDS_FIX' when an unconsumed review verdict exists, else ''."""
    review_log = root / "reviews" / f"{session_id}.jsonl"
    if not review_log.exists():
        return ""
    try:
        with review_log.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and not row.get("consumed") and row.get("verdict") == "NEEDS_FIX":
                    return "NEEDS_FIX"
    except OSError:
        pass
    return ""


def _get_frame_index(state_path: Path, num_frames: int) -> int:
    """Return the current frame index, advancing the rolling counter every _SEGMENT_INTERVAL_S."""
    counter = 0
    last_ts = 0.0
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            counter = int(state.get("counter", 0))
            last_ts = float(state.get("ts", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    now = time.time()
    if now - last_ts >= _SEGMENT_INTERVAL_S:
        counter += 1
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"counter": counter, "ts": now}), encoding="utf-8")
        except OSError:
            pass
    return counter % max(1, num_frames)


def savings_segment(
    session_id: str = "",
    *,
    atelier_root: str | Path | None = None,
    live_cost_usd: float = 0.0,
    live_in_tok: int = 0,
    live_cache_tok: int = 0,
    live_out_tok: int = 0,
    no_color: bool = False,
) -> str:
    """Return a pre-formatted, pre-colored rotating statusline segment.

    Reads frame state from ``<root>/statusline_frame_state.json``, advances the
    frame every ``_SEGMENT_INTERVAL_S`` seconds, and returns the current frame's
    content.  Callers just print what they receive — all formatting lives here.

    Frames (non-empty only):
      0  live cost + I/C/O token breakdown
      1  session savings + % saved
      2  carry credit (♻) and/or routing savings
      3  vs vanilla Claude Code roundtrips
      4  7-day historical savings
      5  30-day historical savings
      6  status tip / update notice

    The review:NEEDS_FIX alert is appended to every frame (not rotated away).
    """
    env_root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or ""
    root: Path
    if atelier_root is not None:
        root = Path(atelier_root)
    elif env_root:
        root = Path(env_root)
    else:
        root = Path.home() / ".atelier"

    # ANSI palette (mirrors statusline.sh)
    if no_color:
        C_BRAND = C_DIM = C_GREEN = C_COST = C_RED = C_RESET = ""
    else:
        C_BRAND = "\033[1;38;2;168;85;247m"  # purple  — carry / ♻
        C_DIM = "\033[2;38;2;200;200;200m"  # dim grey — separators, tips
        C_GREEN = "\033[1;38;2;72;199;116m"  # green   — savings / ↓
        C_COST = "\033[38;2;255;180;70m"  # amber   — cost / ↑
        C_RED = "\033[1;38;2;255;99;71m"  # red     — NEEDS_FIX
        C_RESET = "\033[0m"
    # Dim / used between label-value pairs on text-only frames.
    SEP = f"{C_DIM}|{C_RESET}"

    summary = compute_savings_summary(session_id, atelier_root=root)
    summary.status_text = _resolve_status_text(root)

    # Prefer transcript-derived cumulative I/C/O when available.
    if summary.display_input_tokens > 0 or summary.display_cache_tokens > 0 or summary.display_output_tokens > 0:
        eff_in = summary.display_input_tokens
        eff_cache = summary.display_cache_tokens
        eff_out = summary.display_output_tokens
    else:
        eff_in = live_in_tok
        eff_cache = live_cache_tok
        eff_out = live_out_tok

    has_usage = eff_in > 0 or eff_cache > 0

    # Cost: use transcript-derived value — it resets correctly on /clear (new session_id)
    # and matches our corrected pricing rates. live_cost_usd (Claude's payload) is
    # already baseline-subtracted by statusline.sh but can lag on the first render.
    display_cost = summary.est_cost_usd if summary.est_cost_usd > 0 else live_cost_usd

    # Historical savings (scanned once per segment call — fast file scan).
    usd_1d, tok_1d, calls_1d, _turns_1d, spend_1d, carry_1d = _read_historical_savings(1, root)
    usd_7d, tok_7d, calls_7d, _turns_7d, spend_7d, carry_7d = _read_historical_savings(7, root)
    usd_30d, tok_30d, calls_30d, _turns_30d, spend_30d, carry_30d = _read_historical_savings(30, root)
    first_ts = _first_savings_ts(root)
    days_active = (time.time() - first_ts) / 86_400 if first_ts > 0 else 0.0

    # --- Build frames as (has_icon, content) tuples.
    # has_icon=True  → ↑/↓/♻ leads the frame; no separator needed before it.
    # has_icon=False → plain text; SEP is prepended so it doesn't abut ctx% directly.
    frames: list[tuple[bool, str]] = []

    # Frame 0: $cost(I C O) ↓ $saved(cumulative+last_delta) ♻ $carry(tok·%)
    # Mirrors the pre-rotation "always visible" single-line format.
    in_f, cache_f, out_f = _fmt_tok(eff_in), _fmt_tok(eff_cache), _fmt_tok(eff_out)
    last_delta = _last_call_tokens_saved(session_id, root) if session_id else 0
    delta_str = f"+{last_delta}" if last_delta > 0 else ""
    combined = f"{C_COST}${display_cost:.3f}{C_DIM}(I:{in_f} C:{cache_f} O:{out_f}){C_RESET}"
    if has_usage:
        combined += f" {C_GREEN}↓ ${summary.saved_usd:.3f}{C_DIM}({_fmt_tok(summary.ctx_saved)}{delta_str}){C_RESET}"
    if summary.routing_saved_usd > 0:
        combined += f" {C_DIM}routing:{C_RESET} {C_GREEN}${summary.routing_saved_usd:.3f}{C_RESET}"
    if summary.carry_usd >= 0.001:
        carry_detail = _fmt_tok(summary.carry_tokens)
        if summary.carry_pct >= 1:
            carry_detail += f" · {summary.carry_pct:.0f}%"
        combined += f" {C_BRAND}♻ ${summary.carry_usd:.3f}{C_DIM}({carry_detail}){C_RESET}"
    frames.append((True, combined))

    def _hist_frame(label: str, usd: float, tok: int, calls: int, spend: float, carry: float) -> str:
        """Format: label: ↑ $spent ↓ $saved · NM less tokens · N fewer calls"""
        dot = f" {C_DIM}·{C_RESET} "
        # ↑ cost and ↓ saved share no separator — the icons are the visual break.
        money: list[str] = []
        if spend > 0:
            money.append(f"{C_COST}↑ ${spend:.2f}{C_RESET}")
        combined = usd + carry
        if combined > 0:
            money.append(f"{C_GREEN}↓ ${combined:.2f}{C_RESET}")
        detail: list[str] = []
        if tok > 0:
            detail.append(f"{C_DIM}{_fmt_tok(tok)} less tokens{C_RESET}")
        if calls > 0:
            detail.append(f"{C_DIM}{_fmt_tok(calls)} fewer calls{C_RESET}")
        body = " ".join(money)
        if detail:
            body += dot + dot.join(detail)
        return f"{C_DIM}{label}{C_RESET} {body}"

    # Frame 2: 1-day window — spent · saved · tokens less · calls fewer
    if usd_1d > 0 or carry_1d > 0 or spend_1d > 0:
        frames.append((False, _hist_frame("1d:", usd_1d, tok_1d, calls_1d, spend_1d, carry_1d)))

    # Frame 3: 7-day window — only after ≥1 day of usage.
    if (usd_7d > 0 or carry_7d > 0 or spend_7d > 0) and days_active >= 1:
        frames.append((False, _hist_frame("7d:", usd_7d, tok_7d, calls_7d, spend_7d, carry_7d)))

    # Frame 4: 30-day window — only after ≥7 days of usage.
    if (usd_30d > 0 or carry_30d > 0 or spend_30d > 0) and days_active >= 7:
        frames.append((False, _hist_frame("30d:", usd_30d, tok_30d, calls_30d, spend_30d, carry_30d)))

    # Frame 6: status tip / update notice (text-only)
    # Backtick-wrapped tool names are highlighted in brand purple; rest is dim.
    if summary.status_text:
        frames.append((False, _colorize_tip(summary.status_text, C_DIM, C_BRAND, C_RESET)))

    # Advance the rolling counter and select current frame.
    # Frame 0 (cost+savings+carry) gets 6 slots at 5s each = ~30s; others get 5s each.
    weighted = [frames[0]] * 6 + frames[1:] if frames else frames
    state_path = root / "statusline_frame_state.json"
    idx = _get_frame_index(state_path, len(weighted))
    has_icon, segment = weighted[idx]

    # Review verdict: pinned — appended to every frame, never rotated away.
    if session_id:
        verdict = _read_review_verdict(session_id, root)
        if verdict == "NEEDS_FIX":
            segment += f" {SEP} {C_RED}review: NEEDS_FIX{C_RESET}"

    # Icon-led frames (↑ ↓ ♻) are their own visual separator.
    # Text-only frames get SEP prepended so they don't abut ctx% directly.
    return f" {segment}" if has_icon else f" {SEP} {segment}"
