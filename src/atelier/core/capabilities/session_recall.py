"""All-sessions Recall — index past Claude transcripts for semantic recall.

Indexes turns from every past session into the archival vector
store, then semantic-searches across ALL sessions (not just the current one).
Reuses Atelier's embedder + archival store via ``ArchivalRecallCapability`` and
indexes incrementally (sessions unchanged since the last run are skipped).
Improvement over a naive re-index: per-session mtime state + bounded caps so a
background run stays cheap.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_AGENT_ID = "session-recall"
_TAG = "session-recall"
# "agent:any" tags each indexed passage so it can be recalled under ANY agent_id
# *within the recall store* (see SqliteMemoryStore.list_passages). Cross-store
# visibility is handled by mcp_server._memory_recall, which reads this store
# (recall.db) in addition to memory.db, so past-session context surfaces through
# the memory(op=recall) tool, not just the `atelier recall` CLI.
_SHARED_TAG = "agent:any"
_MAX_SESSIONS = 80
_MAX_SNIPPETS_PER_SESSION = 40
_MAX_SNIPPET_CHARS = 1500
_MIN_SNIPPET_CHARS = 16


def recall_dir(root: str | Path) -> Path:
    return Path(root) / "recall"


def _state_path(root: str | Path) -> Path:
    return recall_dir(root) / "index_state.json"


def _load_state(root: str | Path) -> dict[str, float]:
    try:
        data = json.loads(_state_path(root).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in data.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _save_state(root: str | Path, state: dict[str, float]) -> None:
    try:
        recall_dir(root).mkdir(parents=True, exist_ok=True)
        _state_path(root).write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def _session_snippets(path: str | Path) -> list[str]:
    """Extract user/assistant text snippets from a transcript JSONL."""
    try:
        text = Path(path).read_text("utf-8")
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = message.get("content")
        snippet = ""
        if isinstance(content, str):
            snippet = content
        elif isinstance(content, list):
            parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            snippet = "\n".join(part for part in parts if part)
        snippet = snippet.strip()
        if len(snippet) >= _MIN_SNIPPET_CHARS:
            out.append(f"[{role}] {snippet[:_MAX_SNIPPET_CHARS]}")
        if len(out) >= _MAX_SNIPPETS_PER_SESSION:
            break
    return out


def _recall_embedder_choice(root: str | Path) -> tuple[str, str]:
    """Resolve (embedder, model) for recall: env overrides plugin_settings.json."""
    choice = (os.environ.get("ATELIER_RECALL_EMBEDDER") or "").strip().lower()
    model = (os.environ.get("ATELIER_RECALL_EMBED_MODEL") or "").strip()
    if not choice or not model:
        try:
            data = json.loads((Path(root) / "plugin_settings.json").read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            choice = choice or str(data.get("recallEmbedder", "") or "").strip().lower()
            model = model or str(data.get("recallEmbedModel", "") or "").strip()
    return choice, model


def _make_recall_embedder(root: str | Path) -> Any:
    """Build the embedder for recall. Claude has no embeddings API, so it is not an
    option: codex maps to OpenAI, ollama runs locally, everything else falls back
    to the offline LocalEmbedder."""
    from atelier.infra.embeddings.factory import make_code_embedder, make_embedder

    choice, model = _recall_embedder_choice(root)
    if choice == "ollama":
        return make_code_embedder(pin="ollama", model=model or None)
    if choice in ("openai", "codex"):
        return make_embedder("openai")
    if choice == "local":
        return make_embedder("local")
    return make_embedder()


def _capability(root: str | Path) -> Any:
    # Recall indexes thousands of transcript passages; route them to a dedicated
    # global recall.db so the bulk writes never contend with the main atelier.db.
    from atelier.core.capabilities.archival_recall import ArchivalRecallCapability
    from atelier.core.foundation.redaction import redact
    from atelier.infra.storage.sqlite_memory_store import SqliteMemoryStore

    store = SqliteMemoryStore(Path(root), db_name="recall.db")
    return ArchivalRecallCapability(store, _make_recall_embedder(root), redactor=redact)


def index_sessions(
    root: str | Path,
    *,
    window_days: int = 30,
    max_sessions: int = _MAX_SESSIONS,
    paths: list[Path] | None = None,
    capability: Any | None = None,
) -> dict[str, Any]:
    """Incrementally index recent session transcripts into the recall store."""
    cap = capability or _capability(root)
    if paths is None:
        from atelier.core.capabilities.vanilla_baseline import _transcript_paths_in_window

        paths = _transcript_paths_in_window(window_days)
    state = _load_state(root)
    indexed = 0
    sessions = 0
    skipped = 0
    for path in list(paths)[:max_sessions]:
        candidate = Path(path)
        session_id = candidate.stem
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        if state.get(session_id) == mtime:
            skipped += 1
            continue
        snippets = _session_snippets(candidate)
        if not snippets:
            state[session_id] = mtime
            continue
        project = candidate.parent.name
        for snippet in snippets:
            cap.archive(
                text=snippet,
                source="trace",
                agent_id=_AGENT_ID,
                source_ref=session_id,
                tags=[_TAG, _SHARED_TAG, f"project:{project}"],
            )
            indexed += 1
        state[session_id] = mtime
        sessions += 1
    _save_state(root, state)
    return {"indexed": indexed, "sessions": sessions, "skipped": skipped}


def recall(
    root: str | Path,
    query: str,
    *,
    top_k: int = 10,
    capability: Any | None = None,
) -> list[dict[str, Any]]:
    """Semantic search across all indexed past sessions."""
    cap = capability or _capability(root)
    try:
        passages, _ = cap.recall(agent_id=_AGENT_ID, query=query, top_k=top_k, tags=[_TAG])
    except Exception:  # noqa: BLE001 - recall is best-effort
        return []
    return [
        {
            "text": passage.text,
            "session": passage.source_ref,
            "tags": list(passage.tags),
            "created_at": passage.created_at.isoformat(),
        }
        for passage in passages
    ]


def _main(argv: list[str] | None = None) -> int:
    """Detach target for the SessionStart background indexer."""
    import argparse

    parser = argparse.ArgumentParser(prog="session_recall")
    parser.add_argument("--root", required=True)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--max-sessions", type=int, default=_MAX_SESSIONS)
    namespace = parser.parse_args(argv)
    try:
        index_sessions(
            namespace.root,
            window_days=namespace.window_days,
            max_sessions=namespace.max_sessions,
        )
    except Exception:  # noqa: BLE001 - background indexing is best-effort
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    import sys

    sys.exit(_main())
