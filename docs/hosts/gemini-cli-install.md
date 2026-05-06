# Installing Atelier into Gemini CLI

**Support level**: MCP config + custom command presets

---

## Quick Install

```bash
make install
```

By default this installs Gemini user/global settings. For project-local Gemini artifacts:

```bash
bash scripts/install_gemini.sh --workspace /path/to/workspace
```

---

## What Gets Installed

| Artifact          | Global install                      | `--workspace DIR` install                  |
| ----------------- | ----------------------------------- | ------------------------------------------ |
| MCP server config | `~/.gemini/settings.json`           | `<workspace>/.gemini/settings.json`        |
| Custom commands   | `~/.gemini/commands/atelier/*.toml` | `<workspace>/.gemini/commands/atelier/*.toml` |
| Persona context   | `~/.gemini/GEMINI.md`               | `<workspace>/GEMINI.md`                    |

Gemini CLI requires **absolute paths** — the installer expands them at install time:

```json
&#123;
  "mcpServers": &#123;
    "atelier": &#123;
      "command": "/absolute/path/to/atelier/scripts/atelier_mcp_stdio.sh",
      "args": [],
      "env": &#123;
        "ATELIER_WORKSPACE_ROOT": "/absolute/path/to/workspace",
        "ATELIER_ROOT": "/absolute/path/to/workspace/.atelier"
      &#125;
    &#125;
  &#125;
&#125;
```

> **Note**: Do not move the atelier repository after installing. Gemini CLI uses absolute paths.  
> Re-run `make install` after any move.

## Verify

```bash
make verify
```

## First Task

Start Gemini CLI and ask:

```
use atelier to check this plan
```

## Expected Behavior

- Gemini CLI connects to Atelier MCP stdio server
- All Atelier tools (`lint`, `atelier_status`, etc.) are available
- Custom command presets (`/atelier:status`, `/atelier:context`) are installed

## Troubleshooting

| Problem                             | Fix                                                       |
| ----------------------------------- | --------------------------------------------------------- |
| `~/.gemini/settings.json` not found | `make install` creates it                                 |
| MCP tools missing                   | Restart gemini CLI; check absolute paths in settings.json |
| Paths are wrong after repo move     | Re-run `make install`                                     |

## V2 Tools — Memory, Context Savings, and Lesson Pipeline

All V2 tools are available via the Atelier MCP server. These are **Atelier augmentations** — Gemini CLI native tools remain the primary interface.

| Tool                          | Boundary             | Description                                               |
| ----------------------------- | -------------------- | --------------------------------------------------------- |
| `memory` | Atelier augmentation | Store named value in agent memory                         |
| `memory`    | Atelier augmentation | Retrieve named memory block                               |
| `memory`       | Atelier augmentation | FTS + vector search over archival memory                  |
| `memory`      | Atelier augmentation | Persist text passage to archival memory                   |
| `memory`      | Atelier augmentation | Compact sleeptime memory (reduces context window)         |
| `search`         | Atelier augmentation | Token-saving combined search + read                       |
| `edit`          | Atelier augmentation | Deterministic multi-file batch edits (optional)           |
| `atelier sql inspect`         | Atelier augmentation | Read-only SQL schema/data inspection                      |
| `compact`      | Atelier augmentation | Advise before context compaction; provides reinject hints |
| `atelier lesson inbox`        | Atelier augmentation | List lesson candidates awaiting decision                  |
| `atelier lesson decide`       | Atelier augmentation | Approve or reject a lesson candidate                      |

## Uninstall

```bash
bash scripts/uninstall_gemini.sh
bash scripts/uninstall_gemini.sh --workspace /path/to/workspace
```
