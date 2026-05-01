# opencode Integration

Atelier integrates with opencode via its native MCP support.

## Setup

1. Install Atelier:

   ```bash
   cd atelier && uv sync && uv run atelier init
   ```

2. The MCP config is already in `opencode/opencode.json`. Reference it from your opencode config:

   ```bash
   # Option A: copy to your home opencode config
   cp atelier/opencode/opencode.json ~/.config/opencode/opencode.json

   # Option B: use workspace-local config (opencode reads opencode.json from cwd)
   cp atelier/opencode/opencode.json ./opencode.json
   ```

## MCP Config

`opencode/opencode.json`:

```json
{
  "mcp": {
    "atelier": {
      "type": "local",
      "command": ["uv", "run", "--project", "./atelier", "atelier-mcp"],
      "environment": {
        "ATELIER_WORKSPACE_ROOT": "."
      }
    }
  }
}
```

Note: `"type": "local"` is opencode's MCP server type. The command is relative to the workspace root (`.`).

## MCP Tools Available

**V1 (core):** `atelier_get_reasoning_context`, `atelier_check_plan`, `atelier_rescue_failure`, `atelier_run_rubric_gate`, `atelier_record_trace`, `atelier_search`

**V2 (extended):** `atelier_get_run_ledger`, `atelier_update_run_ledger`, `atelier_monitor_event`, `atelier_compress_context`, `atelier_get_environment`, `atelier_get_environment_context`, `atelier_smart_read`, `atelier_smart_search`, `atelier_cached_grep`

## Verify

After setup, run opencode and check the MCP server is connected:

```bash
opencode mcp list
# should show: atelier (connected)
```
