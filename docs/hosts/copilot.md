# VS Code Copilot Integration

Atelier integrates with VS Code Copilot Chat via the MCP (Model Context Protocol) server. This gives GitHub Copilot access to all Atelier reasoning tools inside VS Code.

## Setup

1. Install Atelier:

   ```bash
   cd atelier && uv sync && uv run atelier init
   ```

2. Copy the MCP config to VS Code:

   ```bash
   cp atelier/copilot/mcp.json .vscode/mcp.json
   ```

   Or reference it from your workspace settings.

## MCP Config

`copilot/mcp.json`:

```json
{
  "servers": {
    "atelier": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "${workspaceFolder}/atelier", "atelier-mcp"],
      "env": {
        "ATELIER_WORKSPACE_ROOT": "${workspaceFolder}"
      }
    }
  }
}
```

Note: Uses `${workspaceFolder}` (VS Code variable), not `${workspaceRoot}`.

## Using Atelier in Copilot Chat

Once configured, Copilot Chat can invoke Atelier tools via `#atelier` references:

```
Use atelier to check this plan before I execute it:
- Fetch product handle from PDP URL
- Update metafields using the handle
```

Copilot will call `atelier_check_plan` automatically.

## Copy-Paste Instructions Block

If MCP is not configured, you can manually inject Atelier's reasoning context into Copilot instructions. See:
[docs/copy-paste/copilot-instructions.md](../copy-paste/copilot-instructions.md)

## MCP Tools Available

**V1 (core):** `atelier_get_reasoning_context`, `atelier_check_plan`, `atelier_rescue_failure`, `atelier_run_rubric_gate`, `atelier_record_trace`, `atelier_search`

**V2 (extended):** `atelier_get_run_ledger`, `atelier_update_run_ledger`, `atelier_monitor_event`, `atelier_compress_context`, `atelier_get_environment`, `atelier_get_environment_context`, `atelier_smart_read`, `atelier_smart_search`, `atelier_cached_grep`
