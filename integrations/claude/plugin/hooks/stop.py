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


def _workspace_key(path: str) -> str:
    import re
    from hashlib import sha256
    from pathlib import Path as _Path

    resolved = _Path(path).expanduser().resolve()
    home = _Path.home().resolve()
    try:
        parts = resolved.relative_to(home).parts
    except ValueError:
        parts = [p for p in resolved.parts if p and p != "/"]
    sanitized = [re.sub(r"[^a-zA-Z0-9.\-_]", "-", p) for p in parts if p]
    label = re.sub(r"-{2,}", "-", "-".join(sanitized)).strip("-")
    if len(label) > 120:
        label = label[:110].rstrip("-") + "--" + sha256(str(resolved).encode()).hexdigest()[:6]
    return label or sha256(str(resolved).encode()).hexdigest()[:12]


def _state_path() -> Path:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    h = _workspace_key(workspace)
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


def _sessions_root() -> Path:
    """Per-workspace store root for sessions — falls back to atelier root."""
    import re

    root = _atelier_root()
    workspace = os.environ.get("ATELIER_WORKSPACE_ROOT") or os.environ.get("CLAUDE_WORKSPACE_ROOT") or ""
    if not workspace:
        return root

    resolved = Path(workspace).expanduser().resolve()
    home = Path.home().resolve()
    try:
        parts = resolved.relative_to(home).parts
    except ValueError:
        parts = [p for p in resolved.parts if p and p != "/"]
    sanitized = [re.sub(r"[^a-zA-Z0-9._\-]", "-", p) for p in parts if p]
    label = re.sub(r"-{2,}", "-", "-".join(sanitized)).strip("-")
    if len(label) > 120:
        from hashlib import sha256

        label = label[:110].rstrip("-") + "--" + sha256(str(resolved).encode()).hexdigest()[:6]
    key = label or __import__("hashlib").sha256(str(resolved).encode()).hexdigest()[:12]
    return root / "workspaces" / key


def _write_token_event(stats: dict[str, Any], session_id: str | None = None) -> None:
    """Append a session_stats note event to the active run file."""
    if not session_id:
        # Fallback: read from workspace state (only when caller didn't supply it).
        state = _load_state()
        session_id = state.get("session_id") or state.get("active_session_id")
    if not session_id:
        return
    run_file = _sessions_root() / "sessions" / session_id / "run.json"
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
    run_file = _sessions_root() / "sessions" / session_id / "run.json"
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


