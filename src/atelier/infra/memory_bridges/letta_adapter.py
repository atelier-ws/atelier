"""Optional Letta sidecar adapter and MemoryStore implementation."""

from __future__ import annotations

import os
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from atelier.core.foundation.memory_models import (
    ArchivalPassage,
    MemoryBlock,
    MemoryBlockHistory,
    MemoryRecall,
    RunMemoryFrame,
)
from atelier.infra.storage.memory_store import MemorySidecarUnavailable
from atelier.infra.storage.sqlite_memory_store import SqliteMemoryStore

_PINNED_TAG = "atelier:pinned"
_HAS_LETTA = False
LettaClient: Any = None


def _load_letta_client() -> bool:
    global LettaClient, _HAS_LETTA
    if _HAS_LETTA:
        return True
    try:
        module = import_module("letta_client")
    except ImportError:
        LettaClient = None
        _HAS_LETTA = False
        return False
    client_type = getattr(module, "LettaClient", None) or getattr(module, "Letta", None)
    if client_type is None:
        LettaClient = None
        _HAS_LETTA = False
        return False
    LettaClient = client_type
    _HAS_LETTA = True
    return True


def _sidecar_error(exc: Exception) -> MemorySidecarUnavailable:
    return MemorySidecarUnavailable(f"Letta sidecar unavailable: {exc}")


