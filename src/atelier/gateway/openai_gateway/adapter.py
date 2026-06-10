"""Adapter: convert between OpenAI chat messages and Atelier NDJSON events.

Two directions:
1. openai_messages_to_atelier(): extract the last user turn + prior history
2. atelier_events_to_sse(): stream AtelierEvents as OpenAI SSE delta chunks
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from .schemas import (
    ChatCompletionChunk,
    ChatMessage,
    DeltaChoice,
    DeltaContent,
)

if TYPE_CHECKING:
    from atelier.gateway.cli.events import AtelierEvent


def openai_messages_to_atelier(
    messages: list[ChatMessage],
) -> tuple[str, list[dict]]:
    """Extract the last user message and return the prior conversation history.

    Returns:
        (last_user_text, prior_history)  — prior_history is a list of
        ``{"role": ..., "content": ...}`` dicts that can be injected into
        the runtime session so context is preserved across requests.

    Raises:
        ValueError: when the message list contains no user messages.
    """
    user_messages = [m for m in messages if m.role == "user"]
    if not user_messages:
        raise ValueError("No user message found in the request")

    last_user = user_messages[-1]

    # Normalise content: lists (multi-modal) → concatenate text parts
    def _text(msg: ChatMessage) -> str:
        if isinstance(msg.content, str):
            return msg.content
        if isinstance(msg.content, list):
            return " ".join(
                part.get("text", "") for part in msg.content if isinstance(part, dict)
            )
        return ""

    last_user_text = _text(last_user)

    # Prior history excludes the last user message; map to plain dicts
    prior: list[dict] = []
    for i, msg in enumerate(messages):
        if i == len(messages) - 1 and msg is last_user:
            break
        prior.append({"role": msg.role, "content": _text(msg)})

    return last_user_text, prior


async def atelier_events_to_sse(
    events: AsyncIterator[AtelierEvent],
    model: str,
    chunk_id: str | None = None,
) -> AsyncIterator[str]:
    """Convert a stream of AtelierEvents to OpenAI SSE chunks.

    Yields ``data: <json>\\n\\n`` lines followed by ``data: [DONE]\\n\\n``.
    Skips session-internal events (route selection, cache stats, etc.) that
    callers don't need.
    """
    if chunk_id is None:
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    created = int(time.time())
    tool_index = 0

    async for event in events:
        ev_type: str = getattr(event, "type", "")

        # ── streaming text token ─────────────────────────────────────────────
        if ev_type == "assistant.delta":
            text: str = getattr(event, "text", "")
            chunk = ChatCompletionChunk(
                id=chunk_id,
                created=created,
                model=model,
                choices=[
                    DeltaChoice(
                        index=0,
                        delta=DeltaContent(content=text),
                        finish_reason=None,
                    )
                ],
            )
            yield f"data: {chunk.model_dump_json()}\n\n"

        # ── final message → close stream ─────────────────────────────────────
        elif ev_type == "assistant.message":
            chunk = ChatCompletionChunk(
                id=chunk_id,
                created=created,
                model=model,
                choices=[
                    DeltaChoice(
                        index=0,
                        delta=DeltaContent(content=""),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        # ── tool call requested → forward as function-call delta ─────────────
        elif ev_type == "tool.requested":
            tool_id: str = getattr(event, "id", f"call_{uuid.uuid4().hex[:8]}")
            name: str = getattr(event, "name", "unknown")
            args: dict = getattr(event, "args", {}) or {}
            tool_call_delta = {
                "index": tool_index,
                "id": tool_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
            chunk = ChatCompletionChunk(
                id=chunk_id,
                created=created,
                model=model,
                choices=[
                    DeltaChoice(
                        index=0,
                        delta=DeltaContent(tool_calls=[tool_call_delta]),
                        finish_reason=None,
                    )
                ],
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
            tool_index += 1

        # ── permission / approval prompt → inject a system note as text ──────
        elif ev_type == "permission.requested":
            action: str = getattr(event, "action", "tool call")
            risk: str = getattr(event, "risk", "medium") or "medium"
            note = f"\n\n[Atelier: executing {action} ({risk} risk) autonomously]\n\n"
            chunk = ChatCompletionChunk(
                id=chunk_id,
                created=created,
                model=model,
                choices=[
                    DeltaChoice(
                        index=0,
                        delta=DeltaContent(content=note),
                        finish_reason=None,
                    )
                ],
            )
            yield f"data: {chunk.model_dump_json()}\n\n"

        # ── error → surface to caller then stop ──────────────────────────────
        elif ev_type == "error":
            message: str = getattr(event, "message", "unknown error")
            error_payload = json.dumps({"error": {"message": message, "type": "atelier_error"}})
            yield f"data: {error_payload}\n\n"
            yield "data: [DONE]\n\n"
            return

        # ── everything else is internal (routing, cache stats, etc.) → skip ──

    # Stream ended without an explicit AssistantMessage (e.g. interrupted)
    chunk = ChatCompletionChunk(
        id=chunk_id,
        created=created,
        model=model,
        choices=[DeltaChoice(index=0, delta=DeltaContent(content=""), finish_reason="stop")],
    )
    yield f"data: {chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"
