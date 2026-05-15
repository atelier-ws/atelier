"""Compresses a run ledger into a tiny state packet for the next turn.

The compressor is the compact-state reducer in the spec. Instead of feeding
the next agent turn the entire raw transcript, we feed it:

  - the files changed (with most recent action per file)
  - the unique error fingerprints seen
  - the monitor alerts at >= medium severity
  - the current blocker, computed as the latest unresolved alert or the
    last failed command

This is enough for the next turn to make a coherent decision without
re-reading 50k tokens of tool output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atelier.infra.runtime.run_ledger import RunLedger


@dataclass
class CompactState:
    files_changed: dict[str, str] = field(default_factory=dict)
    """Mapping of file path -> last action ('edit' or 'revert')."""
    error_fingerprints: list[str] = field(default_factory=list)
    high_severity_alerts: list[str] = field(default_factory=list)
    current_blocker: str | None = None
    tool_call_count: int = 0
    total_tool_output_chars: int = 0
    recent_turns: list[str] = field(default_factory=list)
    pinned_reasonblocks: list[str] = field(default_factory=list)
    claude_md_hash: str | None = None

    def to_prompt_block(self) -> str:
        lines: list[str] = ["## Atelier compact state"]
        if self.files_changed:
            lines.append("Files touched:")
            for path, action in self.files_changed.items():
                lines.append(f"  - {action}: {path}")
        if self.error_fingerprints:
            lines.append("Distinct errors seen:")
            for fp in self.error_fingerprints:
                lines.append(f"  - {fp}")
        if self.high_severity_alerts:
            lines.append("Active alerts:")
            for msg in self.high_severity_alerts:
                lines.append(f"  - {msg}")
        if self.current_blocker:
            lines.append(f"Current blocker: {self.current_blocker}")
        if self.pinned_reasonblocks:
            lines.append("Pinned ReasonBlocks:")
            for block_id in self.pinned_reasonblocks:
                lines.append(f"  - {block_id}")
        if self.claude_md_hash:
            lines.append(f"CLAUDE.md sha256: {self.claude_md_hash}")
        if self.recent_turns:
            lines.append("Recent raw turns:")
            for turn in self.recent_turns:
                lines.append(f"  - {turn}")
        lines.append(
            f"Stats: tool_calls={self.tool_call_count} output_chars={self.total_tool_output_chars}"
        )
        return "\n".join(lines)


@dataclass
class HandoverPacket:
    session_id: str
    goal: str
    progress: str
    decisions_made: list[str] = field(default_factory=list)
    files_changed: dict[str, str] = field(default_factory=dict)
    active_errors: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)

    @classmethod
    def from_ledger(
        cls,
        ledger: RunLedger,
        compact_state: CompactState,
        *,
        workspace_root: Path | None = None,
    ) -> HandoverPacket:
        decisions = _dedupe_preserve_order(
            [
                *ledger.verified_facts,
                *(f"hypothesis accepted: {h}" for h in ledger.hypotheses_tried[-5:]),
                *(f"hypothesis rejected: {h}" for h in ledger.hypotheses_rejected[-5:]),
            ]
        )
        next_steps = _extract_next_steps(ledger)
        context = _handover_context(ledger, compact_state, workspace_root=workspace_root)
        return cls(
            session_id=ledger.session_id,
            goal=ledger.task or "Continue the current Atelier session.",
            progress=compact_state.to_prompt_block(),
            decisions_made=decisions,
            files_changed=compact_state.files_changed,
            active_errors=compact_state.error_fingerprints,
            next_steps=next_steps,
            context=context,
        )

    def to_markdown(self, *, max_chars: int = 20_000) -> str:
        lines = [
            f"## Session Handover - {self.session_id}",
            f"### Goal: {self.goal}",
            "",
            "### Progress",
            _truncate(self.progress, 4_000),
            "",
            "### Decisions made",
            *_markdown_list(self.decisions_made),
            "",
            "### Files changed",
            *_markdown_list([f"{action}: {path}" for path, action in self.files_changed.items()]),
            "",
            "### Active errors",
            *_markdown_list(self.active_errors),
            "",
            "### Next steps",
            *_markdown_list(self.next_steps),
            "",
            "### Context",
            *_markdown_list(self.context),
        ]
        return _truncate("\n".join(lines).rstrip() + "\n", max_chars)


class ContextCompressor:
    def compress(
        self,
        ledger: RunLedger,
        *,
        preserve_last_n_turns: int = 10,
        workspace_root: Path | None = None,
    ) -> CompactState:
        files: dict[str, str] = {}
        errors: list[str] = []
        seen_errors: set[str] = set()
        alerts: list[str] = []
        last_failed_cmd: str | None = None

        for event in ledger.events:
            if event.kind in ("file_edit", "file_revert"):
                path = str(event.payload.get("path", ""))
                action = "revert" if event.kind == "file_revert" else "edit"
                if path:
                    files[path] = action
            elif event.kind == "command_result":
                ok = bool(event.payload.get("ok"))
                err = str(event.payload.get("error_signature", "")).strip()
                if not ok:
                    last_failed_cmd = event.summary
                    if err and err not in seen_errors:
                        seen_errors.add(err)
                        errors.append(err)
            elif event.kind == "watchdog_alert":
                sev = str(event.payload.get("severity", ""))
                if sev in ("medium", "high"):
                    alerts.append(event.summary)

        blocker: str | None = None
        if alerts:
            blocker = alerts[-1]
        elif last_failed_cmd:
            blocker = f"last failed command: {last_failed_cmd}"

        tool_calls = [e for e in ledger.events if e.kind == "tool_call"]
        total_chars = sum(int(e.payload.get("output_chars", 0)) for e in tool_calls)

        return CompactState(
            files_changed=files,
            error_fingerprints=errors,
            high_severity_alerts=alerts,
            current_blocker=blocker,
            tool_call_count=len(tool_calls),
            total_tool_output_chars=total_chars,
            recent_turns=_recent_raw_turns(ledger, preserve_last_n_turns),
            pinned_reasonblocks=list(dict.fromkeys(ledger.active_reasonblocks)),
            claude_md_hash=_claude_md_hash(workspace_root),
        )


def _event_dict(event: Any) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        raw = event.model_dump(mode="json")
        return raw if isinstance(raw, dict) else {}
    if isinstance(event, dict):
        return event
    return {"summary": str(event)}


_RECENT_TURNS_TOKEN_BUDGET = 20_000  # ~5% of a 200k window
_CHARS_PER_TOKEN = 4  # rough estimate used for budget enforcement


def _recent_raw_turns(ledger: RunLedger, limit: int) -> list[str]:
    """Return up to *limit* recent turn-like events as readable ``[kind] summary`` strings.

    The count cap (*limit*) is also subject to a character budget so that a
    handful of very large turns (e.g. 15k-token tool outputs) do not eat the
    entire preserved context.  We walk backwards through the candidate events
    and stop as soon as either cap is hit.
    """
    if limit <= 0:
        return []
    raw_events = [_event_dict(event) for event in ledger.events]
    turn_like = [
        event
        for event in raw_events
        if str(event.get("kind", ""))
        in {"agent_message", "reasoning", "command_result", "test_result", "tool_result"}
    ]
    candidates = (turn_like or raw_events)[-limit:]

    char_budget = _RECENT_TURNS_TOKEN_BUDGET * _CHARS_PER_TOKEN
    lines: list[str] = []
    chars_used = 0
    for event in reversed(candidates):
        kind = str(event.get("kind", "event"))
        summary = str(event.get("summary", "")).strip()
        payload = event.get("payload", {})
        if kind == "command_result":
            ok = payload.get("ok", "?") if isinstance(payload, dict) else "?"
            summary = f"{'✓' if ok else '✗'} {summary}".strip()
        elif kind == "test_result":
            passed = payload.get("passed", "?") if isinstance(payload, dict) else "?"
            summary = f"{'✓' if passed else '✗'} {summary}".strip()
        line = f"[{kind}] {summary}" if summary else f"[{kind}]"
        chars_used += len(line)
        if chars_used > char_budget:
            break
        lines.append(line)
    lines.reverse()
    return lines


def _claude_md_hash(workspace_root: Path | None) -> str | None:
    roots: list[Path] = []
    if workspace_root is not None:
        roots.append(workspace_root)
    roots.append(Path.cwd())
    for root in roots:
        path = root / "CLAUDE.md"
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def _claude_md_excerpt(workspace_root: Path | None) -> str | None:
    roots: list[Path] = []
    if workspace_root is not None:
        roots.append(workspace_root)
    roots.append(Path.cwd())
    for root in roots:
        path = root / "CLAUDE.md"
        if path.is_file():
            return f"CLAUDE.md excerpt:\n{_truncate(path.read_text(encoding='utf-8', errors='replace'), 2_000)}"
    return None


def _extract_next_steps(ledger: RunLedger) -> list[str]:
    if ledger.next_required_validation:
        return [ledger.next_required_validation]
    for event in reversed(ledger.events):
        data = _event_dict(event)
        text = " ".join(
            [str(data.get("summary", "")), json.dumps(data.get("payload", {}), default=str)]
        )
        lowered = text.lower()
        if "next" in lowered or "todo" in lowered:
            return [_truncate(text, 500)]
    return ["Continue from the current compact state and resolve any active errors first."]


def _handover_context(
    ledger: RunLedger,
    compact_state: CompactState,
    *,
    workspace_root: Path | None,
) -> list[str]:
    context: list[str] = []
    if compact_state.claude_md_hash:
        context.append(f"CLAUDE.md sha256: {compact_state.claude_md_hash}")
    excerpt = _claude_md_excerpt(workspace_root)
    if excerpt:
        context.append(excerpt)
    for event in ledger.events:
        data = _event_dict(event)
        if str(data.get("kind", "")) != "file_edit":
            continue
        payload = data.get("payload", {})
        if isinstance(payload, dict) and payload.get("diff"):
            context.append(
                _truncate(
                    f"Snippet for {payload.get('path', 'unknown')}:\n{payload.get('diff', '')}",
                    1_500,
                )
            )
    context.extend(f"Recent turn: {turn}" for turn in compact_state.recent_turns[-3:])
    return context


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = item.strip()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _markdown_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None recorded."]
    return [f"- {_truncate(item, 1_000)}" for item in items]


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    head = value[: max_chars // 2].rstrip()
    tail = value[-max_chars // 2 :].lstrip()
    return f"{head}\n...<truncated>...\n{tail}"
