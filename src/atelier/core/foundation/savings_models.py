"""V2 context-savings instrumentation models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from atelier.core.foundation.models import _utcnow
from atelier.infra.storage.ids import make_uuid7


class ContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"cb-{make_uuid7()}")
    run_id: str
    turn_index: int
    model: str
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    naive_input_tokens: int
    lever_savings: dict[str, int]
    tool_calls: int
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = ["ContextBudget"]
