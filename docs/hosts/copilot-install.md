# Installing Atelier into VS Code Copilot

**Support level**: MCP config + Copilot instructions + chat mode + tasks

---

## Quick Install

```bash
make install
```

---

## What Gets Installed

| Artifact             | Location                                            |
| -------------------- | --------------------------------------------------- |
| MCP server config    | `<workspace>/.vscode/mcp.json`                      |
| Copilot instructions | `<workspace>/.github/copilot-instructions.md`       |
| Chat mode            | `<workspace>/.github/chatmodes/atelier.chatmode.md` |
| Task presets         | `<workspace>/.vscode/tasks.json` (merged)           |

The MCP config registers Atelier as a stdio server:

```json
&#123;
  "servers": &#123;
    "atelier": &#123;
      "type": "stdio",
      "command": "<atelier_repo>/scripts/atelier_mcp_stdio.sh",
      "args": [],
      "env": &#123;
        "ATELIER_WORKSPACE_ROOT": "<workspace>"
      &#125;
    &#125;
  &#125;
&#125;
```

## Verify

```bash
make verify
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
- `atelier` chat mode is available from the chat mode selector
- Task presets can run reasoning preflight from the VS Code task runner

## Reload Required

After install, reload the VS Code window:  
`Ctrl+Shift+P` → `Developer: Reload Window`

## Troubleshooting

| Problem               | Fix                                                                   |
| --------------------- | --------------------------------------------------------------------- |
| MCP tools not loading | Reload VS Code window; check `.vscode/mcp.json`                       |
| `code` CLI not found  | Install VS Code CLI: in VS Code, run "Install 'code' command in PATH" |

## V2 Tools — Memory, Context Savings, and Lesson Pipeline

All V2 tools are available via the Atelier MCP server. These are **Atelier augmentations** — VS Code native search, file reads, and editing remain the primary interfaces.

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

Disable Atelier cache: `ATELIER_CACHE_DISABLED=1`.

## Uninstall

Remove the `atelier` key from `.vscode/mcp.json` → `servers`.  
Remove or revert the Atelier section from `.github/copilot-instructions.md`.
