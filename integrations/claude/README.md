# Claude Code Integration

Support level: **Full plugin** — agents, commands, skills, hooks, and MCP server.

## What gets installed

| Component  | Location after install            | Description                               |
| ---------- | --------------------------------- | ----------------------------------------- |
| Plugin     | `~/.claude/plugins/atelier/`      | Copied from `integrations/claude/plugin/` |
| MCP server | `.mcp.json` in workspace root     | Wired to `scripts/atelier_mcp_stdio.sh`   |
| Agents     | Bundled with plugin               | `atelier:code`, `atelier:explore`, …      |
| Commands   | Bundled with plugin               | `/atelier-status`, `/atelier-context`, …  |
| Skills     | Bundled with plugin               | Auto-trigger on plan/failure/trace        |
| Hooks      | Bundled — **disabled by default** | Opt in via `ATELIER_HOOKS_ENABLED=true`   |

## Install

```bash
bash integrations/claude/install.sh
# or via Makefile:
make install-claude
```

## Verify

```bash
bash integrations/claude/verify.sh
# or:
make verify-claude
```

## Source

Plugin source: `integrations/claude/plugin/`
Full guide: `docs/hosts/claude-code-install.md`
