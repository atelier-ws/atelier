# Installing Atelier into opencode

**Support level**: MCP config

---

## Quick Install

```bash
make install-opencode
```

---

## What Gets Installed

| Artifact          | Location                                          |
| ----------------- | ------------------------------------------------- |
| MCP server config | `<workspace>/opencode.jsonc` (or `opencode.json`) |

The installer merges an `atelier` entry into the `mcp` key:

```json
{
  "mcp": {
    "atelier": {
      "type": "local",
      "command": ["<atelier_repo>/scripts/atelier_mcp_stdio.sh"],
      "environment": {
        "ATELIER_WORKSPACE_ROOT": "<workspace>"
      }
    }
  }
}
```

## Verify

```bash
make verify-opencode-install
```

## First Task

Start opencode in your workspace and ask:

```
use atelier to check this plan
```

## Expected Behavior

- opencode connects to Atelier via MCP stdio
- All Atelier MCP tools (`atelier_check_plan`, `atelier_status`, etc.) are available

## Troubleshooting

| Problem               | Fix                                      |
| --------------------- | ---------------------------------------- |
| MCP tools not showing | Restart opencode after install           |
| Config not found      | Check `opencode.jsonc` in workspace root |

## Uninstall

Remove the `atelier` key from `opencode.jsonc` → `mcp` section.
