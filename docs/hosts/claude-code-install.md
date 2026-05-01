# Installing Atelier into Claude Code

**Support level**: Full plugin (skills, agents, hooks, MCP server)

---

## Install Modes

| Mode                          | What it installs                        | When to use                               |
| ----------------------------- | --------------------------------------- | ----------------------------------------- |
| **Marketplace** (recommended) | Full plugin via `claude plugin install` | Normal install — agents + skills + MCP    |
| **Dev** (no install)          | Plugin loaded via `--plugin-dir` flag   | Testing plugin changes without install    |
| **MCP-only** (fallback)       | `.mcp.json` entry only, no plugin       | Claude < 2.1 or when plugin install fails |

---

## Mode 1: Marketplace Install (Recommended)

```bash
make install-claude
```

This registers the repo root as a local Claude plugin source (`atelier`), installs
`atelier@atelier`, and merges the MCP server entry into your workspace
`.mcp.json`.

The script is idempotent — safe to run again after updates.

### Verify

```bash
make verify-claude
```

All checks should show `PASS`:

- `claude plugin list` shows `atelier@atelier ✔ enabled`
- Plugin source `atelier` is registered
- `.mcp.json` contains atelier server entry

### Manual steps (print-only mode)

```bash
bash scripts/install_claude.sh --print-only
```

---

## Mode 2: Dev Mode (No Install)

For testing plugin changes without a full install:

```bash
make verify-claude-plugin-dev   # validate structure + print launch command
```

This prints the command to run:

```bash
claude --plugin-dir /abs/path/to/integrations/claude/plugin
```

No `claude plugin install` or marketplace registration needed. Changes to skill
files are picked up on restart.

---

## Mode 3: MCP-Only Fallback

```bash
make install-claude-mcp
```

> **WARNING**: This is NOT the full plugin. It installs the MCP server entry in
> `.mcp.json` only. Agents and `/atelier:*` skills are NOT available.
> Use this only when `claude plugin install` is unavailable.

---

## What Gets Installed (Full Plugin)

| Artifact                   | Location                                                              |
| -------------------------- | --------------------------------------------------------------------- |
| Claude plugin (registered) | `~/.claude/plugins/cache/atelier/atelier/<version>/`                  |
| Plugin listing             | `~/.claude/plugins/installed_plugins.json`                            |
| Marketplace entry          | `~/.claude/settings.json` (known_marketplaces)                        |
| MCP server config          | `<workspace>/.mcp.json`                                               |
| Skills (slash commands)    | 7 skills in `integrations/claude/plugin/skills/`                      |
| Agents                     | `atelier:code`, `atelier:explore`, `atelier:review`, `atelier:repair` |
| Internal skills            | 4 skills in `integrations/claude/plugin/skills/atelier-*/`            |
| Hooks                      | disabled by default in `integrations/claude/plugin/hooks/hooks.json`  |

---

## First Task

Start Claude Code in your workspace and type:

```
/atelier:status
```

You should see the Atelier runtime info (run ledger, store path, version).

## Slash Commands (Skills)

All commands use the `/atelier:name` format (colon, not dash):

| Command                               | Description                                             |
| ------------------------------------- | ------------------------------------------------------- |
| `/atelier:status [run_id]`            | Show current run ledger — plan, facts, blockers, alerts |
| `/atelier:context <domain>`           | Show environment context for a domain                   |
| `/atelier:savings`                    | Report savings metrics                                  |
| `/atelier:benchmark [--apply]`        | Run eval suite (dry-run by default)                     |
| `/atelier:analyze-failures`           | Cluster recurring failures across runs                  |
| `/atelier:evals list\|run\|promote`   | Manage eval cases                                       |
| `/atelier:settings [off\|shadow\|on]` | Show or change smart-tool mode                          |

## Agents

Select from the `/agents` list in Claude Code:

| Agent             | Role                                         |
| ----------------- | -------------------------------------------- |
| `atelier:code`    | Main coding agent — full reasoning loop      |
| `atelier:explore` | Read-only repo exploration                   |
| `atelier:review`  | Verifier — plan checks + rubric gate         |
| `atelier:repair`  | Repair specialist — rescue repeated failures |

## Troubleshooting

| Problem                       | Fix                                                                     |
| ----------------------------- | ----------------------------------------------------------------------- |
| Not in `claude plugin list`   | Run `make install-claude`                                               |
| Plugin listed but not enabled | Run `claude plugin enable atelier@atelier`                              |
| Validation fails              | Run `claude plugin validate integrations/claude/plugin/`                |
| MCP tools missing             | Check `.mcp.json` in workspace root; re-run `make install-claude`       |
| Hooks firing unexpectedly     | Set `"enabled": false` in `integrations/claude/plugin/hooks/hooks.json` |
| Want to test without install  | Use dev mode: `make verify-claude-plugin-dev`                           |

## Uninstall

```bash
claude plugin uninstall atelier@atelier
# Remove atelier entry from .mcp.json manually
```
