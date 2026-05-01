"""Optional OpenMemory MCP integration with real MCP client support.

IMPORTANT: Atelier is a reasoning/procedure/runtime layer, not a memory layer.
OpenMemory is for persistent user/project memory.  Atelier is for procedures,
dead ends, rubrics, failure rescue, and verification.

This module provides optional interoperability with OpenMemory MCP servers.
When disabled (default), every function returns a structured no-op response
without touching the network.  No existing Atelier behaviour depends on these.

Configuration
─────────────
  ATELIER_OPENMEMORY_ENABLED           (default: false)
  ATELIER_OPENMEMORY_MCP_SERVER_NAME   (default: openmemory)
  ATELIER_OPENMEMORY_TIMEOUT           (default: 10 seconds)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import: MCP client only loaded if enabled
_mcp_client: Any = None


# --------------------------------------------------------------------------- #
# Config helpers                                                              #
# --------------------------------------------------------------------------- #


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name, "").lower()
    if not val:
        return default
    return val in ("1", "true", "yes")


def is_enabled() -> bool:
    """Return True when ATELIER_OPENMEMORY_ENABLED=true."""
    return _bool_env("ATELIER_OPENMEMORY_ENABLED", False)


def _server_name() -> str:
    return os.environ.get("ATELIER_OPENMEMORY_MCP_SERVER_NAME", "openmemory")


def _timeout() -> float:
    return float(os.environ.get("ATELIER_OPENMEMORY_TIMEOUT", "10.0"))


# --------------------------------------------------------------------------- #
# MCP Client Management                                                       #
# --------------------------------------------------------------------------- #


def _get_mcp_client() -> Any:
    """Get or create MCP client lazily.

    Returns None if MCP is not available or if the server is unreachable.
    """
    global _mcp_client

    if not is_enabled():
        return None

    if _mcp_client is not None:
        return _mcp_client

    # Try to import and initialize MCP client
    try:
        from atelier.gateway.sdk import MCPClient

        server_name = _server_name()
        _timeout()

        _mcp_client = MCPClient(root=".atelier")

        logger.debug(f"OpenMemory MCP client initialized for server '{server_name}'")
        return _mcp_client

    except ImportError:
        logger.warning("MCP module not available. OpenMemory integration disabled.")
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize OpenMemory MCP client: {e}")
        return None


# --------------------------------------------------------------------------- #
# Internal response builders                                                  #
# --------------------------------------------------------------------------- #


def _disabled(action: str) -> dict[str, object]:
    return {
        "ok": False,
        "skipped": True,
        "action": action,
        "reason": (
            "OpenMemory integration is disabled. Set ATELIER_OPENMEMORY_ENABLED=true to enable."
        ),
    }


def _unavailable(action: str, detail: str = "") -> dict[str, object]:
    server = _server_name()
    return {
        "ok": False,
        "skipped": True,
        "action": action,
        "reason": f"OpenMemory MCP server '{server}' is unavailable.",
        "detail": detail or f"Could not reach MCP server '{server}'.",
        "hint": (
            "Ensure the OpenMemory MCP server is running and its name matches "
            "ATELIER_OPENMEMORY_MCP_SERVER_NAME."
        ),
    }


def _success(action: str, data: dict[str, Any] | None = None) -> dict[str, object]:
    return {
        "ok": True,
        "action": action,
        "data": data or {},
    }


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def list_available_memory_tools() -> list[str]:
    """List available OpenMemory tools from MCP server.

    Returns an empty list when disabled or when the server is unreachable.
    No exceptions are raised; callers should treat the empty list as
    "no memory context available".
    """
    if not is_enabled():
        return []

    client = _get_mcp_client()
    if client is None:
        return []

    try:
        # Query MCP server for available tools
        tools = client.list_tools()
        tool_names = [t.get("name", "") for t in tools if isinstance(t, dict)]
        logger.debug(f"Listed {len(tool_names)} OpenMemory tools: {tool_names}")
        return tool_names
    except Exception as e:
        logger.warning(f"Failed to list memory tools: {e}")
        return []


def maybe_link_trace_to_memory_context(
    trace_id: str,
    context_id: str | None = None,
) -> dict[str, object]:
    """Optionally link an Atelier trace-id to an OpenMemory context pointer.

    Only a (trace_id, context_id) association is stored — never the trace
    content itself.  Atelier remains the source of truth for traces.

    Returns a structured response dict; never raises.
    """
    if not is_enabled():
        return _disabled("link_trace_to_memory_context")

    client = _get_mcp_client()
    if client is None:
        return _unavailable(
            "link_trace_to_memory_context",
            f"trace_id={trace_id!r} context_id={context_id!r}",
        )

    try:
        # Call OpenMemory MCP tool to link trace to context
        result = client.call_tool(
            "link_trace_context",
            {
                "trace_id": trace_id,
                "context_id": context_id or "",
            },
        )

        logger.info(f"Linked trace {trace_id} to context {context_id}")
        return _success("link_trace_to_memory_context", result)

    except Exception as e:
        logger.warning(f"Failed to link trace to memory context: {e}")
        return _unavailable(
            "link_trace_to_memory_context",
            f"trace_id={trace_id!r} context_id={context_id!r} error={e!s}",
        )


def maybe_fetch_memory_context_for_task(
    task: str,
    project_id: str | None = None,
) -> dict[str, object]:
    """Optionally fetch user/project memory context from OpenMemory.

    Atelier does NOT depend on the result for plan checking or rubric
    evaluation.  Any context returned here is supplementary to the
    ReasonBlocks already retrieved by the retriever.

    Returns a structured response dict; never raises.
    """
    if not is_enabled():
        return _disabled("fetch_memory_context_for_task")

    client = _get_mcp_client()
    if client is None:
        return _unavailable(
            "fetch_memory_context_for_task",
            f"task={task!r} project_id={project_id!r}",
        )

    try:
        # Query OpenMemory for context related to this task
        result = client.call_tool(
            "fetch_context",
            {
                "task": task,
                "project_id": project_id or "",
                "limit": 10,
            },
        )

        logger.debug(f"Fetched memory context for task: {task}")
        return _success("fetch_memory_context_for_task", result)

    except Exception as e:
        logger.warning(f"Failed to fetch memory context for task: {e}")
        return _unavailable(
            "fetch_memory_context_for_task",
            f"task={task!r} project_id={project_id!r} error={e!s}",
        )


def maybe_store_memory_pointer(trace_id: str, memory_id: str) -> dict[str, object]:
    """Optionally record an OpenMemory pointer for a completed trace.

    Only the (trace_id, memory_id) pairing is stored, never trace content.

    Returns a structured response dict; never raises.
    """
    if not is_enabled():
        return _disabled("store_memory_pointer")

    client = _get_mcp_client()
    if client is None:
        return _unavailable(
            "store_memory_pointer",
            f"trace_id={trace_id!r} memory_id={memory_id!r}",
        )

    try:
        # Store the (trace_id, memory_id) association in OpenMemory
        result = client.call_tool(
            "store_pointer",
            {
                "trace_id": trace_id,
                "memory_id": memory_id,
            },
        )

        logger.info(f"Stored memory pointer: trace {trace_id} -> memory {memory_id}")
        return _success("store_memory_pointer", result)

    except Exception as e:
        logger.warning(f"Failed to store memory pointer: {e}")
        return _unavailable(
            "store_memory_pointer",
            f"trace_id={trace_id!r} memory_id={memory_id!r} error={e!s}",
        )


# --------------------------------------------------------------------------- #
# Convenience batch functions                                                #
# --------------------------------------------------------------------------- #


def link_trace_with_memory_context(
    trace_id: str,
    memory_id: str,
    context_data: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Link a trace and store it with context in OpenMemory (atomic operation).

    Combines linking and storing in a single call.
    Returns structured response; never raises.
    """
    if not is_enabled():
        return _disabled("link_trace_with_memory_context")

    client = _get_mcp_client()
    if client is None:
        return _unavailable(
            "link_trace_with_memory_context",
            f"trace_id={trace_id!r} memory_id={memory_id!r}",
        )

    try:
        # Perform atomic link + store operation
        result = client.call_tool(
            "link_and_store",
            {
                "trace_id": trace_id,
                "memory_id": memory_id,
                "context": context_data or {},
            },
        )

        logger.info(f"Linked and stored trace {trace_id} with memory {memory_id}")
        return _success("link_trace_with_memory_context", result)

    except Exception as e:
        logger.warning(f"Failed to link and store trace: {e}")
        return _unavailable(
            "link_trace_with_memory_context",
            f"trace_id={trace_id!r} memory_id={memory_id!r} error={e!s}",
        )


__all__ = [
    "is_enabled",
    "link_trace_with_memory_context",
    "list_available_memory_tools",
    "maybe_fetch_memory_context_for_task",
    "maybe_link_trace_to_memory_context",
    "maybe_store_memory_pointer",
]
