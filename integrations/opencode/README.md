# opencode Integration

Support level: **MCP config** — MCP server registration in `opencode.jsonc`.

## What gets installed

| Component  | Location after install                    | Description                             |
| ---------- | ----------------------------------------- | --------------------------------------- |
| MCP server | Merged into `opencode.jsonc` in workspace | Wired to `scripts/atelier_mcp_stdio.sh` |

opencode reads `opencode.jsonc` from the workspace root. The installer merges the atelier MCP entry.

## Install

```bash
bash integrations/opencode/install.sh
# or via Makefile:
make install-opencode
```

## Verify

```bash
bash integrations/opencode/verify.sh
# or:
make verify-opencode
```

## Source

Config source: `atelier/opencode/`
Full guide: `docs/hosts/opencode-install.md`
