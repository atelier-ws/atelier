from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from pydantic import Field, ValidationError

from atelier.gateway.adapters import mcp_server

if not hasattr(mcp_server, "_atelier_original_handle"):
    mcp_server._atelier_original_handle = mcp_server._handle  # type: ignore[attr-defined]
_ORIGINAL_HANDLE = mcp_server._atelier_original_handle  # type: ignore[attr-defined]


@mcp_server.mcp_tool(
    name="web_fetch",
    description=(
        "Fetch a public HTTP/HTTPS page for coding-agent research. Requests Markdown when available, "
        "converts HTML to clean Markdown by default, blocks private/local network URLs, and caches "
        "fetched content for 5 minutes."
    ),
)
def tool_web_fetch(
    url: Annotated[str, Field(description="Public HTTP/HTTPS URL to fetch.")],
    output_format: Annotated[
        Literal["auto", "markdown", "text", "html"],
        Field(description="Return format. auto prefers Markdown and converts HTML to Markdown."),
    ] = "auto",
    max_chars: Annotated[
        int,
        Field(description="Maximum returned content characters. Clamped to a safe upper bound."),
    ] = 12_000,
    timeout_s: Annotated[
        float,
        Field(description="Network timeout in seconds. Clamped to a safe upper bound."),
    ] = 20.0,
    include_meta: Annotated[
        bool,
        Field(description="Include minimal debug metadata in the internal payload."),
    ] = False,
) -> dict[str, Any]:
    """Fetch a public web page and return coding-agent-friendly content."""
    from atelier.core.capabilities.web_fetch import fetch_url

    return fetch_url(
        url,
        output_format=output_format,
        max_chars=max_chars,
        timeout_s=timeout_s,
        include_meta=include_meta,
    )


def _tool_entry(name: str) -> dict[str, Any] | None:
    spec = mcp_server.TOOLS.get(name)
    if spec is None:
        return None
    return {
        "name": name,
        "description": mcp_server._tool_description(spec),
        "inputSchema": spec.get("inputSchema", {}),
    }


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle web_fetch with a content-only render; delegate all other MCP calls."""
    method = request.get("method")
    params = request.get("params") or {}
    name = params.get("name") if isinstance(params, dict) else None
    if method == "tools/list":
        response = _ORIGINAL_HANDLE(request)
        if response is not None and "result" in response:
            tools = response["result"].setdefault("tools", [])
            names = {str(tool.get("name") or "") for tool in tools if isinstance(tool, dict)}
            web_fetch_tool = _tool_entry("web_fetch")
            if web_fetch_tool is not None and "web_fetch" not in names:
                tools.append(web_fetch_tool)
        return response
    if method != "tools/call" or name != "web_fetch":
        return _ORIGINAL_HANDLE(request)

    rid = request.get("id")
    args = params.get("arguments") or {}
    spec = mcp_server.TOOLS.get("web_fetch")
    if spec is None:
        return mcp_server._err(rid, -32601, "unknown tool: web_fetch")
    try:
        handler = cast(Any, spec["handler"])
        result = handler(args if isinstance(args, dict) else {})
        if not isinstance(result, dict):
            response_text = str(result)
            saved_tokens = 0
        else:
            response_text = str(result.get("content") or "")
            saved_tokens = mcp_server._coerce_saved_tokens(result.get("tokens_saved"))
        content_item: dict[str, Any] = {"type": "text", "text": response_text}
        if saved_tokens > 0:
            content_item["saved"] = {"tokens": int(saved_tokens), "calls": 0}
            mcp_server._append_workspace_savings("web_fetch", saved_tokens, 0, rid=str(rid))
        return mcp_server._ok(rid, {"content": [content_item]})
    except (ValueError, OSError, RuntimeError, TypeError, ValidationError) as exc:
        return mcp_server._err(rid, mcp_server._tool_error_code(exc), str(exc))


mcp_server._handle = _handle


def serve() -> None:
    mcp_server.serve()


def main() -> None:
    mcp_server.main()


if __name__ == "__main__":
    main()