class LettaAdapter:
    """Small compatibility wrapper around the optional Letta client."""

    source = "letta"

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.url = url or os.environ.get("ATELIER_LETTA_URL", "")
        self.api_key = api_key or os.environ.get("ATELIER_LETTA_API_KEY", "")
        if client is not None:
            self.client = client
            return
        if not self.url:
            raise RuntimeError("ATELIER_LETTA_URL not set")
        if not _load_letta_client():
            raise RuntimeError("letta-client not installed; install 'atelier[memory]'")
        self.client = self._construct_client()

    @classmethod
    def is_available(cls) -> bool:
        return bool(os.environ.get("ATELIER_LETTA_URL")) and _load_letta_client()

    def upsert_block(self, block: MemoryBlock) -> dict[str, Any]:
        payload = self.block_to_letta(block)
        try:
            if hasattr(self.client, "upsert_block"):
                result = self.client.upsert_block(payload)
            elif hasattr(self.client, "blocks") and hasattr(self.client.blocks, "upsert"):
                result = self.client.blocks.upsert(**payload)
            elif hasattr(self.client, "blocks") and hasattr(self.client.blocks, "create"):
                result = self.client.blocks.create(**payload)
            else:
                raise RuntimeError("Letta client does not expose block upsert")
        except Exception as exc:  # pragma: no cover - exercised via fake client tests
            raise _sidecar_error(exc) from exc
        return self._as_mapping(result)

    def get_block(self, agent_id: str, label: str) -> dict[str, Any] | None:
        try:
            if hasattr(self.client, "get_block"):
                result = self.client.get_block(agent_id=agent_id, label=label)
            elif hasattr(self.client, "blocks") and hasattr(self.client.blocks, "get"):
                result = self.client.blocks.get(label=label, agent_id=agent_id)
            else:
                result = None
        except Exception as exc:
            raise _sidecar_error(exc) from exc
        return self._as_mapping(result) if result is not None else None

    def list_blocks(self, agent_id: str) -> list[dict[str, Any]]:
        try:
            if hasattr(self.client, "list_blocks"):
                result = self.client.list_blocks(agent_id=agent_id)
            elif hasattr(self.client, "blocks") and hasattr(self.client.blocks, "list"):
                result = self.client.blocks.list(agent_id=agent_id)
            else:
                result = []
        except Exception as exc:
            raise _sidecar_error(exc) from exc
        return [self._as_mapping(item) for item in result or []]

    def delete_block(self, block_id: str) -> None:
        try:
            if hasattr(self.client, "delete_block"):
                self.client.delete_block(block_id)
            elif hasattr(self.client, "blocks") and hasattr(self.client.blocks, "delete"):
                self.client.blocks.delete(block_id)
        except Exception as exc:
            raise _sidecar_error(exc) from exc

    def search_archival(
        self,
        *,
        agent_id: str,
        query: str,
        top_k: int,
        tags: list[str] | None,
        since: datetime | None,
    ) -> list[dict[str, Any]]:
        try:
            if hasattr(self.client, "archival_search"):
                result = self.client.archival_search(
                    agent_id=agent_id,
                    query=query,
                    top_k=top_k,
                    tags=tags or [],
                    since=since.isoformat() if since else None,
                )
            elif hasattr(self.client, "archival") and hasattr(self.client.archival, "search"):
                result = self.client.archival.search(
                    agent_id=agent_id,
                    query=query,
                    limit=top_k,
                    tags=tags or [],
                )
            else:
                raise RuntimeError("Letta client does not expose archival search")
        except Exception as exc:
            raise _sidecar_error(exc) from exc
        if isinstance(result, dict):
            raw = result.get("results", result.get("passages", []))
        else:
            raw = result
        return [self._as_mapping(item) for item in raw or []]

    def _construct_client(self) -> Any:
        assert LettaClient is not None
        try:
            return LettaClient(base_url=self.url, token=self.api_key or None)
        except TypeError:
            try:
                return LettaClient(url=self.url, api_key=self.api_key or None)
            except TypeError:
                return LettaClient(self.url, self.api_key)

    def summarize_run(
        self,
        dropped_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Delegate run summarization to the Letta sidecar.

        Returns a list of dicts compatible with ``SleeptimeChunk`` fields:
        ``start_event_index``, ``end_event_index``, ``paraphrase``.

        Raises ``RuntimeError`` on any failure so callers can fall back to the
        local summariser.
        """
        try:
            if hasattr(self.client, "summarize_run"):
                result = self.client.summarize_run(dropped_events)
                return [self._as_mapping(item) for item in result or []]
        except Exception as exc:
            raise RuntimeError(f"Letta summarize_run failed: {exc}") from exc
        raise RuntimeError("Letta client does not expose summarize_run()")

    @staticmethod
    def block_to_letta(block: MemoryBlock) -> dict[str, Any]:
        tags = (
            list(block.metadata.get("tags", []))
            if isinstance(block.metadata.get("tags"), list)
            else []
        )
        if block.pinned and _PINNED_TAG not in tags:
            tags.append(_PINNED_TAG)
        metadata = dict(block.metadata)
        metadata["atelier_agent_id"] = block.agent_id
        metadata["atelier_block_id"] = block.id
        metadata["atelier_description"] = block.description
        metadata["atelier_read_only"] = block.read_only
        return {
            "label": block.label,
            "value": block.value,
            "limit": block.limit_chars,
            "metadata": metadata,
            "tags": tags,
        }

    @staticmethod
    def letta_to_block(data: dict[str, Any], *, agent_id: str) -> MemoryBlock:
        metadata = dict(data.get("metadata") or {})
        tags = list(data.get("tags") or metadata.get("tags") or [])
        return MemoryBlock(
            id=str(metadata.get("atelier_block_id") or data.get("id") or data.get("block_id")),
            agent_id=str(metadata.get("atelier_agent_id") or agent_id),
            label=str(data.get("label", "")),
            value=str(data.get("value", "")),
            limit_chars=int(data.get("limit", data.get("limit_chars", 8000)) or 8000),
            description=str(metadata.get("atelier_description", data.get("description", ""))),
            read_only=bool(metadata.get("atelier_read_only", data.get("read_only", False))),
            metadata=metadata,
            pinned=_PINNED_TAG in tags,
        )

    @staticmethod
    def _as_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return dict(value.model_dump())
        if hasattr(value, "dict"):
            return dict(value.dict())
        return {
            key: getattr(value, key)
            for key in dir(value)
            if not key.startswith("_") and not callable(getattr(value, key))
        }


class LettaMemoryStore:
    """MemoryStore implementation backed by Letta plus a local SQLite mirror."""

    def __init__(
        self,
        root: str | Path,
        *,
        adapter: LettaAdapter | None = None,
        client: Any | None = None,
    ) -> None:
        self._local = SqliteMemoryStore(root)
        self._adapter = adapter or LettaAdapter(client=client)

    def upsert_block(self, block: MemoryBlock, *, actor: str, reason: str = "") -> MemoryBlock:
        self._adapter.upsert_block(block)
        return self._local.upsert_block(block, actor=actor, reason=reason)

    def get_block(self, agent_id: str, label: str) -> MemoryBlock | None:
        data = self._adapter.get_block(agent_id, label)
        if data is not None:
            return LettaAdapter.letta_to_block(data, agent_id=agent_id)
        return self._local.get_block(agent_id, label)

    def list_pinned_blocks(self, agent_id: str) -> list[MemoryBlock]:
        blocks = [
            LettaAdapter.letta_to_block(item, agent_id=agent_id)
            for item in self._adapter.list_blocks(agent_id)
        ]
        pinned = [block for block in blocks if block.pinned]
        return pinned or self._local.list_pinned_blocks(agent_id)

    def list_block_history(self, block_id: str, *, limit: int = 50) -> list[MemoryBlockHistory]:
        return self._local.list_block_history(block_id, limit=limit)

    def delete_block(self, block_id: str) -> None:
        self._adapter.delete_block(block_id)
        self._local.delete_block(block_id)

    def insert_passage(self, passage: ArchivalPassage) -> ArchivalPassage:
        return self._local.insert_passage(passage)

    def search_passages(
        self,
        agent_id: str,
        query: str,
        *,
        top_k: int = 5,
        tags: list[str] | None = None,
        since: datetime | None = None,
    ) -> list[ArchivalPassage]:
        results = self._adapter.search_archival(
            agent_id=agent_id,
            query=query,
            top_k=top_k,
            tags=tags,
            since=since,
        )
        passages: list[ArchivalPassage] = []
        for item in results:
            text = str(item.get("text", item.get("value", "")))
            if not text:
                continue
            passages.append(
                ArchivalPassage(
                    id=str(item.get("id", item.get("passage_id", ""))),
                    agent_id=str(item.get("agent_id", agent_id)),
                    text=text,
                    embedding=None,
                    embedding_model=str(item.get("embedding_model", "")),
                    tags=[str(tag) for tag in item.get("tags", [])],
                    source=str(item.get("source", "user")),  # type: ignore[arg-type]
                    source_ref=str(item.get("source_ref", "")),
                    dedup_hash=str(item.get("dedup_hash", item.get("id", text))),
                )
            )
        return passages[:top_k]

    def list_passages(
        self,
        agent_id: str,
        *,
        tags: list[str] | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[ArchivalPassage]:
        return self._local.list_passages(agent_id, tags=tags, since=since, limit=limit)

    def record_recall(self, recall: MemoryRecall) -> MemoryRecall:
        return self._local.record_recall(recall)

    def list_recalls(self, agent_id: str, *, limit: int = 50) -> list[MemoryRecall]:
        return self._local.list_recalls(agent_id, limit=limit)

    def write_run_frame(self, frame: RunMemoryFrame) -> None:
        self._local.write_run_frame(frame)

    def get_run_frame(self, run_id: str) -> RunMemoryFrame | None:
        return self._local.get_run_frame(run_id)


__all__ = ["LettaAdapter", "LettaMemoryStore"]
