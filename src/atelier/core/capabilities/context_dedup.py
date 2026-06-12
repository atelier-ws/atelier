"""Within-session content dedup for read-style MCP tools.

When a ``read`` / ``search`` / ``grep`` / ``explore`` result is byte-identical
to content already returned earlier in the *same* session, emit a short stub
pointer instead of re-paying to put the same bytes back into the context window.
The model still has the original earlier in the transcript, so nothing is lost.

**Scope**: MCP tool-output level, within one session, exact SHA-256 hash match.
Do not confuse with ``context_compression.deduplication``, which runs inside
the compression pipeline and uses edit-distance / MinHash for *near*-duplicate
collapsing of tool outputs during sleeptime summarisation.

Correctness hinges on one invariant: in a Claude Code session, returned content
stays in context until a **compaction** (or /clear) drops it. So the only reset
signal we need is the session's ``compaction_epoch`` (bumped by the PostCompact
hook): when it changes we clear the seen-set, because the compacted summary may
no longer contain the deduped content.

Fail-open by construction: callers wrap usage in suppression and a stub is only
ever emitted on an exact hash match.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Not worth stubbing small results (also matches the cache_control threshold).
_MIN_DEDUP_CHARS = 4096


@dataclass
class _SessionDedup:
    epoch: int = 0
    calls: int = 0
    seen: dict[str, int] = field(default_factory=dict)  # content hash -> call ordinal


class ContextDedup:
    """In-memory per-session dedup registry (one MCP server == one session)."""

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionDedup] = {}

    def _session(self, session_id: str, epoch: int) -> _SessionDedup:
        st = self._sessions.get(session_id)
        if st is None or st.epoch != epoch:
            st = _SessionDedup(epoch=epoch)  # epoch change == compaction == reset
            self._sessions[session_id] = st
        return st

    def _record(self, st: _SessionDedup, content_hash: str) -> int:
        ordinal = st.seen.get(content_hash)
        if ordinal is None:
            st.calls += 1
            st.seen[content_hash] = st.calls
            ordinal = st.calls
        return ordinal

    def stub_for(
        self,
        *,
        session_id: str,
        content: str,
        epoch: int,
        force: bool,
    ) -> tuple[str, int] | None:
        """Return ``(stub_text, chars_saved)`` for a duplicate, else ``None``.

        Records the content either way (so a later non-forced identical call can
        dedup). Returns ``None`` — i.e. keep the original — when forced, when the
        content is too small to bother, or when this content is new this epoch.
        """
        if not session_id or len(content) < _MIN_DEDUP_CHARS:
            return None
        st = self._session(session_id, epoch)
        content_hash = _hash(content)
        seen_ordinal = st.seen.get(content_hash)
        if force or seen_ordinal is None:
            self._record(st, content_hash)
            return None
        stub = f"[atelier dedup] read #{seen_ordinal} — {len(content)} chars omitted. force=true re-emits."
        return stub, len(content) - len(stub)


_REGISTRY = ContextDedup()


def registry() -> ContextDedup:
    return _REGISTRY


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _session_state_path() -> Path | None:
    workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()
    root_env = os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT")
    root = Path(root_env) if root_env else Path.home() / ".atelier"
    try:
        digest = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    except OSError:
        return None
    return root / "workspaces" / digest / "session_state.json"


def current_epoch() -> int:
    """Read the session's compaction epoch from session_state (0 when absent)."""
    path = _session_state_path()
    if path is None or not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return int(data.get("compaction_epoch", 0) or 0)
    except (OSError, ValueError, TypeError):
        return 0
    return 0
