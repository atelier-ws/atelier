"""Streamable-HTTP / SSE MCP transport for Atelier (G17).

This is an *opt-in*, additive transport that runs alongside the default stdio
MCP server. It reuses the exact JSON-RPC dispatcher (``mcp_server._handle``) and
tool registry (``mcp_server.TOOLS``) so every transport exposes identical
behavior: ``initialize``, ``tools/list``, and ``tools/call`` all flow through
the same code path.

Endpoints:
  - ``POST /mcp``               — streamable-HTTP MCP: a single JSON-RPC request
                                  in, a JSON-RPC response out. When the client
                                  sends ``Accept: text/event-stream`` the same
                                  response is delivered as a one-shot SSE event.
  - ``GET  /mcp``               — opens an SSE channel (heartbeat keep-alive).
  - ``GET  /.well-known/mcp.json`` — discovery manifest (server + tool surface).

Nothing here changes ``serve()``; stdio stays the default. Mount this only when
HTTP is explicitly enabled.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from atelier.gateway.adapters import mcp_server

logger = logging.getLogger(__name__)

MCP_HTTP_PATH = "/mcp"
MCP_DISCOVERY_PATH = "/.well-known/mcp.json"


def _public_tools() -> list[dict[str, Any]]:
    """The advertised tool surface, filtered by the shared visibility policy."""
    return [
        {
            "name": name,
            "description": mcp_server._tool_description(spec),
            "inputSchema": spec.get("inputSchema", {}),
        }
        for name, spec in mcp_server.TOOLS.items()
        if mcp_server._tool_visible_to_llm(name, spec)
    ]


def discovery_manifest(*, endpoint: str = MCP_HTTP_PATH) -> dict[str, Any]:
    """Build the ``.well-known/mcp.json`` discovery document.

    Advertises the server identity, the streamable-HTTP endpoint, the protocol
    version, and the public tool names so a client can discover Atelier without
    a round-trip handshake.
    """
    tools = _public_tools()
    return {
        "name": mcp_server.SERVER_NAME,
        "version": mcp_server.SERVER_VERSION,
        "protocolVersion": mcp_server.PROTOCOL_VERSION,
        "transport": {
            "type": "streamable-http",
            "endpoint": endpoint,
        },
        "capabilities": {"tools": {}},
        "tools": [{"name": tool["name"], "description": tool["description"]} for tool in tools],
    }


def _dispatch(request_obj: dict[str, Any]) -> dict[str, Any] | None:
    """Run one JSON-RPC request through the shared dispatcher (fail-safe)."""
    try:
        return mcp_server._handle(request_obj)
    except Exception as exc:
        logging.exception("Recovered from broad exception handler")
        return mcp_server._err(request_obj.get("id"), -32603, f"internal error: {exc}")


def _sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def register_mcp_http(app: FastAPI, *, path: str = MCP_HTTP_PATH) -> FastAPI:
    """Mount the MCP HTTP/SSE transport and discovery manifest onto ``app``.

    Additive: registers new routes only; existing routes are untouched.
    """

    @app.get(MCP_DISCOVERY_PATH)
    async def mcp_discovery() -> dict[str, Any]:
        return discovery_manifest(endpoint=path)

    @app.post(path)
    async def mcp_post(request: Request) -> Any:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            return JSONResponse(mcp_server._err(None, -32700, f"parse error: {exc}"))
        if not isinstance(body, dict):
            return JSONResponse(mcp_server._err(None, -32600, "invalid request: expected a JSON object"))

        response = _dispatch(body)
        accept = request.headers.get("accept", "")
        wants_sse = "text/event-stream" in accept.lower()

        if not wants_sse:
            # Notifications (e.g. notifications/initialized) yield no response.
            if response is None:
                return JSONResponse(content=None, status_code=202)
            return JSONResponse(response)

        async def _one_shot() -> AsyncIterator[str]:
            if response is not None:
                yield _sse_event(response)

        return StreamingResponse(_one_shot(), media_type="text/event-stream")

    @app.get(path)
    async def mcp_get() -> StreamingResponse:
        async def _open_stream() -> AsyncIterator[str]:
            # Minimal keep-alive SSE channel. Server-initiated messages are not
            # used by Atelier's tool surface; the heartbeat keeps the standard
            # GET-SSE handshake satisfied for clients that probe it.
            yield ": mcp-stream-open\n\n"

        return StreamingResponse(_open_stream(), media_type="text/event-stream")

    return app


def create_mcp_http_app(*, path: str = MCP_HTTP_PATH) -> FastAPI:
    """Build a standalone FastAPI app exposing only the MCP HTTP transport."""
    app = FastAPI(
        title="Atelier MCP (HTTP)",
        version=mcp_server.SERVER_VERSION,
        description="Streamable-HTTP / SSE MCP transport for Atelier.",
    )
    return register_mcp_http(app, path=path)
