#!/usr/bin/env python3
"""Stop hook — session summary.

Reads the hook payload (stdin: JSON with session_id, transcript_path).

Behavior:
1. Discussion-only session (no code-editing tools used in the transcript) →
   show plain stats under a "Session stats:" header.
2. Code work happened → show stats under an "Atelier session complete." header.

Token and tool-call counts are read directly from the Claude Code
transcript JSONL at `transcript_path`.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# Route hook logs to a file so tracebacks never leak to Claude Code's
# hook stderr pipeline. Fall back to NullHandler if the path can't be opened.
_log_path = (
    Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")
    / "stop_hook.log"
)
try:
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(_log_path),
        level=logging.ERROR,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
except (OSError, ValueError):
    logging.root.addHandler(logging.NullHandler())

logger = logging.getLogger(__name__)

# Tools that indicate real code work (not just discussion / exploration).
# Sessions that only used Read, Bash (read-only), Glob, WebFetch, etc. are
# classified as "discussion" and do not require a trace.
CODE_EDITING_TOOLS: frozenset[str] = frozenset(
    {
        "Edit",
        "Write",
        "MultiEdit",
        "NotebookEdit",
        "TodoWrite",
    }
)

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _state_path() -> Path:
    import hashlib

    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    root = Path(os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or Path.home() / ".atelier")
    return root / "workspaces" / h / "session_state.json"


def _load_state() -> dict[str, Any]:
    sp = _state_path()
    if not sp.exists():
        return {}
    try:
        result = json.loads(sp.read_text("utf-8"))
        return result if isinstance(result, dict) else {}
    except Exception:
        logger.exception("Failed to load session state")
        return {}


# ---------------------------------------------------------------------------
# RunLedger token-count writer (fail-open)
# ---------------------------------------------------------------------------


def _atelier_root() -> Path:
    state = _load_state()
    root = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    if root:
        return Path(root)
    if state.get("atelier_root"):
        return Path(state["atelier_root"])
    return Path.home() / ".atelier"


def _write_token_event(stats: dict[str, Any]) -> None:
    """Append a session_stats note event to the active run file."""
    state = _load_state()
    session_id: str | None = state.get("session_id") or state.get("active_session_id")
    if not session_id:
        return
    run_file = _atelier_root() / "sessions" / session_id / "run.json"
    if not run_file.exists():
        return
    try:
        data = json.loads(run_file.read_text("utf-8"))
    except Exception:
        logger.exception("Failed to load run file in _write_token_event")
        return

    events: list[dict[str, Any]] = data.setdefault("events", [])
    events.append(
        {
            "kind": "note",
            "at": datetime.datetime.now(datetime.UTC).isoformat(),
            "summary": (
                f"session end — {stats['total_tokens']:,} tokens "
                f"(+{stats['output_tokens']:,} out), "
                f"~${stats['est_cost_usd']:.4f}"
            ),
            "payload": {
                "input_tokens": stats["input_tokens"],
                "output_tokens": stats["output_tokens"],
                "total_tokens": stats["total_tokens"],
                "est_cost_usd": stats["est_cost_usd"],
                "tool_calls": stats["tool_calls"],
                "top_tools": dict(sorted(stats["tools_used"].items(), key=lambda x: -x[1])[:8]),
                "event": "Stop",
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
        logger.exception("Failed to write token event")
        if tmp_path:
            with contextlib.suppress(Exception):
                Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Transcript helpers — thin wrappers around the shared savings_summary module.
# ---------------------------------------------------------------------------


def _is_real_model_id(raw: object) -> bool:
    try:
        from atelier.core.capabilities.savings_summary import is_real_model

        return is_real_model(raw)
    except (ImportError, ModuleNotFoundError):
        return bool(raw) and raw != "unknown"


def _resolve_model_id(raw: str | None) -> str:
    try:
        from atelier.core.capabilities.savings_summary import resolve_model_id

        return resolve_model_id(raw or "")
    except (ImportError, ModuleNotFoundError):
        return raw or "unknown"


def _estimate_cost_usd(
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float:
    try:
        from atelier.core.capabilities.savings_summary import estimate_cost_usd

        return estimate_cost_usd(
            model_id=model_id,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cache_read_tokens=int(cache_read_tokens or 0),
            cache_write_tokens=int(cache_write_tokens or 0),
        )
    except (ImportError, ModuleNotFoundError):
        return 0.0


def _read_transcript_stats(transcript_path: str) -> dict[str, Any] | None:
    """Parse the Claude Code transcript JSONL and return session stats.

    Delegates to savings_summary.read_transcript_stats() for all parsing,
    then converts the TranscriptStats dataclass to the dict format stop.py
    has always returned.
    """
    try:
        from atelier.core.capabilities.savings_summary import TranscriptStats, read_transcript_stats
    except (ImportError, ModuleNotFoundError):
        return None
    stats: TranscriptStats | None = read_transcript_stats(transcript_path)
    if stats is None:
        return None

    return {
        "tool_calls": stats.tool_calls,
        "turns": stats.turns,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "cache_read_tokens": stats.cache_read_tokens,
        "cache_write_tokens": stats.cache_write_tokens,
        "total_tokens": stats.input_tokens + stats.output_tokens + stats.cache_read_tokens + stats.cache_write_tokens,
        "est_cost_usd": stats.est_cost_usd,
        "model": stats.model,
        "last_model": stats.last_model,
        "models_used": stats.models_used,
        "tools_used": stats.tools_used,
    }


def _extract_session_title(transcript_path: str) -> str | None:
    """Return the first real user message from the transcript as session title.

    Skips:
    - ``local-command-caveat`` system injections
    - Slash-command entries (text starts with ``/`` or wrapped in XML tags)
    - Entries with ``parentUuid`` set (continuations, not root turns)

    Caps the title at 500 characters.
    """
    if not transcript_path:
        return None
    p = Path(transcript_path)
    if not p.exists():
        return None

    import re

    try:
        with p.open(encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except Exception:
                    logger.exception("Failed to parse transcript entry in _extract_session_title")
                    continue

                if entry.get("type") != "user":
                    continue
                # Only root turns (parentUuid is null)
                if entry.get("parentUuid") is not None:
                    continue

                msg = entry.get("message", {}) or {}
                content = msg.get("content", "")

                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            break

                # Skip system injections and empty content
                if "local-command-caveat" in text:
                    continue

                # Strip XML command tags (e.g. <command-name>…</command-name>)
                clean = re.sub(r"<[^>]+>.*?</[^>]+>", "", text, flags=re.DOTALL).strip()

                # Skip pure slash-command inputs
                if not clean or clean.startswith("/"):
                    continue

                return clean[:500]
    except Exception:
        logger.exception("Failed to extract session title")
        return None
    return None


def _extract_user_prompts(transcript_path: str) -> list[str]:
    """Return all real user prompts from the transcript (capped at 2 KB each)."""
    _MAX_PROMPT = 2048
    if not transcript_path:
        return []
    p = Path(transcript_path)
    if not p.exists():
        return []

    import re

    prompts: list[str] = []
    try:
        with p.open(encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except Exception:
                    logger.exception("Failed to parse transcript entry in _extract_user_prompts")
                    continue

                if entry.get("type") != "user":
                    continue
                if entry.get("isSidechain"):
                    continue

                msg = entry.get("message", {}) or {}
                content = msg.get("content", "")

                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            break

                if "local-command-caveat" in text:
                    continue

                clean = re.sub(r"<[^>]+>.*?</[^>]+>", "", text, flags=re.DOTALL).strip()
                if not clean or clean.startswith("/"):
                    continue

                prompts.append(clean[:_MAX_PROMPT])
    except Exception:
        logger.exception("Failed to extract user prompts")
        pass
    return prompts


def _write_session_enrichment(
    session_id: str,
    session_title: str | None,
    user_prompts: list[str],
    transcript_path: str,
) -> None:
    """Append session_metadata note to the active run file.

    Written by the Stop hook so the run file always contains the real session
    title (first user message) and the full prompt history, regardless of what
    the agent reported via ``record``.
    """
    if not session_id:
        return
    run_file = _atelier_root() / "sessions" / session_id / "run.json"
    if not run_file.exists():
        return
    try:
        data = json.loads(run_file.read_text("utf-8"))
    except Exception:
        logger.exception("Failed to load run file in _write_session_enrichment")
        return

    # Update top-level task with session_title when the agent left it blank
    if session_title and not (data.get("task") or "").strip():
        data["task"] = session_title

    events: list[dict[str, Any]] = data.setdefault("events", [])
    events.append(
        {
            "kind": "note",
            "at": datetime.datetime.now(datetime.UTC).isoformat(),
            "summary": f"session_title: {(session_title or '')[:80]}",
            "payload": {
                "session_title": session_title,
                "transcript_path": transcript_path,
                "user_prompts": user_prompts[:50],  # cap at 50 turns
                "prompt_count": len(user_prompts),
                "event": "SessionEnrichment",
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
        logger.exception("Failed to write session enrichment")
        if tmp_path:
            with contextlib.suppress(Exception):
                Path(tmp_path).unlink(missing_ok=True)


def _load_session_aggregate(session_id: str) -> dict[str, Any]:
    if not session_id:
        return {}
    try:
        from atelier.core.capabilities.plugin_runtime import aggregate_session_stats

        aggregate = aggregate_session_stats(_atelier_root(), session_id=session_id)
        return aggregate if isinstance(aggregate, dict) else {}
    except Exception:
        logger.exception("Failed to load session aggregate")
        return {}


def _merge_session_aggregate(stats: dict[str, Any] | None, aggregate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not aggregate:
        return stats

    if stats is None:
        stats = {
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
            "est_cost_usd": 0.0,
            "tools_used": {},
        }

    usage_raw = aggregate.get("usage")
    usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
    # Transcript is authoritative; aggregate is a fallback for zero values.
    # Never let potentially-inflated aggregate values override correct transcript totals.
    stats["tool_calls"] = int(stats.get("tool_calls", 0) or 0) or int(aggregate.get("total_tool_calls", 0) or 0)
    stats["input_tokens"] = int(stats.get("input_tokens", 0) or 0) or int(usage.get("input_tokens", 0) or 0)
    stats["output_tokens"] = int(stats.get("output_tokens", 0) or 0) or int(usage.get("output_tokens", 0) or 0)
    stats["cache_read_tokens"] = int(stats.get("cache_read_tokens", 0) or 0) or int(
        usage.get("cache_read_tokens", 0) or 0
    )
    stats["cache_write_tokens"] = int(stats.get("cache_write_tokens", 0) or 0) or int(
        usage.get("cache_write_tokens", 0) or 0
    )
    stats["total_tokens"] = (
        int(stats["input_tokens"])
        + int(stats["output_tokens"])
        + int(stats["cache_read_tokens"])
        + int(stats["cache_write_tokens"])
    )
    return stats


def _is_task_session(stats: dict[str, Any] | None, session_aggregate: dict[str, Any] | None = None) -> bool:
    """Return True only if code-editing tools were used this session.

    A session that only called Read, Bash (read-only), Glob, WebFetch,
    WebSearch, or had zero tool calls is classified as a "discussion" session
    and does not require an Atelier trace.
    """
    if session_aggregate and int(session_aggregate.get("edit_tool_calls", 0) or 0) > 0:
        return True
    if stats is None or stats.get("tool_calls", 0) == 0:
        return False
    tools_used: set[str] = set(stats.get("tools_used", {}).keys())
    return bool(CODE_EDITING_TOOLS & tools_used)


def _load_session_savings(session_id: str) -> dict[str, Any]:
    """Return session savings summary for the Claude session.

    Delegates to ``compute_savings_summary`` — the same function the
    statusline calls via ``atelier savings --line`` — so the statusline
    figure and this stop-hook summary are always derived from the same
    source (``sessions/<session_id>/savings.jsonl``, priced per-row
    at the model captured when each row was written).
    """
    zero = {
        "saved_usd": 0.0,
        "routing_usd": 0.0,
        "tokens_saved": 0,
        "calls_avoided": 0,
        "carry_usd": 0.0,
        "carry_tokens": 0,
        "estimated": False,
    }
    if not session_id:
        return zero
    try:
        from atelier.core.capabilities.savings_summary import compute_savings_summary

        summary = compute_savings_summary(session_id, atelier_root=_atelier_root())
        return {
            "saved_usd": float(summary.saved_usd),
            "routing_usd": float(summary.routing_saved_usd),
            "tokens_saved": int(summary.ctx_saved),
            "calls_avoided": int(summary.smart_calls),
            "carry_usd": float(summary.carry_usd),
            "carry_tokens": int(summary.carry_tokens),
            "estimated": False,
        }
    except Exception:
        logger.exception("Failed to load session savings")
        return zero


def _fmt_tok(n: int) -> str:
    """Compact token count: 87645 → 87.6k, 24063189 → 24.1M, 4110167440 → 4.1B."""
    n = int(n or 0)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _format_stats(
    stats: dict[str, Any],
    savings: dict[str, Any] | None = None,
    real_cost: bool = False,
) -> str:
    inp = int(stats.get("input_tokens", 0) or 0)
    out = int(stats.get("output_tokens", 0) or 0)
    cache_read = int(stats.get("cache_read_tokens", 0) or 0)
    cache_write = int(stats.get("cache_write_tokens", 0) or 0)
    total = inp + out + cache_read + cache_write
    calls = int(stats.get("tool_calls", 0) or 0)
    turns = int(stats.get("turns", 0) or 0)
    cost = float(stats.get("est_cost_usd", 0.0) or 0.0)

    # Top tools (up to 4)
    top = sorted(stats.get("tools_used", {}).items(), key=lambda x: -x[1])[:4]
    tools_str = " · ".join(f"{n}×{c}" for n, c in top) if top else "none"  # noqa: RUF001

    cost_prefix = "cost: " if real_cost else "est. cost: ~"
    # One-line tokens with all 4 Anthropic billing categories. No separate
    # cache line — cW (cache write, expensive at ~$6.25/M for Opus) and cR
    # (cache read, cheap at $0.50/M) get equal billing prominence so users
    # see the real cost structure at a glance.
    # "input processed" = new uncached input + tokens written to cache this
    # session. Anthropic's `input_tokens` field only counts the non-cached
    # delta per turn, which collapses to near-zero on cache-friendly sessions
    # and confuses readers. cW is also "new input the model processed"; only
    # cR is recycled content. So we surface (in+cW) as the meaningful
    # cumulative input figure and keep the raw breakdown for transparency.
    fresh_in = inp + cache_write
    calls_str = f"{calls} tool call{'s' if calls != 1 else ''}"
    turns_str = f"{turns} turn{'s' if turns != 1 else ''}" if turns > 0 else ""
    activity = " · ".join(p for p in (turns_str, calls_str) if p)
    lines = [
        activity,
        f"tokens: {_fmt_tok(fresh_in)} input ({_fmt_tok(inp)} new + {_fmt_tok(cache_write)} cW) / {_fmt_tok(cache_read)} cR / {_fmt_tok(out)} out  ({_fmt_tok(total)} total)",
        f"{cost_prefix}${cost:.4f}",
    ]

    # Always show savings — even at $0 — so the stop output shape is stable
    # across sessions. No display-time clamps; each saving was priced at the
    # model in use when it was emitted, so we trust the numbers as-is.
    savings = savings or {}
    saved_usd = float(savings.get("saved_usd", 0.0) or 0.0)
    tokens_saved = int(savings.get("tokens_saved", 0) or 0)
    calls_avoided = int(savings.get("calls_avoided", 0) or 0)
    routing_usd = float(savings.get("routing_usd", 0.0) or 0.0)
    lines.append(f"savings: ${saved_usd:.4f} · {tokens_saved:,} tokens saved · {calls_avoided} calls avoided")
    carry_usd = float(savings.get("carry_usd", 0.0) or 0.0)
    carry_tokens = int(savings.get("carry_tokens", 0) or 0)
    if carry_usd > 0:
        carry_tokens_str = f" · {carry_tokens:,} tokens" if carry_tokens > 0 else ""
        lines.append(f"context carry: ${carry_usd:.4f}{carry_tokens_str} (cache re-reads avoided on later turns)")
    if routing_usd > 0:
        lines.append(f"routing savings: ${routing_usd:.4f}")

    lines.append(f"top tools: {tools_str}")

    return "\n".join(lines)


def _format_review_findings(session_id: str) -> str:
    """Surface unconsumed NEEDS_FIX live-reviewer verdicts; mark them consumed.

    Advisory only — returns a short suffix appended to the session message.
    Fail-open: any problem yields an empty suffix.
    """
    if not session_id:
        return ""
    try:
        from atelier.core.capabilities.live_reviewer.sink import (
            latest_unconsumed,
            mark_consumed,
        )
    except ImportError:
        return ""
    root = _atelier_root()
    pending = latest_unconsumed(root, session_id)
    if not pending:
        return ""
    mark_consumed(root, session_id)
    needs_fix = [row for row in pending if row.get("verdict") == "NEEDS_FIX"]
    if not needs_fix:
        return ""
    lines = ["", "Code review (atelier) — NEEDS_FIX:"]
    for row in needs_fix[:5]:
        paths = ", ".join(str(p) for p in (row.get("paths") or []))
        missing = str(row.get("missing") or "").strip().replace("\n", " ")
        lines.append(f"  • {paths}: {missing[:300]}" if missing else f"  • {paths}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        logger.exception("Failed to parse main payload")
        payload = {}

    session_id: str = payload.get("session_id", "") or ""
    transcript_path: str = payload.get("transcript_path", "") or ""
    stats = _read_transcript_stats(transcript_path)
    session_aggregate = _load_session_aggregate(session_id)
    stats = _merge_session_aggregate(stats, session_aggregate)
    # Claude's Stop payload usually omits total_cost; fall back to the
    # transcript-derived estimate already computed in _read_transcript_stats.
    payload_cost: float = float(payload.get("total_cost_usd") or payload.get("total_cost") or 0.0)
    real_cost = False
    if stats is not None and payload_cost > 0:
        stats["est_cost_usd"] = payload_cost
        real_cost = True

    # ── Always write token/cost summary to RunLedger (fail-open) ─────────────
    if stats and stats.get("total_tokens", 0) > 0:
        with contextlib.suppress(Exception):
            _write_token_event(stats)

    # ── Enrich run file with session title + full prompt history ──────────────
    with contextlib.suppress(Exception):
        session_title = _extract_session_title(transcript_path)
        user_prompts = _extract_user_prompts(transcript_path)
        if session_title or user_prompts:
            _write_session_enrichment(session_id, session_title, user_prompts, transcript_path)

    # ── Load per-session savings breakdown ────────────────────────────────────
    savings: dict[str, Any] | None = None
    with contextlib.suppress(Exception):
        savings = _load_session_savings(session_id)

    # ── Surface unconsumed live-reviewer findings (advisory) ─────────────────
    review_suffix = ""
    with contextlib.suppress(Exception):
        review_suffix = _format_review_findings(session_id)

    # Transcript JSONL stays as the source of truth even after stop —
    # cost, tokens, and savings are all derivable from it. No snapshot needed.

    # ── Always show stats (discussion and task sessions alike) ───────────────
    # If no code-editing tools were used, show plain session stats.
    if not _is_task_session(stats, session_aggregate):
        if stats and stats["total_tokens"] > 0:
            summary = _format_stats(stats, savings, real_cost=real_cost)
            print(json.dumps({"systemMessage": f"Session stats:\n{summary}{review_suffix}"}))
        return 0

    # ── Code work happened: show the session-complete summary ────────────────
    # (Stop hooks can only emit a systemMessage — hookSpecificOutput is not
    # valid here, unlike PreToolUse/PostToolUse/UserPromptSubmit/PostToolBatch.)
    if stats and stats["total_tokens"] > 0:
        summary = _format_stats(stats, savings, real_cost=real_cost)
        print(json.dumps({"systemMessage": f"Atelier session complete.\n{summary}{review_suffix}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
