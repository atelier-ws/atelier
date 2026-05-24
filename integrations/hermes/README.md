# Hermes Agent Integration

Support level: **MCP config** — MCP server registration in `$HERMES_HOME/config.yaml`.

## What gets installed

| Component  | Location after install              | Description                          |
| ---------- | ----------------------------------- | ------------------------------------ |
| MCP server | `$HERMES_HOME/config.yaml`          | Wired to `atelier-mcp --host hermes` |
| Toolset    | `platform_toolsets.cli` entry       | Ensures MCP tools are visible        |

The installer merges an `atelier` entry into the `mcp_servers` and
`platform_toolsets.cli` keys of your Hermes config. Hermes agents then discover
all Atelier tools automatically.

## Install

```bash
make install
```

## Verify

```bash
make verify
```

## Source

Config source: `atelier/hermes/`
Full guide: `docs/hosts/hermes-install.md`
