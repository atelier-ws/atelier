# Installing Atelier into Codex CLI

**Support level**: Skills + AGENTS.md + MCP config

---

## Quick Install

```bash
make install-codex
```

---

## What Gets Installed

| Artifact                 | Location                             |
| ------------------------ | ------------------------------------ |
| Atelier skills           | `<workspace>/.codex/skills/atelier/` |
| MCP server config        | `<workspace>/.codex/mcp.json`        |
| AGENTS instruction block | `<workspace>/AGENTS.atelier.md`      |

## Verify

```bash
make verify-codex
```

## First Task

Start Codex in your workspace and use the skill:

```
use skill: atelier-check-plan
```

## Expected Behavior

- Codex loads `atelier-check-plan` skill and submits the current task plan to Atelier for scoring
- MCP tools are available for Atelier reasoning operations

## Troubleshooting

| Problem           | Fix                                                         |
| ----------------- | ----------------------------------------------------------- |
| Skill not found   | Check `.codex/skills/atelier/` — rerun `make install-codex` |
| MCP tools missing | Check `.codex/mcp.json` — confirm `atelier` entry present   |

## Uninstall

```bash
rm -rf .codex/skills/atelier/
# Remove atelier entry from .codex/mcp.json manually
# Remove or ignore AGENTS.atelier.md
```
