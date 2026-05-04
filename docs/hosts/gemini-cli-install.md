# Installing Atelier into Gemini CLI

**Support level**: MCP config + custom command presets

---

## Quick Install

```bash
make install
```

---

## What Gets Installed

| Artifact          | Location                            |
| ----------------- | ----------------------------------- |
| MCP server config | `~/.gemini/settings.json` (global)  |
| Custom commands   | `~/.gemini/commands/atelier/*.toml` |

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
- All Atelier tools (`atelier_check_plan`, `atelier_status`, etc.) are available
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
| `atelier_memory_upsert_block` | Atelier augmentation | Store named value in agent memory                         |
| `atelier_memory_get_block`    | Atelier augmentation | Retrieve named memory block                               |
| `atelier_memory_recall`       | Atelier augmentation | FTS + vector search over archival memory                  |
| `atelier_memory_archive`      | Atelier augmentation | Persist text passage to archival memory                   |
| `atelier_memory_summary`      | Atelier augmentation | Compact sleeptime memory (reduces context window)         |
| `atelier_search_read`         | Atelier augmentation | Token-saving combined search + read                       |
| `atelier_batch_edit`          | Atelier augmentation | Deterministic multi-file batch edits (optional)           |
| `atelier_sql_inspect`         | Atelier augmentation | Read-only SQL schema/data inspection                      |
| `atelier_compact_advise`      | Atelier augmentation | Advise before context compaction; provides reinject hints |
| `atelier_lesson_inbox`        | Atelier augmentation | List lesson candidates awaiting decision                  |
| `atelier_lesson_decide`       | Atelier augmentation | Approve or reject a lesson candidate                      |

## Uninstall

Remove the `atelier` key from `~/.gemini/settings.json` → `mcpServers`.
