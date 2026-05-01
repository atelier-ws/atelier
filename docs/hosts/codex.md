# Codex Integration

Atelier integrates with Codex (OpenAI CLI) via:

1. An MCP server (all V1 + V2 tools)
2. Four skill packs that auto-trigger on task start, plan check, failure, and trace record
3. Reasoning block references for copy-paste into prompts

## Setup

```bash
# 1. Install the engine
cd atelier && uv sync && uv run atelier init

# 2. Copy the Codex skill pack to your Codex config directory
cp -r atelier/codex-plugin/skills ~/.codex/skills/
cp atelier/codex-plugin/mcp.json ~/.codex/mcp.json
```

Or if keeping everything in the workspace:

```bash
# Set CODEX_MCP_CONFIG to point at the workspace mcp.json
export CODEX_MCP_CONFIG=./atelier/codex-plugin/mcp.json
```

## MCP Config

`codex-plugin/mcp.json`:

```json
{
  "mcpServers": {
    "atelier": {
      "command": "atelier-mcp",
      "args": ["--root", "${workspaceRoot}/.atelier"],
      "env": {
        "ATELIER_ROOT": "${workspaceRoot}/.atelier"
      }
    }
  }
}
```

## Skill Packs

| Skill                  | Purpose                                          |
| ---------------------- | ------------------------------------------------ |
| `atelier-task`         | Start of every coding task — full reasoning loop |
| `atelier-check-plan`   | Validate a plan before executing                 |
| `atelier-rescue`       | Failure rescue flow                              |
| `atelier-record-trace` | End-of-task trace recording                      |

## MCP Tools Available

**V1 (core):** `atelier_get_reasoning_context`, `atelier_check_plan`, `atelier_rescue_failure`, `atelier_run_rubric_gate`, `atelier_record_trace`, `atelier_search`

**V2 (extended):** `atelier_get_run_ledger`, `atelier_update_run_ledger`, `atelier_monitor_event`, `atelier_compress_context`, `atelier_get_environment`, `atelier_get_environment_context`, `atelier_smart_read`, `atelier_smart_search`, `atelier_cached_grep`

## References

The `codex-plugin/references/` directory contains copy-paste text blocks for manually injecting Atelier context into Codex prompts when not using MCP:

- `codex-plugin/references/reasoning-loop.md`
- `codex-plugin/references/shopify-publish.md`
