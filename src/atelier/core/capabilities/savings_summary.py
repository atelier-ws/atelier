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
    "opus 4.7": "claude-opus-4-7",
    "opus 4.6": "claude-opus-4-6",
    "opus 4.5": "claude-opus-4-5",
    "opus 4.1": "claude-opus-4-1",
    "opus 4": "claude-opus-4-0",
    "sonnet 4.7": "claude-sonnet-4-7",
    "sonnet 4.6": "claude-sonnet-4-6",
    "sonnet 4.5": "claude-sonnet-4-5",
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

    Falls back to Sonnet 4.5 rates when the model is unknown so we never
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


def read_transcript_stats(transcript_path: str | Path) -> TranscriptStats | None:
    """Parse a Claude transcript JSONL and return session stats.

    Cost is computed per model per turn because users can switch models
    mid-conversation (e.g. Opus → Sonnet).  Each token bucket is priced with
    its own rate card and summed.

    Token buckets and cost also include the session's subagent transcripts
    (``<session-id>/subagents/*.jsonl``) — their usage is billed to the
    session. Turn count, tool counts, and the session model fields remain
    main-transcript-only.
    """
    p = Path(transcript_path)
    if not p.exists():
        return None

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
    seen_usage_message_ids: set[str] = set()
    seen_tool_use_ids: set[str] = set()
    lc_thresholds: dict[str, int] = {}

    sources: list[tuple[Path, bool]] = [(p, True)]
    sources.extend((sub, False) for sub in _subagent_transcripts(p))

    try:
        for source, is_main in sources:
            for raw in source.read_text(encoding="utf-8", errors="replace").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
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
                    if is_main:
                        # A turn = one assistant message with non-zero usage.
                        # Dedup on msg_id (same dedup as token accumulation).
                        turns += 1
                        ts_raw = str(entry.get("timestamp") or "")
                        if ts_raw:
                            turn_timestamps.append(ts_raw)

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

    return TranscriptStats(
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
    )


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
    # Comparative "vs vanilla Claude Code" replay (roundtrips vanilla CC would
    # have spent that Atelier avoided, priced at full-context resend). This is a
    # SEPARATE counterfactual estimate and is intentionally NOT added into
    # saved_usd or any measured-savings field.
    vs_vanilla_calls: int = 0
    vs_vanilla_usd: float = 0.0


def _read_claude_session_savings(session_id: str, atelier_root: Path) -> tuple[int, int, float, int]:
    """Return ``(tokens_saved, calls_saved, usd_saved, unpriced_tokens)``.

    Each row is priced at the model stored in the row (set by the MCP server
    at write time).  Rows we can price contribute to both ``tokens_saved`` and
    ``usd_saved``.  Rows we cannot price (missing or unknown model, or no
    pricing entry) are returned separately via ``unpriced_tokens`` so the
    caller can apply a single weighted fallback rate without distorting the
    displayed (usd / tokens) ratio.
    """
    if not session_id:
        return 0, 0, 0.0, 0
    path = atelier_root / "session_stats" / "claude" / f"{session_id}.jsonl"
    if not path.exists():
        return 0, 0, 0.0, 0
    from atelier.core.capabilities.pricing import get_model_pricing

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
            except Exception:
                logging.exception("Recovered from broad exception handler")
                continue
            # Field names mirror the in-response `saved: {tokens, calls}` shape.
            # Older rows (briefly written as tokens_saved/calls_saved) are still
            # accepted as a fallback so historical sidecars keep working.
            t = max(0, int(ev.get("tokens") or ev.get("tokens_saved") or 0))
            c = max(0, int(ev.get("calls") or ev.get("calls_saved") or 0))
            calls_total += c
            # Avoided-call credit priced at write time (measured context size
            # x cache-read rate); contributes USD without distorting tokens.
            calls_usd = float(ev.get("calls_usd") or 0.0)
            if calls_usd > 0:
                usd_total += calls_usd
            if t <= 0:
                continue
            # Sanity cap: a single tool call cannot save more than the full
            # Anthropic context window (~1M tokens). Anything larger came from
            # a pre-fce2110 inflation bug in native_search.py and must not be
            # shown to the user — silently drop the row.
            if t > 2_000_000:
                continue
            # Compaction-credit rows carry a pre-computed USD value priced at the
            # cache-read rate (the per-turn cost of the context that compaction
            # dropped). Add it directly — never re-price at the input rate, which
            # would over-credit ~10x. Tokens still count toward ctx_saved.
            if str(ev.get("kind") or "") == "compaction":
                comp_usd = float(ev.get("usd") or 0.0)
                if comp_usd > 0:
                    priced_tokens += t
                    usd_total += comp_usd
                continue
            model_raw = str(ev.get("model") or "").strip()
            pricing = get_model_pricing(resolve_model_id(model_raw)) if model_raw else None
            if pricing is not None and pricing.known and pricing.input > 0:
                priced_tokens += t
                usd_total += pricing.input / 1_000_000 * t
            else:
                unpriced_tokens += t
    except OSError:
        pass
    return priced_tokens, calls_total, usd_total, unpriced_tokens


