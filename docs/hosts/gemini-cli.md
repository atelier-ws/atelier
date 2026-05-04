# Gemini CLI Integration

Atelier integrates with Gemini CLI through global `~/.gemini/settings.json` MCP wiring plus Atelier command presets.

## Setup

```bash
cd atelier
uv sync --all-extras
make install-gemini
make verify-gemini
```

## Installed Artifacts

- `~/.gemini/settings.json` (`mcpServers.atelier` merged)
- `~/.gemini/commands/atelier/status.toml`
- `~/.gemini/commands/atelier/context.toml`
- `<workspace>/GEMINI.atelier.md`

## Notes

- Gemini requires absolute paths in MCP settings.
- Re-run `make install-gemini` if the Atelier repo path changes.

## MCP Tool Names

Canonical: `check_plan`, `get_reasoning_context`, `rescue_failure`, `run_rubric_gate`, `record_trace`.

Compatibility aliases are available for prefixed names (`atelier_check_plan`, `atelier_status`, etc.).
