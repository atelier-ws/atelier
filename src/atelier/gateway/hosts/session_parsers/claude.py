"""Claude Code session importer for Atelier.

Converts ~/.claude/projects/<workspace-slug>/<session-uuid>.jsonl
into redacted RawArtifacts + curated Atelier Traces.

Session layout::

    ~/.claude/projects/
        -home-pankaj-Projects-leanchain-atelier/   ← workspace slug
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
    CommandRecord,
    FileEditRecord,
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

    Example: ``-home-pankaj-Projects-leanchain-atelier``
             → ``/home/pankaj/Projects/leanchain/atelier``

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
        tool_args: dict[str, dict[str, Any] | None] = {}
        tool_results: dict[str, str] = {}
        pending_tool_uses: dict[str, dict[str, Any]] = {}
        file_index_by_tool_use_id: dict[str, int] = {}
        command_index_by_tool_use_id: dict[str, int] = {}
        files_touched: list[str | FileEditRecord] = []
        errors_seen: set[str] = set()
        commands_run: list[str | CommandRecord] = []
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
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_result":
                            continue
                        tool_use_id = str(block.get("tool_use_id") or "")
                        if not tool_use_id:
                            continue
                        pending = pending_tool_uses.get(tool_use_id) or {}
                        name = str(pending.get("name") or block.get("name") or "unknown")
                        result_text = _tool_result_text(block.get("content"))
                        if result_text:
                            tool_results[name] = result_text[:200]
                        if name == "Bash":
                            idx = command_index_by_tool_use_id.get(tool_use_id)
                            if idx is not None:
                                stdout, stderr = _tool_result_streams(
                                    block.get("content"),
                                    is_error=bool(block.get("is_error")),
                                )
                                command = str((pending.get("input") or {}).get("command") or "")[
                                    :200
                                ]
                                commands_run[idx] = CommandRecord(
                                    command=command,
                                    exit_code=block.get("exit_code"),
                                    stdout=stdout,
                                    stderr=stderr,
                                )
                        elif name in {"Write", "Edit", "MultiEdit"}:
                            idx = file_index_by_tool_use_id.get(tool_use_id)
                            if idx is not None:
                                inp = pending.get("input") or {}
                                path = str(inp.get("file_path") or inp.get("path") or "")
                                diff = _infer_file_edit_diff(name, inp, result_text)
                                if diff:
                                    files_touched[idx] = FileEditRecord(
                                        path=path,
                                        diff=diff[:4096],
                                        event="edit",
                                    )

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
                    name = str(block.get("name", "unknown"))
                    tools_called[name] = tools_called.get(name, 0) + 1
                    inp = block.get("input") or {}
                    if not isinstance(inp, dict):
                        inp = {}
                    tool_args[name] = inp or tool_args.get(name)
                    tool_use_id = str(block.get("id") or "")
                    if tool_use_id:
                        pending_tool_uses[tool_use_id] = {"name": name, "input": inp}
                    if name in _FILE_TOOLS:
                        fp = inp.get("file_path") or inp.get("path")
                        if fp:
                            fp_str = str(fp)
                            if name in {"Write", "Edit", "MultiEdit"}:
                                diff = _infer_file_edit_diff(name, inp)
                                if diff:
                                    files_touched.append(
                                        FileEditRecord(path=fp_str, diff=diff[:4096], event="edit")
                                    )
                                else:
                                    files_touched.append(fp_str)
                            else:
                                files_touched.append(fp_str)
                            if tool_use_id:
                                file_index_by_tool_use_id[tool_use_id] = len(files_touched) - 1
                    elif name == "Bash":
                        cmd = str(inp.get("command") or "").strip()
                        if cmd:
                            commands_run.append(cmd[:200])
                            if tool_use_id:
                                command_index_by_tool_use_id[tool_use_id] = len(commands_run) - 1

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
            files_touched=files_touched,
            tools_called=[
                ToolCall(
                    name=n,
                    args_hash="",
                    count=c,
                    args=tool_args.get(n),
                    result_summary=tool_results.get(n, "")[:200],
                )
                for n, c in tools_called.items()
            ],
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


def _tool_result_text(content: Any) -> str:
    """Flatten Claude tool-result content into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        if "stdout" in content or "stderr" in content:
            stdout = _tool_result_text(content.get("stdout"))
            stderr = _tool_result_text(content.get("stderr"))
            return "\n".join(part for part in (stdout, stderr) if part).strip()
        for key in ("text", "content", "output", "value"):
            if key in content:
                text = _tool_result_text(content.get(key))
                if text:
                    return text
        return ""
    if isinstance(content, list):
        parts = [_tool_result_text(item) for item in content]
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


