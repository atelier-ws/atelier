#!/usr/bin/env python3
"""Stop hook — session summary + trace reminder.

Reads the hook payload (stdin: JSON with session_id, transcript_path).

Decision tree:
1. If this was a discussion-only session (no code-editing tools used in the
   transcript) → silent exit.  No trace required.
2. If code work happened AND trace was already called for
   this session → show stats and exit silently.
3. If code work happened but no trace was recorded → surface a system
   message asking Claude to call trace.

Token and tool-call counts are read directly from the Claude Code
transcript JSONL at `transcript_path`.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

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
    session_id: str | None = state.get("active_session_id")
    if not session_id:
        return
    run_file = _atelier_root() / "runs" / f"{session_id}.json"
    if not run_file.exists():
        return
    try:
        data = json.loads(run_file.read_text("utf-8"))
    except Exception:
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
        if tmp_path:
            with contextlib.suppress(Exception):
                Path(tmp_path).unlink(missing_ok=True)


def _trace_recorded(session_id: str) -> bool:
    """Return True if trace was called in this session.

    Checks session-scoped state first (keyed by *session_id*), then falls
    back to the legacy global ``trace_recorded`` flag for older MCP versions
    that do not write per-session state.
    """
    state = _load_state()

    if session_id:
        sessions: dict[str, dict[str, Any]] = state.get("sessions", {})
        session_data = sessions.get(session_id, {})
        if "trace_recorded" in session_data:
            return bool(session_data["trace_recorded"])

    # Legacy fallback — mcp_server.py < 2.x wrote a flat `trace_recorded` key
    return bool(state.get("trace_recorded"))


# ---------------------------------------------------------------------------
# Transcript helpers — thin wrappers around the shared savings_summary module.
# ---------------------------------------------------------------------------


def _is_real_model_id(raw: object) -> bool:
    from atelier.core.capabilities.savings_summary import is_real_model

    return is_real_model(raw)


def _resolve_model_id(raw: str | None) -> str:
    from atelier.core.capabilities.savings_summary import resolve_model_id

    return resolve_model_id(raw or "")


def _estimate_cost_usd(
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float:
    from atelier.core.capabilities.savings_summary import estimate_cost_usd

    return estimate_cost_usd(
        model_id=model_id,
        input_tokens=int(input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        cache_read_tokens=int(cache_read_tokens or 0),
        cache_write_tokens=int(cache_write_tokens or 0),
    )


def _read_transcript_stats(transcript_path: str) -> dict[str, Any] | None:
    """Parse the Claude Code transcript JSONL and return session stats.

    Delegates to savings_summary.read_transcript_stats() for all parsing,
    then converts the TranscriptStats dataclass to the dict format stop.py
    has always returned.
    """
    from atelier.core.capabilities.savings_summary import TranscriptStats, read_transcript_stats

    stats: TranscriptStats | None = read_transcript_stats(transcript_path)
    if stats is None:
        return None

    return {
        "tool_calls": stats.tool_calls,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "cache_read_tokens": stats.cache_read_tokens,
        "cache_write_tokens": stats.cache_write_tokens,
        "total_tokens": stats.input_tokens + stats.output_tokens + stats.cache_read_tokens + stats.cache_write_tokens,
        "est_cost_usd": stats.est_cost_usd,
        "model": stats.model,
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
    run_file = _atelier_root() / "runs" / f"{session_id}.json"
    if not run_file.exists():
        return
    try:
        data = json.loads(run_file.read_text("utf-8"))
    except Exception:
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
    stats["tool_calls"] = max(int(stats.get("tool_calls", 0) or 0), int(aggregate.get("total_tool_calls", 0) or 0))
    stats["input_tokens"] = max(int(stats.get("input_tokens", 0) or 0), int(usage.get("input_tokens", 0) or 0))
    stats["output_tokens"] = max(int(stats.get("output_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0))
    stats["cache_read_tokens"] = max(
        int(stats.get("cache_read_tokens", 0) or 0),
        int(usage.get("cache_read_tokens", 0) or 0),
    )
    stats["cache_write_tokens"] = max(
        int(stats.get("cache_write_tokens", 0) or 0),
        int(usage.get("cache_write_tokens", 0) or 0),
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


def _load_session_savings(session_id: str, model_id: str | None = None) -> dict[str, Any]:
    """Return session savings summary merged from session stats and live events."""
    if not session_id:
        return {
            "saved_usd": 0.0,
            "routing_usd": 0.0,
            "tokens_saved": 0,
            "calls_avoided": 0,
            "estimated": False,
        }
    try:
        from atelier.core.capabilities.plugin_runtime import build_savings_report

        report = build_savings_report(_atelier_root(), session_id=session_id, model_id=model_id)
        cost_raw = report.get("cost")
        cost: dict[str, Any] = cost_raw if isinstance(cost_raw, dict) else {}
        live_saved = float(cost.get("live_saved_usd", 0.0) or 0.0)
        saved_usd = float(cost.get("saved_usd", 0.0) or 0.0)
        effective_saved = live_saved if live_saved > 0 else saved_usd
        return {
            "saved_usd": effective_saved,
            "routing_usd": float(cost.get("routing_saved_usd", 0.0) or 0.0),
            "tokens_saved": int(report.get("tokens_saved", 0) or 0),
            "calls_avoided": int(report.get("calls_avoided", 0) or 0),
            "estimated": live_saved <= 0 and effective_saved > 0,
        }
    except Exception:
        pass
    return {
        "saved_usd": 0.0,
        "routing_usd": 0.0,
        "tokens_saved": 0,
        "calls_avoided": 0,
        "estimated": False,
    }


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
    cost = float(stats.get("est_cost_usd", 0.0) or 0.0)

    # Top tools (up to 4)
    top = sorted(stats.get("tools_used", {}).items(), key=lambda x: -x[1])[:4]
    tools_str = " · ".join(f"{n}×{c}" for n, c in top) if top else "none"  # noqa: RUF001

    cost_prefix = "cost: " if real_cost else "est. cost: ~"
    # One-line tokens with all 4 Anthropic billing categories. No separate
    # cache line — cW (cache write, expensive at ~$6.25/M for Opus) and cR
    # (cache read, cheap at $0.50/M) get equal billing prominence so users
    # see the real cost structure at a glance.
    lines = [
        f"tool calls: {calls}",
        f"tokens: {_fmt_tok(inp)} in / {_fmt_tok(cache_write)} cW / {_fmt_tok(cache_read)} cR / {_fmt_tok(out)} out  ({_fmt_tok(total)} total)",
        f"{cost_prefix}${cost:.4f}",
    ]

    if savings and (
        float(savings.get("saved_usd", 0.0) or 0.0) > 0
        or int(savings.get("tokens_saved", 0) or 0) > 0
        or int(savings.get("calls_avoided", 0) or 0) > 0
    ):
        saved_usd = float(savings.get("saved_usd", 0.0) or 0.0)
        tokens_saved = int(savings.get("tokens_saved", 0) or 0)
        calls_avoided = int(savings.get("calls_avoided", 0) or 0)

        # Final sanity caps at the display boundary so we never print numbers
        # that are obviously inconsistent with the session that just ended.
        raw_calls_avoided = calls_avoided
        raw_tokens_saved = tokens_saved
        if calls > 0:
            calls_avoided = min(calls_avoided, calls)
        if total > 0:
            tokens_saved = min(tokens_saved, total)
        # If a count was hard-clamped down (raw ≫ actual), the underlying
        # counter is mis-attributing throughput as savings. Drop the count.
        if calls > 0 and raw_calls_avoided > calls:
            calls_avoided = 0
        if total > 0 and raw_tokens_saved > total:
            tokens_saved = 0
        # If savings would exceed the actual session cost by >5x, the math is
        # almost certainly leaking cross-session totals -- hide the dollar
        # figure rather than print something misleading.
        if cost > 0 and saved_usd > cost * 5:
            saved_usd = 0.0

        if saved_usd > 0 or tokens_saved > 0 or calls_avoided > 0:
            parts = []
            if saved_usd > 0:
                prefix = "~$" if savings.get("estimated") else "$"
                parts.append(f"{prefix}{saved_usd:.4f}")
            if calls_avoided > 0:
                parts.append(f"{calls_avoided} calls avoided")
            if tokens_saved > 0:
                parts.append(f"{tokens_saved:,} tokens saved")
            if parts:
                lines.append("savings: " + " · ".join(parts))
        routing_usd = float(savings.get("routing_usd", 0.0) or 0.0)
        if routing_usd > 0 and (cost <= 0 or routing_usd <= cost * 5):
            lines.append(f"routing savings: ${routing_usd:.4f}")

    lines.append(f"top tools: {tools_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Auto-record helper
# ---------------------------------------------------------------------------


def _auto_record(session_id: str, stats: dict[str, Any] | None) -> None:
    """Call `atelier runs record` silently so the ledger stays complete."""
    import subprocess

    if not session_id:
        return
    total_in = (stats or {}).get("input_tokens", 0)
    total_out = (stats or {}).get("output_tokens", 0)
    cost = (stats or {}).get("est_cost_usd", 0.0)
    tool_calls = (stats or {}).get("tool_calls", 0)
    trace = {
        "agent": "claude-code",
        "domain": "session",
        "task": "session-auto-record",
        "status": "success",
        "session_id": session_id,
        "output_summary": f"tokens: {total_in}in/{total_out}out  cost: ~${cost:.4f}  tools: {tool_calls}",
    }

    atelier_bin = os.environ.get("ATELIER_BIN") or str(Path.home() / ".local" / "bin" / "atelier")
    with contextlib.suppress(Exception):
        subprocess.run(
            [atelier_bin, "runs", "record", "--input", "-"],
            input=json.dumps(trace),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}

    session_id: str = payload.get("session_id", "") or ""
    transcript_path: str = payload.get("transcript_path", "") or ""
    stats = _read_transcript_stats(transcript_path)
    session_aggregate = _load_session_aggregate(session_id)
    stats = _merge_session_aggregate(stats, session_aggregate)
    payload_cost: float = float(payload.get("total_cost_usd") or payload.get("total_cost") or 0.0)
    if not payload_cost and session_id:
        with contextlib.suppress(Exception):
            cost_dir = _atelier_root() / "session_costs"
            # The statusline writes <session_id>.txt. A historical parsing bug
            # could also produce <noise>\t<session_id>.txt variants. Pick the
            # freshest file whose name CONTAINS the session_id and read the
            # largest numeric value (the latest snapshot).
            candidates = []
            clean_file = cost_dir / f"{session_id}.txt"
            if clean_file.is_file():
                candidates.append(clean_file)
            if cost_dir.is_dir():
                for entry in cost_dir.iterdir():
                    if entry.is_file() and session_id in entry.name and entry not in candidates:
                        candidates.append(entry)
            if candidates:
                best_cost = 0.0
                best_mtime = 0.0
                for entry in candidates:
                    try:
                        value = float(entry.read_text("utf-8").strip())
                        mtime = entry.stat().st_mtime
                    except Exception:
                        continue
                    if value <= 0:
                        continue
                    # Prefer most recent; on tie prefer larger (cost only grows).
                    if mtime > best_mtime or (mtime == best_mtime and value > best_cost):
                        best_cost = value
                        best_mtime = mtime
                if best_cost > 0:
                    payload_cost = best_cost
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
    session_model = stats.get("model") if isinstance(stats, dict) else None
    with contextlib.suppress(Exception):
        savings = _load_session_savings(session_id, model_id=session_model)
        if savings and (
            float(savings.get("saved_usd", 0.0) or 0.0) <= 0
            and int(savings.get("tokens_saved", 0) or 0) <= 0
            and int(savings.get("calls_avoided", 0) or 0) <= 0
        ):
            savings = None

    # ── Write terminal snapshot so `savings --line` uses transcript data post-stop ──
    # After this point the session is over; live events are no longer relevant.
    # write_session_done() creates session_done/<session_id>.json which
    # compute_savings_summary() will use as the sole source on the next call.
    if session_id:
        with contextlib.suppress(Exception):
            from atelier.core.capabilities.savings_summary import write_session_done

            write_session_done(
                session_id,
                tokens_saved=int((savings or {}).get("tokens_saved", 0) or 0),
                calls_avoided=int((savings or {}).get("calls_avoided", 0) or 0),
                saved_usd=float((savings or {}).get("saved_usd", 0.0) or 0.0),
                routing_usd=float((savings or {}).get("routing_usd", 0.0) or 0.0),
                est_cost_usd=float((stats or {}).get("est_cost_usd", 0.0) or 0.0),
            )

    # ── Always show stats (discussion and task sessions alike) ───────────────
    # If no code-editing tools were used, show stats but skip the trace reminder.
    if not _is_task_session(stats, session_aggregate):
        if stats and stats["total_tokens"] > 0:
            summary = _format_stats(stats, savings, real_cost=real_cost)
            print(json.dumps({"systemMessage": f"Session stats:\n{summary}"}))
        return 0

    # ── Code work happened: check if trace was recorded ──────────────────────
    if _trace_recorded(session_id):
        # Trace already recorded — show stats via systemMessage and allow exit.
        # Note: hookSpecificOutput is NOT valid for Stop hooks (only PreToolUse,
        # PostToolUse, UserPromptSubmit, PostToolBatch support it).
        if stats and stats["total_tokens"] > 0:
            summary = _format_stats(stats, savings, real_cost=real_cost)
            print(json.dumps({"systemMessage": f"Atelier session complete.\n{summary}"}))
        return 0

    # ── Code work done but no trace — auto-record and show stats ─────────────
    _auto_record(session_id, stats)
    if stats and stats["total_tokens"] > 0:
        summary = _format_stats(stats, savings, real_cost=real_cost)
        print(json.dumps({"systemMessage": f"Atelier: session auto-recorded.\n{summary}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
