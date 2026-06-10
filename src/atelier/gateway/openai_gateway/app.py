"""FastAPI application for the Atelier OpenAI-compatible gateway.

Wraps ``InteractiveRuntime`` in a standards-compliant HTTP server:
  - ``POST /v1/chat/completions``  — streaming or buffered completion
  - ``GET  /v1/models``            — list available Atelier models
  - ``GET  /health``               — liveness probe

Usage::

    from atelier.gateway.openai_gateway.app import create_app
    app = create_app(project_root="/path/to/project")
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from atelier.gateway.cli.runtime import InteractiveRuntime

from .adapter import atelier_events_to_sse, openai_messages_to_atelier
from .schemas import ChatCompletionRequest, ModelListResponse, ModelObject


def create_app(
    project_root: str | None = None,
    yolo: bool = True,
    model: str | None = None,
    provider: str | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    Args:
        project_root: Working directory for the Atelier runtime.
            Defaults to the process cwd.
        yolo: Auto-approve edit and shell tools for unattended endpoint use.
        model: Optional LiteLLM model override, such as
            ``bedrock/us.anthropic.claude-sonnet-4-6``.
        provider: Provider label paired with ``model`` for routing telemetry.
    """
    runtime = InteractiveRuntime(yolo=yolo, model=model, provider=provider)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await runtime.start_session(project_root)  # warm up tools in the configured workspace
        yield
        runtime.shutdown()

    app = FastAPI(
        title="Atelier OpenAI Gateway",
        version="1.0.0",
        description="OpenAI-compatible chat completions endpoint backed by Atelier's execution engine.",
        lifespan=lifespan,
    )

    # Allow all CORS origins so browser-based TUIs can connect
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routing tier → budget. Anything not in this dict is a direct model ID.
    _TIER_BUDGET: dict[str, str] = {
        "atelier": "balanced",
        "atelier-cheap": "cheap",
        "atelier-best": "best",
    }

    # ── /health ──────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ── /v1/models ───────────────────────────────────────────────────────────

    @app.get("/v1/models")
    async def list_models() -> ModelListResponse:
        from atelier.core.capabilities.providers.discovery import discover_models

        model_ids = await discover_models()
        return ModelListResponse(data=[ModelObject(id=m) for m in model_ids])

    @app.get("/v1/models/refresh")
    async def refresh_models() -> ModelListResponse:
        from atelier.core.capabilities.providers.discovery import discover_models, invalidate_cache

        invalidate_cache()
        model_ids = await discover_models()
        return ModelListResponse(data=[ModelObject(id=m) for m in model_ids])

    # ── /v1/chat/completions ─────────────────────────────────────────────────

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest) -> Any:
        if not req.messages:
            raise HTTPException(status_code=422, detail="messages must not be empty")

        try:
            last_user_text, prior_history = openai_messages_to_atelier(req.messages)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        session_id = str(uuid.uuid4())
        runtime._sessions[session_id] = prior_history

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        model = req.model or ""
        model_override = model if model else None

        events_gen = runtime.handle_user_message(
            session_id,
            last_user_text,
            model_override=model_override,
        )
        sse_gen = atelier_events_to_sse(events_gen, model=model or "atelier", chunk_id=chunk_id)

        if req.stream:
            return StreamingResponse(sse_gen, media_type="text/event-stream")

        # Buffered (non-streaming) — accumulate all tokens
        content_parts: list[str] = []
        finish_reason = "stop"
        async for line in sse_gen:
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
                choices = obj.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    token = delta.get("content") or ""
                    content_parts.append(token)
                    if choices[0].get("finish_reason"):
                        finish_reason = choices[0]["finish_reason"]
                if "error" in obj:
                    raise HTTPException(status_code=500, detail=obj["error"].get("message"))
            except (json.JSONDecodeError, KeyError):
                pass

        return JSONResponse(
            {
                "id": chunk_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "".join(content_parts),
                        },
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": None,
            }
        )

    return app