def _tool_result_streams(content: Any, *, is_error: bool = False) -> tuple[str, str]:
    """Extract stdout/stderr text from a Claude tool-result block."""
    if isinstance(content, dict):
        stdout = _tool_result_text(content.get("stdout"))
        stderr = _tool_result_text(content.get("stderr"))
        if stdout or stderr:
            return stdout[:1024], stderr[:1024]
        text = _tool_result_text(
            content.get("content") or content.get("text") or content.get("output")
        )
        if text:
            if is_error:
                return "", text[:1024]
            return text[:1024], ""
        return "", ""
    if isinstance(content, list):
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if "stdout" in item or "stderr" in item:
                    stdout_piece = _tool_result_text(item.get("stdout"))
                    stderr_piece = _tool_result_text(item.get("stderr"))
                    if stdout_piece:
                        stdout_parts.append(stdout_piece)
                    if stderr_piece:
                        stderr_parts.append(stderr_piece)
                    continue
                kind = str(item.get("type", "")).lower()
                text = _tool_result_text(
                    item.get("text") or item.get("content") or item.get("output")
                )
                if not text:
                    text = _tool_result_text(item)
                if not text:
                    continue
                if kind in {"stderr", "error", "bash-stderr", "local-command-stderr"}:
                    stderr_parts.append(text)
                elif kind in {"stdout", "output", "bash-stdout", "local-command-stdout"}:
                    stdout_parts.append(text)
                else:
                    (stderr_parts if is_error else stdout_parts).append(text)
            else:
                text = _tool_result_text(item)
                if text:
                    (stderr_parts if is_error else stdout_parts).append(text)
        return ("\n".join(stdout_parts).strip()[:1024], "\n".join(stderr_parts).strip()[:1024])
    text = _tool_result_text(content)
    if not text:
        return "", ""
    if is_error:
        return "", text[:1024]
    return text[:1024], ""


def _looks_like_diff(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and any(
        marker in stripped
        for marker in ("diff --git", "\n--- ", "\n+++ ", "\n@@", "@@", "--- ", "+++ ")
    )


def _infer_file_edit_diff(name: str, inp: dict[str, Any], result_text: str = "") -> str:
    """Pick the best available diff-like text for a file edit tool."""
    result_text = result_text.strip()
    if result_text and _looks_like_diff(result_text):
        return result_text[:4096]
    if name == "Write":
        content = _tool_result_text(inp.get("content"))
        if content:
            return content[:4096]
    elif name == "Edit":
        path = str(inp.get("file_path") or inp.get("path") or "")
        old = _tool_result_text(inp.get("old_string"))
        new = _tool_result_text(inp.get("new_string"))
        if old or new:
            return f"--- {path}\n+++ {path}\n- {old}\n+ {new}"[:4096]
    elif name == "MultiEdit":
        edits = inp.get("edits")
        if isinstance(edits, list):
            chunks: list[str] = []
            for edit in edits:
                if not isinstance(edit, dict):
                    continue
                path = str(
                    edit.get("file_path")
                    or edit.get("path")
                    or inp.get("file_path")
                    or inp.get("path")
                    or ""
                )
                old = _tool_result_text(edit.get("old_string"))
                new = _tool_result_text(edit.get("new_string"))
                if old or new:
                    chunks.append(f"--- {path}\n+++ {path}\n- {old}\n+ {new}")
            if chunks:
                return "\n".join(chunks)[:4096]
    if result_text:
        return result_text[:4096]
    if inp:
        try:
            return json.dumps(inp, ensure_ascii=False, sort_keys=True)[:4096]
        except TypeError:
            return str(inp)[:4096]
    return ""
