# Installing Atelier into opencode

**Support level**: MCP + workspace agent profile

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
make verify-opencode
```

## First Task

Start opencode in your workspace and ask:

```
use atelier to check this plan
```

## Expected Behavior

- opencode connects to Atelier via MCP stdio
- Workspace Atelier agent profile is installed at `.opencode/agents/atelier.md`
- Canonical MCP tools (`check_plan`, `get_reasoning_context`, etc.) are available
- Compatibility aliases (`atelier_check_plan`, `atelier_status`, etc.) are also available

## Troubleshooting

| Problem               | Fix                                      |
| --------------------- | ---------------------------------------- |
| MCP tools not showing | Restart opencode after install           |
| Config not found      | Check `opencode.jsonc` in workspace root |

## V2 Tools — Memory, Context Savings, and Lesson Pipeline

All V2 tools are available via the Atelier MCP server. These are **Atelier augmentations** — opencode native tools remain the primary interface.

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

Remove the `atelier` key from `opencode.jsonc` → `mcp` section.
