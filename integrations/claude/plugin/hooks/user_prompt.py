#!/usr/bin/env python3
"""UserPromptSubmit hook — capture user prompts into the RunLedger.

Fires each time the user submits a message.  Records the prompt text as an
``agent_message`` event (kind chosen for visibility in the timeline) so the
full conversation context is preserved in the ledger.

Prompt text is truncated to 8 KB to cap ledger file size while keeping full
context for normal prompts.

Fail-open: any error exits silently (code 0) — never blocks the agent.

Payload received on stdin:
  {
    "session_id": "abc123",
    "transcript_path": "...",
    "cwd": "...",
    "permission_mode": "default",
    "hook_event_name": "UserPromptSubmit",
    "prompt": "Write a function to calculate factorial"
  }
"""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PROMPT_BYTES = 8192  # 8 KB


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _session_state_path() -> Path:
    import hashlib

    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    root = Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")
    return root / "workspaces" / h / "session_state.json"


def _read_session_state() -> dict:  # type: ignore[type-arg]
    p = _session_state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))  # type: ignore[no-any-return]
    except Exception:
        logger.exception("Failed to read session state")
        return {}


def _write_session_state(state: dict[str, Any]) -> None:
    path = _session_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(state, tmp, indent=2)
            tmp_path = tmp.name
        Path(tmp_path).replace(path)
    except Exception:
        logger.exception("Failed to write session state")
        if tmp_path:
            with contextlib.suppress(Exception):
                Path(tmp_path).unlink(missing_ok=True)


def _atelier_root() -> Path:
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    if root:
        return Path(root)
    state = _read_session_state()
    if state.get("atelier_root"):
        return Path(state["atelier_root"])
    return Path.home() / ".atelier"


def _active_session_id() -> str | None:
    state = _read_session_state()
    return state.get("session_id") or state.get("active_session_id")


# ---------------------------------------------------------------------------
# RunLedger event writer
# ---------------------------------------------------------------------------


def _append_prompt_event(session_id: str, prompt: str) -> None:
    runs_dir = _atelier_root() / "runs"
    run_file = runs_dir / f"{session_id}.json"
    if not run_file.exists():
        return

    try:
        data = json.loads(run_file.read_text("utf-8"))
    except Exception:
        logger.exception("Failed to read run file")
        return

    events: list[dict[str, Any]] = data.setdefault("events", [])
    truncated = len(prompt) > _MAX_PROMPT_BYTES
    stored_prompt = prompt[:_MAX_PROMPT_BYTES]
    short = stored_prompt[:100].replace("\n", " ")

    events.append(
        {
            "kind": "agent_message",
            "at": datetime.datetime.now(datetime.UTC).isoformat(),
            "summary": f"user: {short}{'…' if len(stored_prompt) > 100 else ''}",
            "payload": {
                "role": "user",
                "prompt": stored_prompt,
                "truncated": truncated,
                "event": "UserPromptSubmit",
            },
        }
    )
    data["events"] = events

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=run_file.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = tmp.name
        Path(tmp_path).replace(run_file)
    except Exception:
        logger.exception("Failed to update run file")
        if tmp_path:
            with contextlib.suppress(Exception):
                Path(tmp_path).unlink(missing_ok=True)


def _persist_last_user_prompt(prompt: str) -> None:
    state = _read_session_state()
    state["last_user_prompt"] = prompt
    _write_session_state(state)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Context-window estimation
# ---------------------------------------------------------------------------

# Context-window capacity per model. The live window occupancy is read from the
# transcript's real ``usage`` numbers (input + cache_read + cache_creation),
# matching what Claude Code's own status-line gauge reports. Capacity is looked
# up by substring match on the model id; ATELIER_CONTEXT_WINDOW_TOKENS overrides
# everything when set. NEVER size against transcript *file bytes*: the JSONL is
# cumulative (tool dumps, compacted-away turns, JSON overhead) and vastly
# exceeds the live window, which is what produced bogus ~100% warnings.
_DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000
_MODEL_WINDOW_TOKENS = {
    "fable": 1_000_000,
    "mythos": 1_000_000,
    "opus-4": 1_000_000,
    "sonnet-4": 1_000_000,
    "haiku-4": 200_000,
    "claude-3": 200_000,
}
# Proactive compaction is token-based so it behaves the same in a 200k or a 1M
# window: we nudge on absolute occupancy, not just a percentage. Each nudge
# carries a real per-turn cache-read cost so the user sees what the stale
# context is actually costing on every message.
_COMPACT_MIN_TOKENS = 100_000  # never nudge below this live occupancy
_DRIFT_MIN_TOKENS = 25_000  # a topic switch can nudge a bit earlier than size alone
# (occupancy_floor, prompts_between_nudges): the more is loaded, the more often
# we re-nudge, because each turn re-bills the whole window as cache reads.
_COMPACT_BANDS: tuple[tuple[int, int], ...] = ((400_000, 1), (150_000, 2), (50_000, 4))

