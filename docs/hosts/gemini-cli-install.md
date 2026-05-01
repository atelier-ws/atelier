# Installing Atelier into Gemini CLI

**Support level**: MCP config (global `~/.gemini/settings.json`)

---

## Quick Install

```bash
make install-gemini
```

---

## What Gets Installed

| Artifact          | Location                           |
| ----------------- | ---------------------------------- |
| MCP server config | `~/.gemini/settings.json` (global) |

Gemini CLI requires **absolute paths** — the installer expands them at install time:

```json
{
  "mcpServers": {
    "atelier": {
      "command": "/absolute/path/to/atelier/scripts/atelier_mcp_stdio.sh",
      "args": [],
      "env": {
        "ATELIER_WORKSPACE_ROOT": "/absolute/path/to/workspace",
        "ATELIER_STORE_ROOT": "/absolute/path/to/workspace/.atelier"
      }
    }
  }
}
```

> **Note**: Do not move the atelier repository after installing. Gemini CLI uses absolute paths.  
> Re-run `make install-gemini` after any move.

## Verify

```bash
make verify-gemini
```

## First Task

Start Gemini CLI and ask:

```
use atelier to check this plan
```

## Expected Behavior

- Gemini CLI connects to Atelier MCP stdio server
- All Atelier tools (`atelier_check_plan`, `atelier_status`, etc.) are available

## Troubleshooting

| Problem                             | Fix                                                       |
| ----------------------------------- | --------------------------------------------------------- |
| `~/.gemini/settings.json` not found | `make install-gemini` creates it                          |
| MCP tools missing                   | Restart gemini CLI; check absolute paths in settings.json |
| Paths are wrong after repo move     | Re-run `make install-gemini`                              |

## Uninstall

Remove the `atelier` key from `~/.gemini/settings.json` → `mcpServers`.
