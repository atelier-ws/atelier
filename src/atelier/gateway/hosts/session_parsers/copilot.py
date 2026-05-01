"""Copilot session-state importer for Atelier.

Converts ~/.copilot/session-state/ artifacts into:

- **Redacted RawArtifacts** — the full session files (events.jsonl,
  workspace.yaml) stored verbatim after Atelier redaction.  Nothing is
  thrown away except secrets/PII that the redactor strips.
- **Curated Atelier Traces** — compact, retrieval-friendly summaries linked
  back to the raw artifacts via ``raw_artifact_ids``.

Lookup path:
    agent → curated Trace (fast, context-window-friendly)
    human → RawArtifact content (full detail for audit / debugging)
"""

from __future__ import annotations

import hashlib
import json
import traceback as _traceback
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from atelier.core.foundation.models import (
    RawArtifact,
    ToolCall,
    Trace,
    ValidationResult,
)
from atelier.core.foundation.redaction import redact
from atelier.core.foundation.store import ReasoningStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_workspace_dt(val: Any) -> datetime:
    """Parse a workspace.yaml timestamp into a timezone-aware datetime."""
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return _utcnow()
    else:
        return _utcnow()
    # yaml.safe_load may return naive datetimes — make tz-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------


def find_copilot_sessions(root: Path | None = None) -> Iterator[Path]:
    """Yield session directories that contain an events.jsonl file."""
    if root is None:
        root = Path("~/.copilot/session-state").expanduser()
    if not root.is_dir():
        return
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p / "events.jsonl").exists():
            yield p


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


