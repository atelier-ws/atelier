# Atelier MCP

Atelier's MCP server is the host-neutral way to plug procedural reasoning, monitors, rubric gates, and failure rescue into existing agent CLIs.

## Start Modes

### Local stdio

```bash
cd atelier
uv run atelier-mcp
```

### Remote service-backed mode

Set `ATELIER_MCP_MODE=remote` plus `ATELIER_SERVICE_URL` and `ATELIER_API_KEY` to route the same tool calls through the HTTP service.

## Core MCP Tools

- `atelier_get_reasoning_context`
- `atelier_check_plan`
- `atelier_rescue_failure`
- `atelier_run_rubric_gate`
- `atelier_record_trace`

## Extended MCP Tools

- `atelier_get_run_ledger`
- `atelier_update_run_ledger`
- `atelier_monitor_event`
- `atelier_compress_context`
- `atelier_get_environment`
- `atelier_get_environment_context`
- `atelier_smart_read`
- `atelier_smart_search`
- `atelier_cached_grep`

## Host Example

```json
{
  "mcpServers": {
    "atelier": {
      "command": "uv",
      "args": ["run", "atelier-mcp"],
      "env": {
        "ATELIER_ROOT": ".atelier",
        "ATELIER_WORKSPACE_ROOT": "."
      }
    }
  }
}
```

## Embedding via SDK

When you want the MCP contract in-process, use `AtelierClient.mcp()` from the Python SDK. It uses the same tool semantics but can run in a loopback mode for tests and embedded agents.