def _push_public_rollup(
    session_id: str,
    saved_usd: float,
    tokens_saved: int,
    calls_avoided: int,
    turn_count: int,
    carry_usd: float = 0.0,
    carry_tokens: int = 0,
    source: str = "claude",
    est_cost_usd: float = 0.0,
) -> bool:
    """Stdlib-only public rollup push — no atelier imports, always works."""
    import hashlib
    import json as _json
    import urllib.request
    from datetime import UTC, datetime

    saved = max(0.0, float(saved_usd or 0))
    tokens = max(0, int(tokens_saved or 0))
    calls = max(0, int(calls_avoided or 0))
    turns = max(0, int(turn_count or 0))
    carry_s = max(0.0, float(carry_usd or 0))
    carry_t = max(0, int(carry_tokens or 0))
    cost = max(0.0, float(est_cost_usd or 0))
    if saved <= 0 and tokens <= 0 and calls <= 0 and turns <= 0 and carry_s <= 0 and carry_t <= 0 and cost <= 0:
        return False

    # Stable anonymous install identifier from auth.json
    try:
        import json as _j

        _auth = _j.loads((_atelier_root() / "auth.json").read_text())
        _raw_id = _auth.get("install_id") or _auth.get("userId") or "unknown"
    except Exception:  # noqa: BLE001
        _raw_id = "unknown"
    anon_id = hashlib.sha256(_raw_id.encode()).hexdigest()

    # Atelier version (best-effort)
    try:
        from importlib.metadata import version as _ver

        atelier_version = _ver("atelier")
    except Exception:  # noqa: BLE001
        atelier_version = "unknown"

    endpoint = (
        __import__("os").environ.get("ATELIER_PUBLIC_TELEMETRY_ENDPOINT", "")
        or "https://atelier.ws/api/telemetry/rollup"
    )

    payload = {
        "anon_id": anon_id,
        "session_id": str(session_id).strip(),
        "atelier_version": atelier_version,
        "source": source,
        "saved_usd": round(saved, 6),
        "tokens_saved": tokens,
        "calls_avoided": calls,
        "carry_usd": round(carry_s, 6),
        "carry_tokens": carry_t,
        "turn_count": turns,
        "est_cost_usd": round(cost, 6),
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    try:
        body = _json.dumps(payload).encode()
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"atelier/{atelier_version} (telemetry)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            ok = resp.status in (200, 201)
            logger.info(
                "public_rollup.pushed session=%s saved=%.4f carry=%.4f tokens=%d turns=%d ok=%s",
                payload["session_id"][:8],
                saved,
                carry_s,
                tokens + carry_t,
                turns,
                ok,
            )
            return ok
    except Exception as exc:  # noqa: BLE001
        logger.warning("public_rollup.failed session=%s err=%s", payload["session_id"][:8], exc)
        return False


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
    # Pre-compact usage: token totals from turns that were erased when /compact rewrote the
    # transcript. The compact.py PreCompact hook snapshots these before the overwrite; add
    # them on top of whatever the (now-truncated) transcript shows. This bridges the gap
    # between the Claude Code statusline (in-process running sum) and the stop hook
    # (transcript-derived), making reported cost match what the statusline showed.
    pre_compact = aggregate.get("pre_compact_usage")
    if isinstance(pre_compact, dict):
        stats["input_tokens"] = int(stats["input_tokens"]) + int(pre_compact.get("input_tokens", 0) or 0)
        stats["output_tokens"] = int(stats["output_tokens"]) + int(pre_compact.get("output_tokens", 0) or 0)
        stats["cache_read_tokens"] = int(stats["cache_read_tokens"]) + int(pre_compact.get("cache_read_tokens", 0) or 0)
        stats["cache_write_tokens"] = int(stats["cache_write_tokens"]) + int(
            pre_compact.get("cache_write_tokens", 0) or 0
        )
        stats["est_cost_usd"] = float(stats.get("est_cost_usd", 0.0) or 0.0) + float(
            pre_compact.get("est_cost_usd", 0.0) or 0.0
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


def _write_session_cost(
    session_id: str,
    cost_usd: float,
    total_tokens: int,
    carry_usd: float = 0.0,
    carry_tokens: int = 0,
) -> None:
    """Append a session-end cost row to savings.jsonl for historical spend tracking.

    The row has ``kind=="session_end"`` so ``_read_historical_savings`` in
    savings_summary.py can accumulate actual spend and carry for historical
    statusline frames without touching the savings totals.
    """
    if not session_id or cost_usd <= 0:
        return
    path = _sessions_root() / "sessions" / session_id / "savings.jsonl"
    if not path.exists():
        return  # no savings sidecar → session produced no MCP events; skip
    row = {
        "kind": "session_end",
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "est_cost_usd": round(cost_usd, 6),
        "total_tokens": int(total_tokens or 0),
        "carry_usd": round(carry_usd, 6),
        "carry_tokens": int(carry_tokens or 0),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


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
    # One dense line per metric. Cost is omitted when negligible (<$0.01) -- the
    # exact sub-cent figure is noise. tokens stays a single line with the 4
    # Anthropic billing categories (cW/cR weighted by their real $ prominence).
    tokens_line = (
        f"tokens: {_fmt_tok(fresh_in)} in ({_fmt_tok(inp)} new + {_fmt_tok(cache_write)} cW) · "
        f"{_fmt_tok(cache_read)} cR · {_fmt_tok(out)} out · {_fmt_tok(total)} total"
    )
    lines = [activity, tokens_line]
    if cost >= 0.01:
        lines.append(f"{cost_prefix}${cost:.4f}")

    # Always show savings — even at $0 — so the stop output shape is stable
    # across sessions. No display-time clamps; each saving was priced at the
    # model in use when it was emitted, so we trust the numbers as-is.
    savings = savings or {}
    saved_usd = float(savings.get("saved_usd", 0.0) or 0.0)
    tokens_saved = int(savings.get("tokens_saved", 0) or 0)
    calls_avoided = int(savings.get("calls_avoided", 0) or 0)
    routing_usd = float(savings.get("routing_usd", 0.0) or 0.0)
    carry_usd = float(savings.get("carry_usd", 0.0) or 0.0)
    carry_tokens = int(savings.get("carry_tokens", 0) or 0)
    savings_line = f"savings: ${saved_usd:.4f} · {tokens_saved:,} tok · {calls_avoided} calls avoided"
    if carry_usd > 0:
        carry_tokens_str = f"/{carry_tokens:,} tok" if carry_tokens > 0 else ""
        savings_line += f" · carry ${carry_usd:.4f}{carry_tokens_str}"
    if routing_usd > 0:
        savings_line += f" · routing ${routing_usd:.4f}"
    lines.append(savings_line)

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
            _write_token_event(stats, session_id)

    # ── Load per-session savings breakdown (before writing session_end so carry is persisted)
    savings: dict[str, Any] | None = None
    with contextlib.suppress(Exception):
        savings = _load_session_savings(session_id)

    # Public rollup — always-on stdlib push (no atelier import, never fails silently).
    _s = savings or {}
    _push_public_rollup(
        session_id=session_id,
        saved_usd=float(_s.get("saved_usd", 0.0) or 0.0),
        tokens_saved=int(_s.get("tokens_saved", 0) or 0),
        calls_avoided=int(_s.get("calls_avoided", 0) or 0),
        carry_usd=float(_s.get("carry_usd", 0.0) or 0.0),
        carry_tokens=int(_s.get("carry_tokens", 0) or 0),
        turn_count=int((stats or {}).get("turns", 0) or 0),
        source="claude",
        est_cost_usd=float((stats or {}).get("est_cost_usd", 0.0) or 0.0),
    )

    # ── Write session cost + carry to savings.jsonl for historical 7d/30d spend tracking
    if stats and stats.get("est_cost_usd", 0) > 0:
        with contextlib.suppress(Exception):
            _write_session_cost(
                session_id,
                float(stats["est_cost_usd"]),
                int(stats.get("total_tokens", 0)),
                carry_usd=float((savings or {}).get("carry_usd", 0.0) or 0.0),
                carry_tokens=int((savings or {}).get("carry_tokens", 0) or 0),
            )

    # ── Enrich run file with session title + full prompt history ─────────────────────
    with contextlib.suppress(Exception):
        session_title = _extract_session_title(transcript_path)
        user_prompts = _extract_user_prompts(transcript_path)
        if session_title or user_prompts:
            _write_session_enrichment(session_id, session_title, user_prompts, transcript_path)

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
