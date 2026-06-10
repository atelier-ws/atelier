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
from contextlib import asynccontextmanager
from pathlib import Path
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
) -> FastAPI:
    """Build and return the FastAPI application.

    Args:
        project_root: Working directory for the Atelier runtime.
            Defaults to the process cwd.
        yolo: When True, auto-approves all tool permission prompts
            so the agent loop is never blocked waiting for user input.
            Defaults to True for gateway mode.
    """
    runtime = InteractiveRuntime(root=Path(project_root) if project_root else None, yolo=yolo)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await runtime.start_session()  # warm up session store, MCP servers, etc.
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

    # ── /health ──────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ── /v1/models ───────────────────────────────────────────────────────────

    @app.get("/v1/models")
    async def list_models() -> ModelListResponse:
        return ModelListResponse(
            data=[
                ModelObject(id="atelier-default"),
                ModelObject(id="atelier-auto"),
                ModelObject(id="atelier-cheap"),
                ModelObject(id="atelier-best"),
            ]
        )

    # ── /v1/chat/completions ─────────────────────────────────────────────────

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest) -> Any:
        if not req.messages:
            raise HTTPException(status_code=422, detail="messages must not be empty")

        try:
            last_user_text, prior_history = openai_messages_to_atelier(req.messages)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Each HTTP request gets a fresh session ID so conversation histories
        # from different clients are isolated inside the runtime.
        session_id = str(uuid.uuid4())
        runtime._sessions[session_id] = prior_history

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        model = req.model or "atelier-default"

        events_gen = runtime.handle_user_message(session_id, last_user_text)
        sse_gen = atelier_events_to_sse(events_gen, model=model, chunk_id=chunk_id)

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
