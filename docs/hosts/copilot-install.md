# Installing Atelier into VS Code Copilot

**Support level**: MCP config + Copilot instructions

---

## Quick Install

```bash
make install-copilot
```

---

## What Gets Installed

| Artifact             | Location                                      |
| -------------------- | --------------------------------------------- |
| MCP server config    | `<workspace>/.vscode/mcp.json`                |
| Copilot instructions | `<workspace>/.github/copilot-instructions.md` |

The MCP config registers Atelier as a stdio server:

```json
{
  "servers": {
    "atelier": {
      "type": "stdio",
      "command": "<atelier_repo>/scripts/atelier_mcp_stdio.sh",
      "args": [],
      "env": {
        "ATELIER_WORKSPACE_ROOT": "<workspace>"
      }
    }
  }
}
```

## Verify

```bash
make verify-copilot
```

## First Task

Open VS Code Copilot Chat and ask:

```
@atelier check this plan
```

Or use a prompt like:

```
Use atelier to check the plan for: [your task here]
```

## Expected Behavior

- Copilot Chat can invoke Atelier MCP tools
- `copilot-instructions.md` provides Atelier context to every Copilot session

## Reload Required

After install, reload the VS Code window:  
`Ctrl+Shift+P` → `Developer: Reload Window`

## Troubleshooting

| Problem               | Fix                                                                   |
| --------------------- | --------------------------------------------------------------------- |
| MCP tools not loading | Reload VS Code window; check `.vscode/mcp.json`                       |
| `code` CLI not found  | Install VS Code CLI: in VS Code, run "Install 'code' command in PATH" |

## Uninstall

Remove the `atelier` key from `.vscode/mcp.json` → `servers`.  
Remove or revert the Atelier section from `.github/copilot-instructions.md`.
