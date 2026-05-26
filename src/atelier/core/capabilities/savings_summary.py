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
    model: str = ""
    models_used: list[str] = field(default_factory=list)
    tools_used: dict[str, int] = field(default_factory=dict)
    # Per-model token buckets: {model_id: {in, out, cR, cW}} for weighted pricing.
    per_model: dict[str, dict[str, int]] = field(default_factory=dict)
    # Last model seen in transcript (most recent turn). Differs from `model`
    # (first seen) for resumed sessions where user switched models mid-session.
    last_model: str = ""
    # Atelier savings extracted from tool_result.content[].saved entries.
    # Priced per-event at the model of the assistant turn that issued the tool_use.
    saved_tokens: int = 0
    saved_calls: int = 0
    saved_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


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
    last_model_id = ""  # tracks most recently seen model (for resumed sessions)
    per_model: dict[str, dict[str, int]] = {}
    seen_usage_message_ids: set[str] = set()
    seen_tool_use_ids: set[str] = set()
    # tool_use_id -> model that issued it (for pricing tool_result savings)
    tool_use_model: dict[str, str] = {}
    seen_saved_tool_use_ids: set[str] = set()
    saved_tokens_total = 0
    saved_calls_total = 0
    saved_usd_total = 0.0

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

            candidate = msg.get("model") or entry.get("model") or ""
            if is_real_model(candidate):
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
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "tool_use":
                    name = block.get("name") or "unknown"
                    tool_use_id = str(block.get("id") or "").strip()
                    if tool_use_id and last_model_id:
                        tool_use_model[tool_use_id] = last_model_id
                    tool_key = tool_use_id or (f"{msg_id}:{index}:{name}" if msg_id else "")
                    if tool_key:
                        if tool_key in seen_tool_use_ids:
                            continue
                        seen_tool_use_ids.add(tool_key)
                    tools_used[name] = tools_used.get(name, 0) + 1
                    tool_calls += 1
                elif block_type == "tool_result":
                    # MCP tool results carry per-call savings on each content
                    # item: {"type":"text","text":"...","saved":{"tokens":N,"calls":M}}.
                    # Sum across the result's content list, then price the
                    # tokens at the model that issued the originating tool_use.
                    tool_use_id = str(block.get("tool_use_id") or "").strip()
                    if tool_use_id and tool_use_id in seen_saved_tool_use_ids:
                        continue
                    if tool_use_id:
                        seen_saved_tool_use_ids.add(tool_use_id)
                    saved_tokens_here = 0
                    saved_calls_here = 0
                    for content in block.get("content") or []:
                        if not isinstance(content, dict):
                            continue
                        saved = content.get("saved")
                        if not isinstance(saved, dict):
                            continue
                        try:
                            saved_tokens_here += int(saved.get("tokens") or 0)
                            saved_calls_here += int(saved.get("calls") or 0)
                        except (TypeError, ValueError):
                            continue
                    if saved_tokens_here <= 0 and saved_calls_here <= 0:
                        continue
                    saved_tokens_total += max(0, saved_tokens_here)
                    saved_calls_total += max(0, saved_calls_here)
                    issuing_model = tool_use_model.get(tool_use_id) or last_model_id
                    if issuing_model and saved_tokens_here > 0:
                        try:
                            from atelier.core.capabilities.pricing import get_model_pricing

                            pricing = get_model_pricing(resolve_model_id(issuing_model))
                            if pricing is not None and pricing.known and pricing.input > 0:
                                saved_usd_total += pricing.cost_usd(input_tokens=saved_tokens_here)
                        except Exception:
                            pass
    except Exception:
        return None

    resolved_model = resolve_model_id(model_id)
    resolved_last_model = resolve_model_id(last_model_id) if last_model_id else resolved_model

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
        saved_tokens=saved_tokens_total,
        saved_calls=saved_calls_total,
        saved_usd=round(saved_usd_total, 6),
    )


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
    total_tokens: int = 0  # cumulative session tokens (in+out+cR+cW) from transcript
    status_text: str = ""


def compute_savings_summary(
    session_id: str = "",
    *,
    atelier_root: str | Path | None = None,
    workspace: str | None = None,
) -> SavingsSummary:
    """Single entry point. The Claude transcript JSONL is the only source.

    Reads ``~/.claude/projects/<project>/<session_id>.jsonl`` exactly once:

    - cumulative tokens / cost: per-turn ``message.usage`` priced at
      ``message.model`` (handles mid-session model switches).
    - savings (tokens + calls + USD): summed from
      ``tool_result.content[].saved`` blocks the MCP server embedded,
      priced at the model that issued the originating ``tool_use``.

    No side files. No session-id filter. No live-events jsonl. No done file.
    """
    del atelier_root, workspace  # accepted for backward compatibility; unused

    result = SavingsSummary()
    if not session_id:
        return result

    paths = claude_transcript_candidates(session_id)
    if not paths:
        return result

    stats = read_transcript_stats(paths[0])
    if stats is None:
        return result

    result.saved_usd = stats.saved_usd
    result.ctx_saved = stats.saved_tokens
    result.smart_calls = stats.saved_calls
    result.est_cost_usd = stats.est_cost_usd
    result.total_tokens = stats.total_tokens
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
    atelier_root: str | Path | None = None,
    workspace: str | None = None,
) -> str:
    """Return the pipe-delimited savings line consumed by statusline.sh.

    Format: ``$<saved_usd>|<tokens_saved>|<calls_saved>|<status_text>|$<routing_saved_usd>|<est_cost_usd>|<total_tokens>``
    """
    summary = compute_savings_summary(session_id, atelier_root=atelier_root, workspace=workspace)
    summary.status_text = _resolve_status_text(atelier_root)
    return (
        f"${summary.saved_usd:.3f}|{_fmt_tok(summary.ctx_saved)}|{summary.smart_calls}"
        f"|{summary.status_text}|${summary.routing_saved_usd:.3f}"
        f"|{summary.est_cost_usd:.3f}|{summary.total_tokens}"
    )
