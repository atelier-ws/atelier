"""Unified savings/cost computation for all hooks and host integrations.

Single source of truth for:
- Claude transcript discovery and per-model cost parsing
- Session savings aggregation (live events + session_stats)
- savings-line output formatting (consumed by statusline.sh via ``atelier savings-line``)

Previously this logic was spread across:
- integrations/claude/plugin/scripts/statusline.sh (inline Python heredoc)
- integrations/claude/plugin/hooks/stop.py (_read_transcript_stats, _estimate_cost_usd, etc.)
- plugin_runtime.py (load_live_savings_summary)
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
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
) -> float:
    """Estimate cost using the per-model 4-category rate card.

    Falls back to Sonnet 4.5 rates when the model is unknown so we never
    silently show $0 for an active session.
    """
    try:
        from atelier.core.capabilities.pricing import get_model_pricing

        pricing = get_model_pricing(model_id) if model_id else None
        if pricing is None or not pricing.known or pricing.input <= 0:
            pricing = get_model_pricing("claude-sonnet-4-5")
        return pricing.cost_usd(
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cache_read_tokens=int(cache_read_tokens or 0),
            cache_write_tokens=int(cache_write_tokens or 0),
        )
    except Exception:
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
        return []
    return sorted((p for p in paths if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)


@dataclass
class TranscriptStats:
    """Parsed statistics from a Claude transcript JSONL file."""

    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    est_cost_usd: float = 0.0
    # Cost of prompt tokens only (input + cache, no output). Used to derive the
    # per-token rate for savings computation — savings are tokens *not sent*, so
    # only input/cache rates apply.
    prompt_cost_usd: float = 0.0
    model: str = ""
    models_used: list[str] = field(default_factory=list)
    tools_used: dict[str, int] = field(default_factory=dict)
    # Per-model token buckets: {model_id: {in, out, cR, cW}} for weighted pricing.
    per_model: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def prompt_rate(self) -> float | None:
        """Blended $/token for prompt (input + cache) tokens.

        Uses only the prompt-token component of cost because saved tokens are
        INPUT tokens (context not resent) — output costs don't apply here.
        Returns None when there are no prompt tokens or no cost to derive a rate from.
        """
        if self.prompt_tokens <= 0 or self.prompt_cost_usd <= 0:
            return None
        return self.prompt_cost_usd / self.prompt_tokens

    def savings_input_rate(self) -> float | None:
        """Weighted $/input-token rate across all models used in this session.

        Saved tokens are context tokens NOT sent to the model — they would have
        been charged as NEW INPUT tokens (not cache reads/writes).  We weight
        each model's input rate by the number of input tokens it actually
        processed to get the best per-session estimate.
        """
        from atelier.core.capabilities.pricing import get_model_pricing

        if not self.per_model:
            return None
        total_input = sum(b.get("in", 0) for b in self.per_model.values())
        if total_input <= 0:
            # No per-turn input token data; fall back to first model's input rate.
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


def read_transcript_stats(transcript_path: str | Path) -> TranscriptStats | None:
    """Parse a Claude transcript JSONL and return session stats.

    Cost is computed per model per turn because users can switch models
    mid-conversation (e.g. Opus → Sonnet).  Each token bucket is priced with
    its own rate card and summed.
    """
    p = Path(transcript_path)
    if not p.exists():
        return None

    tool_calls = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    tools_used: dict[str, int] = {}
    model_id = ""
    per_model: dict[str, dict[str, int]] = {}
    seen_usage_message_ids: set[str] = set()
    seen_tool_use_ids: set[str] = set()

    try:
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except Exception:
                continue

            msg = entry.get("message") or {}
            if not isinstance(msg, dict):
                continue
            msg_id = str(msg.get("id") or "").strip()

            if not model_id:
                candidate = msg.get("model") or entry.get("model") or ""
                if is_real_model(candidate):
                    model_id = str(candidate).strip()

            usage = msg.get("usage") or {}
            if not isinstance(usage, dict):
                continue
            in_t = int(usage.get("input_tokens", 0) or 0)
            out_t = int(usage.get("output_tokens", 0) or 0)
            cr_t = int(usage.get("cache_read_input_tokens", 0) or 0)
            cw_t = int(usage.get("cache_creation_input_tokens", 0) or 0)
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

                turn_model = str(msg.get("model") or entry.get("model") or "").strip()
                if is_real_model(turn_model):
                    bucket = per_model.setdefault(turn_model, {"in": 0, "out": 0, "cR": 0, "cW": 0})
                    bucket["in"] += in_t
                    bucket["out"] += out_t
                    bucket["cR"] += cr_t
                    bucket["cW"] += cw_t

            for index, block in enumerate(msg.get("content") or []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
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
        return None

    resolved_model = resolve_model_id(model_id)

    if per_model:
        est_cost_usd = sum(
            estimate_cost_usd(
                model_id=resolve_model_id(m),
                input_tokens=b["in"],
                output_tokens=b["out"],
                cache_read_tokens=b["cR"],
                cache_write_tokens=b["cW"],
            )
            for m, b in per_model.items()
        )
        # Prompt-only cost: exclude output tokens (savings = tokens not sent as input)
        prompt_cost_usd = sum(
            estimate_cost_usd(
                model_id=resolve_model_id(m),
                input_tokens=b["in"],
                output_tokens=0,
                cache_read_tokens=b["cR"],
                cache_write_tokens=b["cW"],
            )
            for m, b in per_model.items()
        )
    else:
        est_cost_usd = estimate_cost_usd(
            model_id=resolved_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        prompt_cost_usd = estimate_cost_usd(
            model_id=resolved_model,
            input_tokens=input_tokens,
            output_tokens=0,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

    return TranscriptStats(
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        est_cost_usd=est_cost_usd,
        prompt_cost_usd=prompt_cost_usd,
        model=resolved_model,
        models_used=(
            sorted(resolve_model_id(m) for m in per_model)
            if per_model
            else ([resolved_model] if resolved_model else [])
        ),
        tools_used=tools_used,
        per_model={resolve_model_id(m): b for m, b in per_model.items()} if per_model else {},
    )


def transcript_prompt_rate(session_candidates: list[str]) -> float | None:
    """Return the blended $/prompt-token rate derived from the Claude transcript.

    This is the authoritative rate for computing ``saved_usd`` because it reads
    real model IDs (not display names or defaults) and weights each turn by its
    actual token counts.  It is authoritative over live-event ``saved_usd``
    values which may have been written with a stale ``$0.003/1K`` fallback.
    """
    for candidate in session_candidates:
        paths = claude_transcript_candidates(candidate)
        if not paths:
            continue
        stats = read_transcript_stats(paths[0])
        if stats is not None:
            rate = stats.prompt_rate()
            if rate is not None:
                return rate
    return None


# ---------------------------------------------------------------------------
# Savings aggregation
# ---------------------------------------------------------------------------


@dataclass
class SavingsSummary:
    saved_usd: float = 0.0
    ctx_saved: int = 0
    smart_calls: int = 0
    routing_saved_usd: float = 0.0
    est_cost_usd: float = 0.0  # baseline cost from terminated session transcript
    status_text: str = ""


def session_done_path(session_id: str, atelier_root: str | Path | None = None) -> Path:
    """Return the path for the terminal savings snapshot written by the stop hook."""
    root: Path
    if atelier_root:
        root = Path(atelier_root)
    else:
        root_env = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or ""
        root = Path(root_env) if root_env else Path.home() / ".atelier"
    return root / "session_done" / f"{session_id}.json"


def write_session_done(
    session_id: str,
    *,
    tokens_saved: int,
    calls_avoided: int,
    saved_usd: float,
    routing_usd: float,
    est_cost_usd: float = 0.0,
    atelier_root: str | Path | None = None,
) -> None:
    """Write a terminal savings snapshot so savings-line uses transcript data after stop."""
    if not session_id:
        return
    try:
        path = session_done_path(session_id, atelier_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "tokens_saved": tokens_saved,
                    "calls_avoided": calls_avoided,
                    "saved_usd": saved_usd,
                    "routing_usd": routing_usd,
                    "est_cost_usd": est_cost_usd,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _workspace_digest(workspace: str | None = None) -> str:
    ws = workspace or os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()
    return hashlib.sha256(str(Path(ws).resolve()).encode("utf-8")).hexdigest()[:12]


def resolve_session_candidates(
    session_id: str,
    *,
    atelier_root: str | Path | None = None,
    workspace: str | None = None,
) -> list[str]:
    """Return ordered list of session ID candidates to try for savings lookup.

    Combines the explicit *session_id* (from Claude Code's context_window payload)
    with IDs found in the workspace session_state.json so we can find savings even
    when Claude Code doesn't pass the session ID down to hooks.
    """
    root = Path(atelier_root) if atelier_root else None
    if root is None:
        root_env = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or ""
        root = Path(root_env) if root_env else None

    candidates: list[str] = []

    def _add(s: str) -> None:
        s = s.strip()
        if s and s not in candidates:
            candidates.append(s)

    _add(session_id)

    if root is not None:
        try:
            digest = _workspace_digest(workspace)
            state_path = root / "workspaces" / digest / "session_state.json"
            if state_path.is_file():
                state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8"))
                _add(str(state.get("session_id") or ""))
                _add(str(state.get("active_session_id") or ""))
        except Exception:
            pass

    return candidates


def _transcript_model(session_candidates: list[str]) -> str:
    """Return the canonical model ID found in the session transcript, or empty string."""
    for candidate in session_candidates:
        paths = claude_transcript_candidates(candidate)
        if not paths:
            continue
        stats = read_transcript_stats(paths[0])
        if stats is not None and stats.model:
            return stats.model
    return ""


def compute_savings_summary(
    session_id: str = "",
    *,
    model_id: str = "",
    atelier_root: str | Path | None = None,
    workspace: str | None = None,
) -> SavingsSummary:
    """Single entry point: resolve savings and compute ``saved_usd`` at the correct rate.

    Saved tokens are context tokens that Atelier's optimizer did NOT load into
    the context window.  Those tokens would have been charged as new INPUT tokens
    (not cache reads), so we always use the model's input token rate.

    Priority for model identification:
    1. Explicit *model_id* argument.
    2. ``ATELIER_STATUS_MODEL`` / ``ATELIER_MODEL`` env vars.
    3. Model detected from the Claude transcript.
    4. Sonnet 4.5 fallback (never silent $0).
    """
    from atelier.core.capabilities.plugin_runtime import load_live_savings_summary

    root = Path(atelier_root) if atelier_root else None
    if root is None:
        root_env = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or ""
        root = Path(root_env) if root_env else None

    session_candidates = resolve_session_candidates(session_id, atelier_root=root, workspace=workspace)

    # --- terminal snapshot (written by stop hook) takes precedence over live events ---
    # Once a session ends, the transcript is authoritative; live events are no longer relevant.
    if root is not None:
        for candidate in session_candidates:
            done_path = session_done_path(candidate, root)
            if not done_path.is_file():
                continue
            try:
                data = json.loads(done_path.read_text(encoding="utf-8"))
                return SavingsSummary(
                    saved_usd=float(data.get("saved_usd", 0.0) or 0.0),
                    ctx_saved=int(data.get("tokens_saved", 0) or 0),
                    smart_calls=int(data.get("calls_avoided", 0) or 0),
                    routing_saved_usd=float(data.get("routing_usd", 0.0) or 0.0),
                    est_cost_usd=float(data.get("est_cost_usd", 0.0) or 0.0),
                )
            except Exception:
                continue

    result = SavingsSummary()

    # --- live events only — real token counts from MCP tool results ---
    # session_stats uses fixed heuristic constants (~77k tokens/call regardless
    # of actual response size). live_savings_events.jsonl has real tokens_saved
    # from each tool result. We use live events exclusively so the number is
    # grounded in what the tools actually reported, not a formula.
    if root is not None:
        for candidate in session_candidates:
            live = load_live_savings_summary(root, session_id=candidate)
            live_calls = int(live.get("calls_saved", 0) or 0)
            live_tokens = int(live.get("tokens_saved", 0) or 0)
            live_saved_usd = float(live.get("saved_usd", 0.0) or 0.0)
            live_routing_usd = float(live.get("routing_saved_usd", 0.0) or 0.0)
            if not (live_calls or live_tokens or live_saved_usd or live_routing_usd):
                continue
            result.smart_calls = live_calls
            result.ctx_saved = live_tokens
            result.saved_usd = live_saved_usd
            result.routing_saved_usd = live_routing_usd
            break

    # --- recompute saved_usd at the correct rate ---
    # Saved tokens are context tokens that were NOT loaded — they would have been
    # charged as NEW INPUT tokens, not cache reads.  Always use the model's INPUT
    # token rate (never a flat fallback).  Unknown models fall back to Sonnet pricing.
    # Use per-turn weighted rate from the transcript so mixed-model sessions
    # (e.g. Opus then Sonnet) are priced correctly per segment, not just by first model.
    if result.ctx_saved > 0:
        try:
            from atelier.core.capabilities.pricing import get_model_pricing

            # Try weighted rate from transcript (reads per-turn model data)
            rate_per_token: float | None = None
            for candidate in session_candidates:
                paths = claude_transcript_candidates(candidate)
                if not paths:
                    continue
                stats = read_transcript_stats(paths[0])
                if stats is not None:
                    rate_per_token = stats.savings_input_rate()
                    if rate_per_token is not None:
                        break

            if rate_per_token is None:
                # Fallback: single-model resolution priority
                mid = (
                    model_id
                    or os.environ.get("ATELIER_STATUS_MODEL")
                    or os.environ.get("ATELIER_MODEL")
                    or "claude-sonnet-4-5"
                )
                pricing = get_model_pricing(mid)
                if pricing is None or not pricing.known or pricing.input <= 0:
                    pricing = get_model_pricing("claude-sonnet-4-5")
                if pricing is not None and pricing.input > 0:
                    rate_per_token = pricing.input / 1_000_000

            if rate_per_token is not None and rate_per_token > 0:
                result.saved_usd = rate_per_token * result.ctx_saved
        except Exception:
            pass  # leave saved_usd at whatever live events reported

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


def savings_line(
    session_id: str = "",
    *,
    model_id: str = "",
    atelier_root: str | Path | None = None,
    workspace: str | None = None,
) -> str:
    """Return the pipe-delimited savings line consumed by statusline.sh.

    Format: ``$<saved_usd>|<tokens_saved>|<calls_saved>|<status_text>|$<routing_saved_usd>``
    """
    summary = compute_savings_summary(
        session_id,
        model_id=model_id,
        atelier_root=atelier_root,
        workspace=workspace,
    )
    summary.status_text = _resolve_status_text(atelier_root)
    return f"${summary.saved_usd:.3f}|{_fmt_tok(summary.ctx_saved)}|{summary.smart_calls}|{summary.status_text}|${summary.routing_saved_usd:.3f}|{summary.est_cost_usd:.3f}"