# Cache-read price ($/1M tokens) used to estimate the per-turn cost of carrying
# the current context. Substring match on the model id; Sonnet rate as default.
# Tracks Anthropic's published cache-read prices (~10% of input).
_DEFAULT_CACHE_READ_USD_PER_MTOK = 0.30
_MODEL_CACHE_READ_USD_PER_MTOK = {
    "fable": 1.00,
    "opus": 1.50,
    "sonnet": 0.30,
    "haiku": 0.08,
    "claude-3": 0.30,
}

# Drift detection: TF-IDF cosine similarity between the new prompt and a
# recency-weighted view of recent prompts. Low similarity ⇒ the loaded history
# is now off-topic and is just inflating cache-read cost. Cooldown-gated.
_DRIFT_SIM_THRESHOLD = 0.18  # cosine below this == drifted
_DRIFT_MIN_EARLIER_PROMPTS = 4
_DRIFT_HISTORY_CAP = 8
_DRIFT_STOPWORDS = frozenset(
    "the a an and or but to of in on for with at by from is are be this that it as we i you "
    "can could would should do does did please now then make add fix update change use let".split()
)
_EDIT_INTENT_TERMS = (
    "change ",
    "edit ",
    "fix ",
    "modify ",
    "patch ",
    "refactor ",
    "rename ",
    "rewrite ",
    "update ",
)
_GROUNDED_TERMS = (
    " search ",
    " read ",
    " context ",
    " explore ",
    " node ",
    " callers ",
    " callees ",
    " usages ",
)


def _context_window_tokens(model: str | None) -> int:
    """Resolve the context-window capacity for *model*.

    Precedence: ATELIER_CONTEXT_WINDOW_TOKENS env override > model substring
    lookup > default. Fail-open to the default on any bad value.
    """
    override = os.environ.get("ATELIER_CONTEXT_WINDOW_TOKENS", "").strip()
    if override:
        with contextlib.suppress(ValueError):
            value = int(override)
            if value > 0:
                return value
    lowered = (model or "").lower()
    for needle, capacity in _MODEL_WINDOW_TOKENS.items():
        if needle in lowered:
            return capacity
    return _DEFAULT_CONTEXT_WINDOW_TOKENS


def _model_pricing(model: str | None):  # type: ignore[no-untyped-def]
    """Live rate card for *model*, or None when atelier/pricing is unavailable."""
    try:
        from atelier.core.capabilities.pricing import get_model_pricing

        pricing = get_model_pricing(model or "")
        if pricing.known and pricing.cache_read > 0:
            return pricing
    except Exception:  # noqa: BLE001 - hook must fail open without atelier installed
        pass
    return None


def _cache_read_price(model: str | None, occupancy: int = 0) -> float:
    """Resolve cache-read $/1M-tokens for *model*.

    Premium-aware: above the model's long-context boundary (e.g. 200k) the
    whole request bills at the premium cache-read rate. Falls back to the
    static substring table when the live rate card is unavailable.
    """
    pricing = _model_pricing(model)
    if pricing is not None:
        threshold = pricing.long_context_threshold()
        if occupancy and threshold and occupancy > threshold and pricing.cache_read_tiers:
            return float(pricing.cache_read_tiers[0].rate)
        return float(pricing.cache_read)
    lowered = (model or "").lower()
    for needle, price in _MODEL_CACHE_READ_USD_PER_MTOK.items():
        if needle in lowered:
            return price
    return _DEFAULT_CACHE_READ_USD_PER_MTOK


