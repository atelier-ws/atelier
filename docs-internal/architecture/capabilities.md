# Core Capabilities

Atelier core capabilities live at:

- `src/atelier/core/capabilities/`

## Capability Set

1. `context_compression`
2. `context_reuse`
3. `failure_analysis`
4. `proof_gate`
5. `quality_router`
6. `semantic_file_memory`
7. `tool_supervision`

These capabilities are internal and runtime-managed. Agent code and host adapters remain thin.

## Runtime Exposure

MCP tools:

- `context`
- `route`
- `rescue`
- `trace`
- `verify`
- `memory`
- `read`
- `edit`
- `sql`
- `search`
- `compact`
- `code`
- `shell`

CLI-only workflows include `atelier lesson inbox`, `atelier report`, and `atelier proof show`.
