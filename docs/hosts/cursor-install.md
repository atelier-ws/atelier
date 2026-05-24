# Installing Atelier into Cursor IDE

**Support level**: MCP server (stdio JSON-RPC)

---

## Quick Install

```bash
make install
```

By default this installs Cursor user/global MCP config. For a project-local install:

```bash
bash scripts/install_cursor.sh --workspace /path/to/workspace
```

---

## What Gets Installed

| Artifact          | Global install                         | `--workspace DIR` install              |
| ----------------- | -------------------------------------- | -------------------------------------- |
| MCP server config | `~/.cursor/mcp.json`                   | `<workspace>/.cursor/mcp.json`         |
| Rules (optional)  | (none — Cursor rules are project-only) | `<workspace>/.cursor/rules/atelier.mdc`|

The installer merges an `atelier` entry into the `mcpServers` key:

```json
{
  "mcpServers": {
    "atelier": {
      "type": "stdio",
      "command": "atelier-mcp",
      "args": ["--host", "cursor"]
    }
  }
}
```

For global installs, Cursor's working directory for MCP subprocesses is **not** the
workspace root, so we inject `args` that handle workspace resolution automatically.
The `--host cursor` flag tells Atelier's MCP server which agent environment it's
running in, enabling correct trace labeling.

### Cursor Rules (`.cursor/rules/atelier.mdc`)

Cursor's rules system is project-scoped — there is no global equivalent. When
installing project-locally, the installer creates a rules file that tells Cursor's
agent to prefer Atelier's MCP tools:

```markdown
---
description: Atelier reasoning context usage guide — when to use which tool
alwaysApply: true
---

Use Atelier's `context` tool at the start of every task to retrieve relevant
reasoning blocks. After completing a task, record a trace with the `trace` tool.
On repeated failures, use the `rescue` tool to get recovery hints.
Prefer Atelier tools over native `Read`, `Grep`, and `Bash` for code insight.
```

---

## Verify

```bash
make verify
```

Or manually:

```bash
atelier-mcp --host cursor --version
```

---

## Expected Behavior

- Cursor connects to the Atelier MCP server via stdio on startup
- Atelier tools (`context`, `trace`, `rescue`, `verify`, `memory`, `read`, `edit`, `sql`, `search`, `compact`, `shell`, `code`) appear in Cursor's tool list
- With `ATELIER_DEV_MODE=1`, all tools are fully visible and active
- `trace` remains the stable observable recording surface
- Cursor's agent uses Atelier's `context` tool for task-level reasoning

---

## Troubleshooting

| Problem                          | Fix                                                                                |
| -------------------------------- | ---------------------------------------------------------------------------------- |
| "atelier-mcp: command not found" | Run `pip install atelier-runtime` or reinstall via `make install`                  |
| MCP tools not showing up         | Restart Cursor completely (Cmd+Shift+P → "Developer: Reload Window")              |
| Tools fail with "host not cursor" | Check `~/.cursor/mcp.json` has `--host cursor` in args                             |
| Cursor workspace not detected    | For global installs, ensure you open a folder/workspace in Cursor before using MCP |

---

## Uninstall

```bash
atelier uninstall
```

Or manually remove the `atelier` entry from `~/.cursor/mcp.json` and delete
`.cursor/rules/atelier.mdc` if present.
