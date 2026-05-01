# Gemini CLI Integration

Atelier integrates with the Gemini CLI (Google) via its MCP server support.

## Setup

1. Install Atelier:

   ```bash
   cd atelier && uv sync && uv run atelier init
   ```

2. Edit `atelier/gemini-plugin/settings.json` and replace the placeholder paths with your absolute paths:

   ```json
   {
     "mcpServers": {
       "atelier": {
         "command": "uv",
         "args": [
           "run",
           "--project",
           "/absolute/path/to/atelier",
           "atelier-mcp"
         ],
         "env": {
           "ATELIER_STORE_ROOT": "/absolute/path/to/.atelier"
         }
       }
     }
   }
   ```

3. Point Gemini CLI at this settings file, or merge the `mcpServers` block into your existing `~/.gemini/settings.json`.

## MCP Config Template

`gemini-plugin/settings.json` (replace `PATH` with your absolute path):

```json
{
  "mcpServers": {
    "atelier": {
      "command": "uv",
      "args": ["run", "--project", "PATH/atelier", "atelier-mcp"],
      "env": {
        "ATELIER_STORE_ROOT": "PATH/.atelier"
      }
    }
  }
}
```

**Important:** Gemini CLI requires absolute paths in settings. Use `$(pwd)/atelier` rather than `./atelier`.

## Verify

A verification script is included:

```bash
bash atelier/gemini-plugin/verify.sh
```

This starts the MCP server and calls `tools/list` to confirm all Atelier tools are registered.

## MCP Tools Available

**V1 (core):** `atelier_get_reasoning_context`, `atelier_check_plan`, `atelier_rescue_failure`, `atelier_run_rubric_gate`, `atelier_record_trace`, `atelier_search`

**V2 (extended):** `atelier_get_run_ledger`, `atelier_update_run_ledger`, `atelier_monitor_event`, `atelier_compress_context`, `atelier_get_environment`, `atelier_get_environment_context`, `atelier_smart_read`, `atelier_smart_search`, `atelier_cached_grep`
