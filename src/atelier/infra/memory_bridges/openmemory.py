"""OpenMemory interoperability wrapper."""

from __future__ import annotations

import json

from atelier.gateway.integrations import openmemory as openmemory_bridge
from atelier.infra.memory_bridges.base import MemorySyncResult


class OpenMemoryAdapter:
    source = "openmemory"

    def fetch_context(self, *, task: str, project_id: str | None = None) -> MemorySyncResult:
        result = openmemory_bridge.maybe_fetch_memory_context_for_task(task, project_id)
        data = result.get("data", {})
        context = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
        return MemorySyncResult(
            ok=bool(result.get("ok", False)),
            skipped=bool(result.get("skipped", False)),
            source=self.source,
            context=context,
            detail=str(result.get("reason", "")),
        )

    def push_procedural_lesson(self, *, trace_id: str, memory_id: str) -> MemorySyncResult:
        result = openmemory_bridge.maybe_store_memory_pointer(trace_id, memory_id)
        return MemorySyncResult(
            ok=bool(result.get("ok", False)),
            skipped=bool(result.get("skipped", False)),
            source=self.source,
            detail=str(result.get("reason", "")),
        )
