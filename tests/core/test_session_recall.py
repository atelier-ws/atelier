from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from atelier.core.capabilities import session_recall


class _FakeCap:
    def __init__(self, recall_passages: list[Any] | None = None) -> None:
        self.archived: list[dict[str, Any]] = []
        self._recall_passages = recall_passages or []

    def archive(self, *, text: str, source: str, agent_id: str, source_ref: str, tags: list[str]) -> Any:
        self.archived.append(
            {"text": text, "source": source, "agent_id": agent_id, "source_ref": source_ref, "tags": tags}
        )
        return SimpleNamespace()

    def recall(self, *, agent_id: str, query: str, top_k: int, tags: list[str]) -> tuple[list[Any], Any]:
        return self._recall_passages[:top_k], SimpleNamespace()


def _transcript(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def _msg(role: str, text: str) -> dict[str, Any]:
    return {"message": {"role": role, "content": [{"type": "text", "text": text}]}}


def test_session_snippets_extracts_user_and_assistant(tmp_path: Path) -> None:
    transcript = _transcript(
        tmp_path / "s.jsonl",
        [
            _msg("user", "Please refactor the auth module thoroughly"),
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "edit"},
                        {"type": "text", "text": "I refactored the auth module and added tests"},
                    ],
                }
            },
            _msg("user", "hi"),  # below the minimum length -> skipped
        ],
    )
    snippets = session_recall._session_snippets(transcript)
    assert any("refactor the auth" in s for s in snippets)
    assert any(s.startswith("[assistant]") for s in snippets)
    assert not any(s == "[user] hi" for s in snippets)


def test_index_sessions_incremental(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    project = tmp_path / "proj"
    project.mkdir()
    transcript = _transcript(
        project / "abc.jsonl",
        [
            _msg("user", "Index this conversation about caching strategy"),
            _msg("assistant", "We chose an LRU cache with a 5 minute TTL"),
        ],
    )
    cap = _FakeCap()
    result = session_recall.index_sessions(root, paths=[transcript], capability=cap)
    assert result["sessions"] == 1
    assert result["indexed"] == 2
    assert result["skipped"] == 0
    assert cap.archived[0]["agent_id"] == "session-recall"
    assert cap.archived[0]["source"] == "trace"
    assert "project:proj" in cap.archived[0]["tags"]
    # "agent:any" lets the existing memory(op=recall) tool surface these for any agent_id
    assert "agent:any" in cap.archived[0]["tags"]

    cap2 = _FakeCap()
    result2 = session_recall.index_sessions(root, paths=[transcript], capability=cap2)
    assert result2["skipped"] == 1
    assert result2["indexed"] == 0
    assert cap2.archived == []


def test_index_reindexes_after_change(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    project = tmp_path / "proj"
    project.mkdir()
    transcript = _transcript(project / "abc.jsonl", [_msg("user", "first version of the session content")])
    session_recall.index_sessions(root, paths=[transcript], capability=_FakeCap())

    _transcript(transcript, [_msg("user", "second version of the session content now")])
    future = time.time() + 10
    os.utime(transcript, (future, future))

    cap = _FakeCap()
    result = session_recall.index_sessions(root, paths=[transcript], capability=cap)
    assert result["sessions"] == 1
    assert result["indexed"] == 1


def test_recall_maps_passages(tmp_path: Path) -> None:
    passage = SimpleNamespace(
        text="LRU cache TTL",
        source_ref="abc",
        tags=["session-recall"],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    cap = _FakeCap(recall_passages=[passage])
    out = session_recall.recall(tmp_path / ".atelier", "cache strategy", top_k=5, capability=cap)
    assert out == [
        {
            "text": "LRU cache TTL",
            "session": "abc",
            "tags": ["session-recall"],
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]


def test_recall_fail_open(tmp_path: Path) -> None:
    class _Boom:
        def recall(self, **_kwargs: Any) -> tuple[list[Any], Any]:
            raise RuntimeError("store down")

    assert session_recall.recall(tmp_path, "q", capability=_Boom()) == []


def test_empty_session_marks_state_without_indexing(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    project = tmp_path / "proj"
    project.mkdir()
    transcript = _transcript(project / "empty.jsonl", [{"message": {"role": "system", "content": "noise"}}])
    cap = _FakeCap()
    result = session_recall.index_sessions(root, paths=[transcript], capability=cap)
    assert result["sessions"] == 0
    assert result["indexed"] == 0
    assert cap.archived == []

    result2 = session_recall.index_sessions(root, paths=[transcript], capability=_FakeCap())
    assert result2["skipped"] == 1
