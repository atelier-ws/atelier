# opencode Integration

Atelier integrates with opencode through workspace MCP config plus a workspace-local Atelier agent profile.

## Setup

```bash
cd atelier
uv sync --all-extras
make install
make verify
```

## Installed Artifacts

- `opencode.jsonc` (or `opencode.json`) with merged `mcp.atelier`
- `.opencode/agents/atelier.md`
- `default_agent: "atelier"` in workspace config

## MCP Config Shape

```json
&#123;
  "default_agent": "atelier",
  "mcp": &#123;
    "atelier": &#123;
      "type": "local",
      "command": ["<atelier_repo>/scripts/atelier_mcp_stdio.sh"],
      "environment": &#123;
        "ATELIER_WORKSPACE_ROOT": "<workspace>"
      &#125;
    &#125;
  &#125;
&#125;
```

## MCP Tools

Canonical names:

- `get_reasoning_context`, `check_plan`, `rescue_failure`, `run_rubric_gate`, `record_trace`
- `get_run_ledger`, `update_run_ledger`, `monitor_event`, `compress_context`
- `get_environment`, `get_environment_context`
- `atelier_smart_search`, `atelier_smart_read`, `atelier_smart_edit`, `atelier_sql_inspect`, `atelier_bash_intercept`

Compatibility aliases are also available for prefixed names like `atelier_check_plan`.
