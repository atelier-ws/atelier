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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atelier.gateway.cli.runtime import InteractiveRuntime

from .adapter import run_chat_completion
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
        return await run_chat_completion(runtime, req)

    # ── MCP HTTP transport (G17, opt-in) ─────────────────────────────────────
    # Mount the streamable-HTTP/SSE MCP transport + discovery manifest only when
    # explicitly enabled. stdio remains the default; this never auto-starts.
    from atelier.core.environment import bool_env

    if bool_env("ATELIER_MCP_HTTP"):
        from atelier.gateway.adapters.mcp_http import register_mcp_http

        register_mcp_http(app)

    return app