def _context_occupancy(transcript_path: str) -> tuple[int, str | None]:
    """Return ``(live_window_tokens, model)`` from the transcript's usage data.

    Reads the last real assistant ``usage`` block (input + cache_read +
    cache_creation = current prompt size = live window occupancy). Mirrors
    Claude Code's own status-line gauge; never uses transcript file size, which
    is cumulative. Fail-open: returns ``(0, None)`` on any error.
    """
    try:
        occupancy = 0
        model: str | None = None
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except (ValueError, TypeError):
                    continue
                message = entry.get("message") or {}
                usage = message.get("usage") or {}
                turn = sum(
                    int(usage.get(key, 0) or 0)
                    for key in (
                        "input_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                )
                if turn > 0:
                    occupancy = turn  # last non-zero turn = current occupancy
                    model = message.get("model") or model
        return occupancy, model
    except OSError:
        return 0, None


def _humanize_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n // 1000}k"
    return str(n)


def _topic_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 3 and t not in _DRIFT_STOPWORDS]


def _cosine_drift(current: list[str], history: list[list[str]]) -> float | None:
    """Return TF-IDF cosine similarity (0..1) of *current* vs recency-weighted
    *history*, or ``None`` when there isn't enough signal to judge.

    More accurate than raw term-overlap: rare/topical terms dominate via IDF,
    recent prompts weigh more than old ones, and cosine normalises for length.
    """
    if len(history) < _DRIFT_MIN_EARLIER_PROMPTS or len(current) < 4:
        return None
    docs = [*history, current]
    n = len(docs)
    df: dict[str, int] = {}
    for doc in docs:
        for term in set(doc):
            df[term] = df.get(term, 0) + 1
    idf = {term: math.log((n + 1) / (count + 0.5)) + 1.0 for term, count in df.items()}

    def _vec(tokens: list[str], weight: float = 1.0) -> dict[str, float]:
        if not tokens:
            return {}
        counts: dict[str, float] = {}
        for term in tokens:
            counts[term] = counts.get(term, 0.0) + 1.0
        scale = weight / len(tokens)
        return {term: c * scale * idf[term] for term, c in counts.items()}

    cur = _vec(current)
    hist: dict[str, float] = {}
    m = len(history)
    for i, doc in enumerate(history):
        recency = (i + 1) / m  # oldest ~1/m, newest ~1
        for term, val in _vec(doc, recency).items():
            hist[term] = hist.get(term, 0.0) + val
    dot = sum(weight * hist.get(term, 0.0) for term, weight in cur.items())
    norm_cur = math.sqrt(sum(v * v for v in cur.values()))
    norm_hist = math.sqrt(sum(v * v for v in hist.values()))
    if norm_cur == 0 or norm_hist == 0:
        return None
    return dot / (norm_cur * norm_hist)


def _compact_cooldown(occupancy: int) -> int:
    for floor, cooldown in _COMPACT_BANDS:
        if occupancy >= floor:
            return cooldown
    return _COMPACT_BANDS[-1][1]


def _emit_compaction_advice(occupancy: int, pct: int, model: str | None, drifted: bool) -> None:
    """Inject a compaction nudge carrying the real per-turn cache-read cost."""
    per_turn = occupancy / 1_000_000 * _cache_read_price(model, occupancy)
    tok = _humanize_tokens(occupancy)
    if drifted:
        head = (
            f"This prompt looks unrelated to the earlier conversation, yet ~{tok} tokens "
            f"(~{pct}% of the window) of now-stale history are still loaded"
        )
    else:
        head = f"Context is ~{tok} tokens (~{pct}% of the window)"
    boundary = ""
    pricing = _model_pricing(model)
    if pricing is not None:
        threshold = pricing.long_context_threshold()
        if threshold and occupancy > threshold:
            boundary = (
                f" The window is past the {threshold // 1000}k long-context boundary, so "
                "input-side rates are doubled until it shrinks."
            )
    msg = (
        f"[Atelier] {head}. Carrying it re-bills ~${per_turn:.2f} per turn in cache reads."
        f"{boundary} "
        "Call mcp__atelier__compact now, or tell the user to run /compact, to cut that."
    )
    sys.stdout.write(json.dumps({"type": "context", "content": msg}) + "\n")
    sys.stdout.flush()


def _append_compaction_savings_row(tokens: int, usd: float, model: str | None) -> None:
    """Append a compaction-credit row to the savings sidecar (cache-read priced)."""
    try:
        sid = _active_session_id()
        if not sid:
            return
        path = _atelier_root() / "session_stats" / "claude" / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "kind": "compaction",
            "tokens": int(tokens),
            "usd": round(float(usd), 6),
            "model": model or "",
            "calls": 0,
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def _clear_precompact(state: dict[str, Any]) -> None:
    for key in (
        "precompact_pending",
        "precompact_occupancy",
        "precompact_model",
        "precompact_attempts",
    ):
        state.pop(key, None)


def _credit_pending_compaction(state: dict[str, Any], occupancy: int, model: str | None) -> None:
    """Credit the realized cache-read reduction from a recent compaction.

    PreCompact stored the pre-compaction occupancy; once a turn has run on the
    compacted window we read the new occupancy here and bank the one-time saving
    (delta tokens x cache-read price). Conservative: skips while the delta isn't
    visible yet, gives up after a few prompts, one-shot per compaction. This
    under-credits the recurring per-turn benefit on purpose — never over-credits.
    """
    if not state.get("precompact_pending"):
        return
    attempts = int(state.get("precompact_attempts", 0) or 0) + 1
    state["precompact_attempts"] = attempts
    pre = int(state.get("precompact_occupancy", 0) or 0)
    delta = pre - occupancy
    if occupancy > 0 and 0 < delta <= pre:
        price_model = model or state.get("precompact_model") or ""
        # Premium-aware: when compaction drops the window below the
        # long-context boundary, the saving is pre@premium - post@base,
        # not just delta tokens at one flat rate.
        usd = max(
            0.0,
            pre / 1_000_000 * _cache_read_price(price_model, pre)
            - occupancy / 1_000_000 * _cache_read_price(price_model, occupancy),
        )
        _append_compaction_savings_row(delta, usd, price_model)
        _clear_precompact(state)
    elif attempts >= 3:
        _clear_precompact(state)  # post-compact size never resolved; stop trying


def _maybe_emit_compaction_advice(prompt: str, transcript_path: str) -> bool:
    """Decide whether to nudge for compaction and emit it. Fail-open.

    Fires on absolute occupancy (>=50k tokens) so it works the same at 200k or
    1M windows, earlier (>=25k) when the topic has drifted, and re-nudges more
    often as occupancy grows. Cooldown + rolling topic history live in session
    state. Returns True when a nudge was emitted.
    """
    try:
        occupancy, model = _context_occupancy(transcript_path) if transcript_path else (0, None)
        state = _read_session_state()
        _credit_pending_compaction(state, occupancy, model)
        history_raw = [h for h in state.get("prompt_topic_history", []) if isinstance(h, str)]
        history_tok = [_topic_tokens(h) for h in history_raw]
        sim = _cosine_drift(_topic_tokens(prompt), history_tok)
        drifted = sim is not None and sim < _DRIFT_SIM_THRESHOLD
        count = int(state.get("prompt_count", 0) or 0)
        # Persist rolling history + counter regardless of whether we nudge.
        history_raw.append(prompt[:500])
        state["prompt_topic_history"] = history_raw[-_DRIFT_HISTORY_CAP:]
        state["prompt_count"] = count + 1

        fired = False
        if occupancy > 0:
            window = _context_window_tokens(model)
            pct = min(100, round(occupancy * 100 / window))
            floor = _DRIFT_MIN_TOKENS if drifted else _COMPACT_MIN_TOKENS
            if occupancy >= floor:
                last_raw = state.get("last_compact_notice_count")
                last = last_raw if isinstance(last_raw, int) else -(10**9)
                if count - last >= _compact_cooldown(occupancy):
                    state["last_compact_notice_count"] = count
                    _emit_compaction_advice(occupancy, pct, model, drifted)
                    fired = True
        _write_session_state(state)
        return fired
    except (OSError, ValueError, TypeError):
        return False


def _looks_like_multi_file_edit_prompt(prompt: str) -> bool:
    lowered = f" {prompt.lower()} "
    if not any(term in lowered for term in _EDIT_INTENT_TERMS):
        return False
    if any(term in lowered for term in _GROUNDED_TERMS):
        return False
    file_mentions = lowered.count(".py") + lowered.count(".ts") + lowered.count(".tsx") + lowered.count(".js")
    return file_mentions >= 2 or " files " in lowered


def _emit_grounded_batching_nudge() -> None:
    msg = "[Atelier] Ground multi-file changes with search or read first, then batch related edits in one edit call."
    sys.stdout.write(json.dumps({"type": "context", "content": msg}) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0

    prompt: str = payload.get("prompt", "") or ""
    if not prompt.strip():
        return 0
    stored_prompt = prompt[:_MAX_PROMPT_BYTES]

    # Context-window check — inject a token-based compaction nudge (drift-aware,
    # with the real per-turn cache-read cost) when occupancy warrants it.
    transcript_path: str = payload.get("transcript_path", "") or ""
    _maybe_emit_compaction_advice(prompt, transcript_path)
    if _looks_like_multi_file_edit_prompt(prompt):
        _emit_grounded_batching_nudge()

    # Autopilot (M5): inject scoped context for this prompt. Fail-open.
    try:
        _persist_last_user_prompt(stored_prompt)
        from atelier.core.capabilities.autopilot.factory import run_and_emit

        run_and_emit("user_prompt", {"prompt": prompt})
    except (ImportError, OSError, ValueError):
        pass

    try:
        session_id = _active_session_id()
        if not session_id:
            return 0
        _append_prompt_event(session_id, stored_prompt)
    except (OSError, TypeError, ValueError):
        pass  # fail-open

    return 0


if __name__ == "__main__":
    sys.exit(main())
