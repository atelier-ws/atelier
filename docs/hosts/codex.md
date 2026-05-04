# Codex Integration

Atelier integrates with Codex via workspace-local MCP config, skill packs, a preflight wrapper, and reusable task templates.

## Setup

```bash
cd atelier
uv sync --all-extras
make install-codex
make verify-codex
```

## Installed Artifacts

- `.codex/skills/atelier/`
- `.codex/mcp.json`
- `AGENTS.atelier.md`
- `bin/atelier-codex`
- `.codex/tasks/preflight.md`
- `.codex/tasks/review-repair.md`

## Wrapper Flow

```bash
./bin/atelier-codex --task "Fix checkout price mismatch" --domain beseam.shopify.publish
```

The wrapper enforces:

1. `context`
2. `check-plan`
3. Optional rubric gate via `--rubric`

## MCP Tools

Canonical names:

- `get_reasoning_context`, `check_plan`, `rescue_failure`, `run_rubric_gate`, `record_trace`
- `get_run_ledger`, `update_run_ledger`, `monitor_event`, `compress_context`
- `get_environment`, `get_environment_context`
- `atelier_smart_search`, `atelier_smart_read`, `atelier_smart_edit`, `atelier_sql_inspect`, `atelier_bash_intercept`

Compatibility aliases are also available for host prompts that use prefixed names (`atelier_check_plan`, `atelier_get_reasoning_context`, etc.).

## References

Codex task and reference templates live under `integrations/codex/`.
