# VS Code Copilot Integration

Support level: **MCP + custom instructions** — MCP server registration and workspace instructions.

## What gets installed

| Component           | Location after install                       | Description                             |
| ------------------- | -------------------------------------------- | --------------------------------------- |
| MCP server          | `.vscode/mcp.json` in workspace root         | Wired to `scripts/atelier_mcp_stdio.sh` |
| Custom instructions | `.github/copilot-instructions.md` (appended) | Atelier usage instructions              |

VS Code Copilot reads MCP servers from `.vscode/mcp.json`. The installer creates or merges that file.
For full plugin features, it also appends Atelier context instructions to your copilot-instructions.md.

## Install

```bash
make install
```

For manual install (print exact steps):

```bash
bash scripts/install_copilot.sh --print-only
```

## Verify

```bash
make verify
```

## Source

Config source: `atelier/copilot/`
Full guide: `docs/hosts/copilot-install.md`
