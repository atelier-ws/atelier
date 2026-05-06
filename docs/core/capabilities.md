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
- `reasoning`
- `lint`
- `route`
- `rescue`
- `trace`
- `verify`
- `memory`
- `read`
- `edit`
- `search`
- `compact`
- `atelier_repo_map`

CLI-only workflows include `atelier sql inspect`, `atelier lesson inbox`, `atelier consolidation inbox`, `atelier report`, `atelier proof show`, and `atelier route contract`.
