# Gateway Adapters

## Purpose

Host-facing integration surfaces for CLI, MCP, service, and embedded runtime adapters.

## Entry Points

- `cli.py` - primary `atelier` CLI surface
- `mcp_server.py` - MCP tool server and tool registry
- `runtime.py` - in-process runtime adapter used by product agents
- `http_api.py` - HTTP API adapter
- `remote_client.py` - service-mode remote client

## Key Contracts

- Adapters call one runtime orchestrator (`AtelierRuntimeCore`) for capability logic.
- Legacy command/tool surfaces remain available while new capability commands/tools are added.
- Host adapters are thin wrappers; policy and state logic live in core runtime/capabilities.
- Domain bundles are internal-only, loaded from built-in and local domain directories.

## Capability-driven tools and commands

- CLI: `capability list/status`, `memory summarize`, `read smart`, `edit smart`, `sql inspect`, `benchmark-runtime`, `benchmark-host`
- MCP: `atelier_reasoning_reuse`, `atelier_semantic_memory`, `atelier_loop_monitor`, `atelier_tool_supervisor`, `atelier_context_compressor`, `atelier_smart_search`, `atelier_smart_read`, `atelier_smart_edit`, `atelier_sql_inspect`

## Where to look next

- `src/atelier/core/runtime/engine.py`
- `src/atelier/core/capabilities/`
- `docs/core/runtime.md`
- `docs/core/capabilities.md`