class CopilotImporter:
    """Loss-preserving importer.

    For every Copilot session:
    1. Write **redacted raw artifacts** (events.jsonl + workspace.yaml) into
       ``<store_root>/raw/copilot/<session_id>/``.  The SHA-256 of both the
       original and the redacted form are recorded so you can verify nothing
       was silently lost.
    2. Parse the *redacted* events into a compact Atelier ``Trace`` whose
       ``raw_artifact_ids`` field links back to step 1.

    No data is discarded beyond what Atelier's redactor strips (secrets,
    API keys, PII).
    """

    def __init__(self, store: ReasoningStore) -> None:
        self.store = store

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def import_all(self, root: Path | None = None, *, force: bool = False) -> int:
        """Import all sessions under *root*.  Returns the number imported."""
        count = 0
        skipped = 0
        for session_dir in find_copilot_sessions(root):
            try:
                if self.import_session(session_dir, force=force):
                    count += 1
                else:
                    skipped += 1
            except Exception as exc:
                _traceback.print_exc()
                print(f"[atelier] skipping session {session_dir.name}: {exc}")
        if skipped > 0:
            print(f"[atelier] {skipped} sessions already imported (skipped by dedup)")
        return count

    def import_session(self, session_dir: Path, *, force: bool = False) -> bool:
        """Import a single session directory.  Returns True on success."""
        session_id = session_dir.name

        # ── Timestamp-based dedup check ──────────────────────────────
        artifact_id = f"copilot-{session_id}-events-jsonl"
        existing = self.store.get_raw_artifact(artifact_id)
        try:
            file_mtime = datetime.fromtimestamp(
                (session_dir / "events.jsonl").stat().st_mtime, tz=UTC
            )
        except OSError:
            file_mtime = _utcnow()
        if (
            not force
            and existing
            and existing.source_file_mtime
            and file_mtime <= existing.source_file_mtime
        ):
            return False  # unchanged, skip

        # --- workspace metadata ---
        workspace_path = session_dir / "workspace.yaml"
        if not workspace_path.exists():
            return False
        try:
            workspace_data: dict[str, Any] = (
                yaml.safe_load(workspace_path.read_text(encoding="utf-8")) or {}
            )
        except (OSError, yaml.YAMLError):
            return False

        # --- events ---
        events_path = session_dir / "events.jsonl"
        if not events_path.exists():
            return False

        # ── Step 1: write redacted raw artifacts ─────────────────────────────
        artifact_ids: list[str] = []

        events_raw = events_path.read_text(encoding="utf-8")
        redacted_events = redact(events_raw)
        workspace_raw = workspace_path.read_text(encoding="utf-8")
        redacted_workspace = redact(workspace_raw)

        for filename, raw_content, redacted_content in (
            ("events.jsonl", events_raw, redacted_events),
            ("workspace.yaml", workspace_raw, redacted_workspace),
        ):
            kind = filename
            artifact = RawArtifact(
                id=f"copilot-{session_id}-{kind.replace('.', '-')}",
                source="copilot",
                source_session_id=session_id,
                kind=kind,
                relative_path=filename,
                content_path=f"raw/copilot/{session_id}/{filename}",
                sha256_original=_sha256(raw_content),
                sha256_redacted=_sha256(redacted_content),
                byte_count_original=len(raw_content.encode("utf-8")),
                byte_count_redacted=len(redacted_content.encode("utf-8")),
                created_at=_utcnow(),
                source_file_mtime=file_mtime,
            )
            self.store.record_raw_artifact(artifact, redacted_content)
            artifact_ids.append(artifact.id)

        # ── Step 2: build curated Trace from redacted events ─────────────────
        tools_called: dict[str, int] = {}
        files_touched: set[str] = set()
        errors_seen: set[str] = set()
        commands_run: list[str] = []
        validation_results: list[ValidationResult] = []
        reasoning_snippets: list[str] = []
        task = str(workspace_data.get("summary") or "untitled copilot session")

        # Reuse already-redacted events text (no second disk read).
        for line in redacted_events.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Extract task from user.message
            if ev.get("type") == "user.message" and task.startswith("Read and follow"):
                content = ev.get("data", {}).get("content") or ""
                if content and len(content) > 20:
                    task = str(content)[:200]

            # Extract reasoning from assistant.message (chain-of-thought)
            if ev.get("type") == "assistant.message":
                data = ev.get("data") or {}
                reasoning = data.get("reasoningOpaque") or ""
                if reasoning and len(str(reasoning)) > 10:
                    reasoning_snippets.append(str(reasoning)[:500])

            self._process_event(
                ev,
                tools_called,
                files_touched,
                errors_seen,
                commands_run,
                validation_results,
                task,
            )

        trace = Trace(
            id=f"copilot-{session_id}",
            run_id=session_id,
            agent="copilot",
            domain="coding",
            task=task,
            status="success",
            files_touched=sorted(files_touched),
            tools_called=[ToolCall(name=n, args_hash="", count=c) for n, c in tools_called.items()],
            commands_run=commands_run,
            errors_seen=sorted(errors_seen),
            validation_results=validation_results,
            reasoning=reasoning_snippets,
            raw_artifact_ids=artifact_ids,
            created_at=_parse_workspace_dt(workspace_data.get("created_at")),
        )
        self.store.record_trace(trace)

        # ── Step 3: reconstruct fully populated RunLedger ────────────────────
        # Skip if ledger reconstruction fails - don't crash the main import
        try:
            from atelier.core.service.config import cfg
            from atelier.gateway.integrations.ledger_reconstructor import LedgerReconstructor

            recon = LedgerReconstructor(root=Path(cfg.atelier_root))
            led = recon.reconstruct(
                source="copilot",
                session_id=session_id,
                raw_content=events_raw,
                task=task,
            )
            led.persist()
        except Exception as e:
            print(f"[atelier] failed to reconstruct ledger for {session_id}: {e}")

        return True

    # ------------------------------------------------------------------
    # Event parsing
    # ------------------------------------------------------------------

    def _process_event(
        self,
        ev: dict[str, Any],
        tools_called: dict[str, int],
        files_touched: set[str],
        errors_seen: set[str],
        commands_run: list[str],
        validation_results: list[ValidationResult],
        task: str,
    ) -> None:
        etype = ev.get("type", "")
        data: dict[str, Any] = ev.get("data") or {}

        # Copilot: tool.execution_start
        if etype == "tool.execution_start":
            name = data.get("toolName")
            if name:
                tools_called[name] = tools_called.get(name, 0) + 1

                # Extract files/commands from arguments
                args = data.get("arguments", {})
                if name in ("edit", "create", "create_thunk", "view"):
                    path = args.get("path") or args.get("file_path") or args.get("filePath")
                    if path:
                        files_touched.add(str(path))
                elif name in ("bash", "read_bash"):
                    cmd = args.get("command")
                    if cmd:
                        commands_run.append(str(cmd)[:200])
                elif name in ("glob", "grep", "rg"):
                    pattern = args.get("pattern") or args.get("query")
                    if pattern and len(str(pattern)) < 100:
                        files_touched.add(f"{name}:{pattern}")

        elif etype == "tool_call":
            name = data.get("name")
            if name:
                tools_called[name] = tools_called.get(name, 0) + 1

        elif etype == "command_result":
            cmd = data.get("command")
            if cmd:
                commands_run.append(str(cmd))
            if not data.get("ok"):
                sig = data.get("error_signature")
                if sig:
                    errors_seen.add(str(sig))

        elif etype in ("file_edit", "file_revert"):
            path = data.get("path")
            if path:
                files_touched.add(str(path))

        elif etype == "test_result":
            name = data.get("test_id")
            if name:
                validation_results.append(
                    ValidationResult(
                        name=str(name),
                        passed=bool(data.get("passed")),
                        detail=str(data.get("detail") or ""),
                    )
                )
