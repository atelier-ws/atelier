"""Claude Code session importer for Atelier.

Converts ~/.claude/projects/<workspace-slug>/<session-uuid>.jsonl
into redacted RawArtifacts + curated Atelier Traces.

Session layout::

    ~/.claude/projects/
        -home-pankaj-Projects-leanchain-e-commerce/   ← workspace slug
            00463f2c-c1c9-4cb4-ab4e-888a47dc4da4.jsonl  ← one file per session
            ...

Each JSONL file contains one JSON object per line:

- ``{"type":"user","message":{"role":"user","content":...},"timestamp":...}``
- ``{"type":"assistant","message":{"role":"assistant","content":[...],"usage":{...}}}``
  - content blocks include ``{"type":"tool_use","name":"Edit","input":{...}}``
- ``{"type":"ai-title","title":"..."}`` — AI-generated session title
- ``{"type":"queue-operation",...}`` — internal plumbing, skipped
- ``{"type":"progress",...}`` — tool progress, skipped

Lookup path::

    agent → curated Trace (fast, retrieval-friendly)
    human → RawArtifact content (full redacted JSONL for audit)
"""

from __future__ import annotations

import hashlib
import json
import re
import traceback as _traceback
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atelier.core.foundation.models import (
    RawArtifact,
    ToolCall,
    Trace,
)
from atelier.core.foundation.redaction import redact
from atelier.core.foundation.store import ReasoningStore