def _resolve_workspace_session_id(workspace: str | None, root_path: Path) -> str:
    """Read the active session_id from workspace/session_state.json.

    Used as fallback when the caller-supplied session_id has no savings
    (e.g. subagent sessions that don't have their own MCP sidecar).
    """
    if not workspace:
        return ""
    import hashlib as _hl

    try:
        ws_hash = _hl.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
        state_path = root_path / "workspaces" / ws_hash / "session_state.json"
        if not state_path.is_file():
            return ""
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return str(data.get("session_id") or "")
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return ""


def _carry_credit(session_id: str, atelier_root: Path, turn_timestamps: list[str]) -> tuple[int, float]:
    """Context-carry credit for saved tokens.

    A token kept out of context at turn N is also NOT re-read at the
    cache-read rate on every later assistant turn. Fully measured: row
    timestamps from the sidecar, turn timestamps from the transcript, rates
    from the per-row model. Rows with unknown models contribute nothing.
    Returned separately — never folded into the conservative saved_usd.
    """
    if not session_id or not turn_timestamps:
        return 0, 0.0
    path = atelier_root / "session_stats" / "claude" / f"{session_id}.jsonl"
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

    turns = sorted(t for t in (_parse(x) for x in turn_timestamps) if t is not None)
    if not turns:
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
            first_turn = bisect.bisect_right(turns, row_dt)
            next_compaction = bisect.bisect_right(compactions, row_dt)
            last_turn = (
                bisect.bisect_left(turns, compactions[next_compaction])
                if next_compaction < len(compactions)
                else len(turns)
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


def compute_savings_summary(
    session_id: str = "",
    *,
    atelier_root: str | Path | None = None,
    workspace: str | None = None,
) -> SavingsSummary:
    """Aggregate savings for a session.

    Token savings come from ``session_stats/claude/<session_id>.jsonl`` —
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
                        entry = json.loads(line)
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
    if stats is not None and stats.turn_timestamps:
        result.carry_tokens, result.carry_usd = _carry_credit(session_id, root_path, stats.turn_timestamps)

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

    return result


def _resolve_status_text(atelier_root: str | Path | None = None) -> str:
    """Return update / login / subscription warning text for the statusline."""
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
        import sqlite3

        with sqlite3.connect(str(db_path)) as conn:
            # traces table
            for row in conn.execute(
                "SELECT json_extract(payload, '$.input_tokens'), json_extract(payload, '$.output_tokens'), "
                "json_extract(payload, '$.cached_input_tokens'), json_extract(payload, '$.thinking_tokens'), host, "
                "json_extract(payload, '$.model') FROM traces"
            ):
                inp, out, cr, _th, _host, model = row
                inp = int(inp or 0)
                out = int(out or 0)
                cr = int(cr or 0)
                model_id = resolve_model_id(model) or "claude-sonnet-4-5"

                input_tokens += inp
                output_tokens += out
                cache_read_tokens += cr

                total_cost += usage_cost_usd(model_id, input_tokens=inp, output_tokens=out, cache_read_tokens=cr)
                b = usage_cost_breakdown_usd(model_id, input_tokens=inp, output_tokens=out, cache_read_tokens=cr)
                breakdown["input"] += b["input"]
                breakdown["output"] += b["output"]
                breakdown["cache_read"] += b["cache_read"]
                breakdown["cache_write"] += b["cache_write"]

            # context_budget table (aggregates for sessions)
            for row in conn.execute(
                "SELECT SUM(input_tokens), SUM(output_tokens), SUM(cache_read_tokens) FROM context_budget"
            ):
                inp, out, cr = row
                if inp is None:
                    continue
                # Note: context_budget doesn't store model, so we use Sonnet 4.5 as proxy for these aggregates
                # if they weren't already captured in traces (usually they are).
                # To avoid double counting, we'd need to link them, but context_budget is often
                # a redundant high-level log. Dashboard uses it as a fallback.
                pass

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
