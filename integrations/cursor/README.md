# Cursor IDE Integration

Support level: **MCP config** — MCP server registration in `.cursor/mcp.json`.

## What gets installed

| Component  | Location after install                          | Description                         |
| ---------- | ----------------------------------------------- | ----------------------------------- |
| MCP server | `~/.cursor/mcp.json` or `.cursor/mcp.json`      | Wired to `atelier-mcp --host cursor` |
| Agent rule | `.cursor/rules/atelier.mdc` (project only)      | Cursor agent instruction file        |

The installer merges an `atelier` entry into the `mcpServers` key of your Cursor
MCP config. Cursor then discovers all Atelier tools automatically.

## Install

```bash
make install
```

## Verify

```bash
make verify
```

## Source

Config source: `atelier/cursor/`
Full guide: `docs/hosts/cursor-install.md`
