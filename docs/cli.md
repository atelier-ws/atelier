# CLI Reference

## `atelier`

| Command | Description |
|---------|-------------|
| `atelier tools list` | List available MCP tools |
| `atelier tools call <tool> --args <json>` | Call a tool directly |
| `atelier sessions list` | List recent sessions |
| `atelier sessions show <id>` | Show session details |
| `atelier memory search <query>` | Search archival memory |
| `atelier memory store <key> <value>` | Store a memory block |
| `atelier route --task <text>` | Route a task to the best model |
| `atelier verify --rubric <id>` | Run verification against a rubric |
| `atelier background start\|stop\|status` | Manage background daemon |
| `atelier stack up\|down\|status` | Manage dashboard stack |
| `atelier init` | Initialize Atelier in the current repo |
| `atelier --version` | Show version |

## `atelier-mcp`

MCP server that exposes Atelier capabilities as tools to any MCP host.

Run automatically by agent integrations. Start manually with:

```bash
atelier-mcp
```
