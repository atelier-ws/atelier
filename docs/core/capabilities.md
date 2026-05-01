# Core Capabilities

Atelier core capabilities live at:
- `src/atelier/core/capabilities/`

## Capability Set

1. `reasoning_reuse`
2. `semantic_file_memory`
3. `loop_detection`
4. `tool_supervision`
5. `context_compression`

These capabilities are internal and runtime-managed. Agent code and host adapters remain thin.

## Runtime Exposure

CLI:
- `atelier capability list`
- `atelier capability status`

MCP tools:
- `atelier_reasoning_reuse`
- `atelier_semantic_memory`
- `atelier_loop_monitor`
- `atelier_tool_supervisor`
- `atelier_context_compressor`
- `atelier_smart_search`
- `atelier_smart_read`
- `atelier_smart_edit`
- `atelier_sql_inspect`
