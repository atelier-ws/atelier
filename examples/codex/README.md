# Codex CLI Example

## Install

```bash
cd atelier
uv sync --all-extras
make install
```

## Config

Wire Codex to the Atelier MCP server and keep host-specific behavior in `AGENTS.md`.

## Commands

```bash
uv run atelier-mcp
uv run atelier rescue --task "Fix PDP schema" --domain Agent.pdp.schema --error "availability missing"
```

## Benchmark

```bash
uv run atelier benchmark --prompt "Fix PDP schema" --json
```

## Troubleshooting

- If Codex cannot see the server, re-run `make verify`.
- If the MCP server starts but returns no context, check `ATELIER_ROOT`.