# Tools that touch files (used to build files_touched list)
_FILE_TOOLS = frozenset(
    {
        "Edit",
        "Write",
        "MultiEdit",
        "NotebookEdit",
        "Read",
        "Glob",
        "Grep",
        "FileSearch",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_ts(val: str | None) -> datetime:
    if not val:
        return _utcnow()
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return _utcnow()


def _workspace_from_slug(slug: str) -> str:
    """Decode a Claude projects folder slug back to a filesystem path.

    Claude converts the workspace path to a slug by replacing '/' with '-'
    (the leading '/' becomes a leading '-').

    Example: ``-home-pankaj-Projects-leanchain-e-commerce``
             → ``/home/pankaj/Projects/leanchain/e-commerce``

    Note: dashes in directory names are ambiguous in the slug, so this is
    best-effort.  We return the slug itself if it does not start with '-'.
    """
    if slug.startswith("-"):
        return slug.replace("-", "/", 1).replace("-", "/")
    return slug


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------


def find_claude_sessions(root: Path | None = None) -> Iterator[tuple[str, Path]]:
    """Yield ``(workspace_slug, jsonl_path)`` for every Claude Code session."""
    if root is None:
        root = Path("~/.claude/projects").expanduser()
    if not root.is_dir():
        return
    for workspace_dir in sorted(root.iterdir()):
        if not workspace_dir.is_dir():
            continue
        for jsonl in sorted(workspace_dir.glob("*.jsonl")):
            yield workspace_dir.name, jsonl


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


class ClaudeImporter:
    """Loss-preserving importer for Claude Code sessions.

    For every ``.jsonl`` session file:

    1. Write a **redacted raw artifact** (full JSONL) into
       ``<store_root>/raw/claude/<workspace_slug>/<session_id>.jsonl``.
    2. Parse the *redacted* file into a compact ``Trace`` whose
       ``raw_artifact_ids`` links back to the raw artifact.

    Nothing is thrown away beyond what Atelier's redactor strips.
    """

    def __init__(self, store: ReasoningStore) -> None:
        self.store = store

    def import_all(self, root: Path | None = None, *, force: bool = False) -> int:
        """Import all sessions.  Returns the number successfully imported."""
        count = 0
        skipped = 0
        for workspace_slug, jsonl_path in find_claude_sessions(root):
            try:
                if self.import_session(workspace_slug, jsonl_path, force=force):
                    count += 1
                else:
                    skipped += 1
            except Exception as exc:
                _traceback.print_exc()
                print(f"[atelier] skipping claude session {jsonl_path.name}: {exc}")
        if skipped > 0:
            print(f"[atelier] {skipped} sessions already imported (skipped by dedup)")
        return count

    def import_session(self, workspace_slug: str, jsonl_path: Path, *, force: bool = False) -> bool:
        """Import a single session JSONL file.  Returns True on success."""
        session_id = jsonl_path.stem  # UUID, e.g. 00463f2c-c1c9-...

        # ── Timestamp-based dedup check ────────────────────────────
        artifact_id = f"claude-{workspace_slug}-{session_id}"
        file_mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=UTC)
        if not force:
            existing = self.store.get_raw_artifact(artifact_id)
            if existing and existing.source_file_mtime and file_mtime <= existing.source_file_mtime:
                return False  # unchanged, skip

        raw_content = jsonl_path.read_text(encoding="utf-8")
        redacted = redact(raw_content)

        # ── Step 1: write redacted raw artifact ──────────────────────────────
        artifact = RawArtifact(
            id=artifact_id,
            source="claude",
            source_session_id=session_id,
            kind="session.jsonl",
            relative_path=jsonl_path.name,
            content_path=f"raw/claude/{workspace_slug}/{session_id}.jsonl",
            sha256_original=_sha256(raw_content),
            sha256_redacted=_sha256(redacted),
            byte_count_original=len(raw_content.encode("utf-8")),
            byte_count_redacted=len(redacted.encode("utf-8")),
            created_at=_utcnow(),
            source_file_mtime=file_mtime,
        )
        self.store.record_raw_artifact(artifact, redacted)

        # ── Step 2: build curated Trace from the redacted JSONL ──────────────
        tools_called: dict[str, int] = {}
        files_touched: set[str] = set()
        errors_seen: set[str] = set()
        commands_run: list[str] = []
        reasoning_snippets: list[str] = []
        task = "untitled claude session"
        title = ""
        created_at: datetime = _utcnow()
        first_ts_set = False

        for line in redacted.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            ev_type = ev.get("type", "")
            ts_str = ev.get("timestamp", "")

            # Record created_at from the first timestamped event
            if ts_str and not first_ts_set:
                created_at = _parse_ts(ts_str)
                first_ts_set = True

            if ev_type == "ai-title":
                # The real field name is "aiTitle", not "title"
                t = ev.get("aiTitle") or ev.get("title", "")
                if t:
                    title = str(t)

            elif ev_type == "last-prompt":
                # lastPrompt holds the final user message — use as task fallback
                lp = str(ev.get("lastPrompt", "")).strip()
                if (
                    lp
                    and task == "untitled claude session"
                    and not lp.startswith("<")
                    and len(lp) > 5
                ):
                    task = lp[:200]

            elif ev_type == "user":
                # Skip system-injected metadata messages (isMeta=True)
                if ev.get("isMeta"):
                    continue
                msg = ev.get("message") or {}
                content = msg.get("content", "")
                # Keep looking until we find a real user task
                if task == "untitled claude session":
                    text = _extract_user_text(content)
                    # Skip system-generated messages, thinking, commands
                    if (
                        text
                        and not text.startswith("<")
                        and not text.startswith("/")
                        and not text.startswith("[")
                        and len(text) > 5
                    ):
                        task = text[:200]

            elif ev_type == "assistant":
                msg = ev.get("message") or {}
                for block in msg.get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type", "")

                    # Extract thinking blocks (usually redacted by Atelier, but capture presence)
                    if block_type == "thinking":
                        thinking = block.get("thinking", "")
                        if thinking:
                            reasoning_snippets.append(str(thinking)[:500])

                    if block_type != "tool_use":
                        continue
                    name = block.get("name", "unknown")
                    tools_called[name] = tools_called.get(name, 0) + 1
                    inp = block.get("input") or {}
                    if name in _FILE_TOOLS:
                        fp = inp.get("file_path") or inp.get("path")
                        if fp:
                            files_touched.add(str(fp))
                    elif name == "Bash":
                        cmd = inp.get("command")
                        if cmd:
                            commands_run.append(str(cmd)[:200])

        # Use AI title as task if we couldn't extract a clean user message
        if task == "untitled claude session" and title:
            task = title

        trace = Trace(
            id=f"claude-{workspace_slug}-{session_id}",
            run_id=session_id,
            agent="claude",
            domain="coding",
            task=task,
            status="success",
            files_touched=sorted(files_touched),
            tools_called=[ToolCall(name=n, args_hash="", count=c) for n, c in tools_called.items()],
            commands_run=commands_run,
            errors_seen=sorted(errors_seen),
            validation_results=[],
            raw_artifact_ids=[artifact.id],
            reasoning=reasoning_snippets,
            created_at=created_at,
        )
        # write_json=False: raw JSONL is already stored as a RawArtifact.
        self.store.record_trace(trace, write_json=False)

        # ── Step 3: reconstruct fully populated RunLedger ────────────────────
        # Skip if ledger reconstruction fails - don't crash the main import
        try:
            from atelier.core.service.config import cfg
            from atelier.gateway.integrations.ledger_reconstructor import LedgerReconstructor

            recon = LedgerReconstructor(root=Path(cfg.atelier_root))
            led = recon.reconstruct(
                source="claude",
                session_id=session_id,
                raw_content=raw_content,
                task=task,
            )
            led.persist()
        except Exception as e:
            print(f"[atelier] failed to reconstruct ledger for {session_id}: {e}")

        return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_user_text(content: Any) -> str:
    """Extract plain text from a user message content field.

    Handles plain strings, content arrays with text blocks, and
    XML-tagged prompts like <task>...</task> or similar tags.

    Skips system-generated messages like <local-command-caveats>...,
    <ide-opened_file>..., <command-name>..., etc.
    """
    _SYSTEM_PREFIXES = (
        "<local-command-",
        "<ide_",
        "<command-",
        "<thinking>",
    )

    if isinstance(content, str):
        text = content.strip()
        # Skip system-generated messages
        if any(text.startswith(prefix) for prefix in _SYSTEM_PREFIXES):
            return ""
        # Try to extract from common XML tags like <task>, <prompt>, etc.
        xml_match = re.search(
            r"<(task|prompt|request|question)[^>]*>(.*?)</\1>",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if xml_match:
            return xml_match.group(2).strip()
        return text
    if isinstance(content, list):
        parts: list[str] = []
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                t = blk.get("text", "")
                if t:
                    # Skip system-generated messages
                    if any(t.strip().startswith(prefix) for prefix in _SYSTEM_PREFIXES):
                        continue
                    # Check for XML tags in text blocks too
                    xml_match = re.search(
                        r"<(task|prompt|request|question)[^>]*>(.*?)</\1>",
                        t,
                        re.IGNORECASE | re.DOTALL,
                    )
                    if xml_match:
                        parts.append(xml_match.group(2).strip())
                    else:
                        parts.append(str(t))
        return " ".join(parts).strip()
    return ""
