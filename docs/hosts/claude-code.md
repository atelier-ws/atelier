# Claude Code Integration

Atelier integrates with Claude Code via:

1. An MCP server (primary — all V1 + V2 tools)
2. Four specialized agents (`atelier:code`, `atelier:explore`, `atelier:review`, `atelier:repair`)
3. Slash commands for status, context, savings, and evals
4. Skills that auto-trigger on task start, plan check, failure, and trace record
5. Lifecycle hooks (optional, disabled by default)

## Quick Setup (Plugin)

The `integrations/claude/plugin/` directory is the canonical Claude Code plugin. Install it from the workspace root:

```bash
make install-claude
```

Then bootstrap the engine:

```bash
cd atelier && uv sync
uv run atelier init
```

## Manual MCP Setup

If you prefer to wire the MCP server directly without the plugin:

```json
{
  "mcpServers": {
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

## Agents

The plugin provides 4 agents selectable via `claude --agent`:

| Agent             | Purpose                                                           |
| ----------------- | ----------------------------------------------------------------- |
| `atelier:code`    | Main coding agent — runs full reasoning loop (default)            |
| `atelier:explore` | Read-only investigator — retrieves context, reads files, no edits |
| `atelier:review`  | Verifier — runs `check_plan` + `run_rubric_gate` against a patch  |
| `atelier:repair`  | Repair specialist — loads run ledger, asks for rescue, verifies   |

## Slash Commands

| Command                               | Description                                                  |
| ------------------------------------- | ------------------------------------------------------------ |
| `/atelier:status [run_id]`            | Show current run plan, facts, blockers, alerts               |
| `/atelier:context <domain>`           | Resolve environment rules and required validations           |
| `/atelier:savings`                    | Calls avoided, tokens saved, rubric failures caught          |
| `/atelier:benchmark [--apply]`        | Run eval suite (dry-run by default)                          |
| `/atelier:analyze-failures`           | Cluster repeated failures; propose blocks/rubrics/eval cases |
| `/atelier:evals list\|run\|promote`   | Manage the eval suite                                        |
| `/atelier:settings [off\|shadow\|on]` | Inspect or change smart-tool mode (default: `shadow`)        |

## Skills

Skills auto-trigger based on context:

| Skill                  | Trigger                                                   |
| ---------------------- | --------------------------------------------------------- |
| `atelier-task`         | Start of every coding task — runs the full reasoning loop |
| `atelier-check-plan`   | Explicit plan validation                                  |
| `atelier-rescue`       | Invoked on repeated failures                              |
| `atelier-record-trace` | End-of-task observable summary                            |

## Hooks (Optional)

Hooks are **disabled by default**. Enable them in `integrations/claude/plugin/hooks/hooks.json` only after you're comfortable with the skills/agent flow.

What each hook does:

- **`pre_tool_use.py`** — On Edit/Write to risky paths (`shopify/`, `pdp/`, `catalog/`, etc.), require a recent successful `atelier_check_plan` in session state.
- **`post_tool_use_failure.py`** — On the second identical Bash failure (same command + error signature), tell the agent to call `atelier_rescue_failure`.
- **`stop.py`** — On session stop, ensure `atelier_record_trace` was called.

Hook state is kept at `${workspace}/.atelier/session_state.json`. No secrets, no chain-of-thought stored.

To enable hooks, edit `integrations/claude/plugin/hooks/hooks.json`:

```jsonc
// integrations/claude/plugin/hooks/hooks.json
{
  "PreToolUse": [{ "matcher": "Edit|Write|MultiEdit", "enabled": true }],
}
```

## MCP Tools Available

**V1 (core):** `atelier_get_reasoning_context`, `atelier_check_plan`, `atelier_rescue_failure`, `atelier_run_rubric_gate`, `atelier_record_trace`, `atelier_search`

**V2 (extended):** `atelier_get_run_ledger`, `atelier_update_run_ledger`, `atelier_monitor_event`, `atelier_compress_context`, `atelier_get_environment`, `atelier_get_environment_context`, `atelier_smart_read`, `atelier_smart_search`, `atelier_cached_grep`

## Reasoning Loop (Full)

The `atelier:code` agent and `atelier-task` skill enforce this loop on every task:

1. `atelier_get_reasoning_context` — inject relevant procedures
2. `atelier_check_plan` — validate plan before editing (exit 2 = abort)
3. Execute task
4. `atelier_run_rubric_gate` — verify output meets domain requirements
5. `atelier_record_trace` — record what happened (for future rescue + block extraction)
