# Installing Atelier into Codex CLI

**Support level**: Native Codex skills/subagents + MCP + Atelier wrapper workflow

---

## Quick Install

```bash
make install
```

---

## What Gets Installed

| Artifact                 | Location                             |
| ------------------------ | ------------------------------------ |
| Atelier skills           | `<workspace>/.codex/skills/atelier/` |
| MCP server config        | `<workspace>/.codex/mcp.json`        |
| AGENTS instruction block | `<workspace>/AGENTS.atelier.md`      |
| Wrapper script           | `<workspace>/bin/atelier-codex`      |
| Task templates           | `<workspace>/.codex/tasks/*.md`      |

## Verify

```bash
make verify
```

## First Task

Start Codex in your workspace and use the skill:

```
use skill: atelier-check-plan
```

Or run the Atelier preflight wrapper:

```bash
./bin/atelier-codex --task "Fix checkout price mismatch" --domain beseam.shopify.publish
```

## Expected Behavior

- Codex loads `atelier-check-plan` skill and submits the current task plan to Atelier for scoring
- MCP tools are available for Atelier reasoning operations
- Wrapper preflight always runs reasoning context, plan validation, and optional rubric gate

## Troubleshooting

| Problem           | Fix                                                               |
| ----------------- | ----------------------------------------------------------------- |
| Skill not found   | Check `.codex/skills/atelier/` — rerun `make install`             |
| MCP tools missing | Check `.codex/mcp.json` — confirm `atelier` entry present         |
| Wrapper missing   | Re-run `make install` and verify `bin/atelier-codex` exists       |

## V2 Tools — Memory, Context Savings, and Lesson Pipeline

The following V2 tools are available via MCP once installed. All are **Atelier augmentations** — native Codex read/search tools remain the primary interface.

| Tool                          | Boundary                                         | Description                                       |
| ----------------------------- | ------------------------------------------------ | ------------------------------------------------- |
| `atelier_memory_upsert_block` | Atelier augmentation                             | Store named value in agent memory                 |
| `atelier_memory_get_block`    | Atelier augmentation                             | Retrieve named memory block                       |
| `atelier_memory_recall`       | Atelier augmentation                             | FTS + vector search over archival memory          |
| `atelier_memory_archive`      | Atelier augmentation                             | Persist text passage to archival memory           |
| `atelier_memory_summary`      | Atelier augmentation                             | Compact sleeptime memory (reduces context window) |
| `atelier_search_read`         | Atelier augmentation                             | Token-saving combined search + read               |
| `atelier_batch_edit`          | Atelier augmentation                             | Deterministic multi-file batch edits (optional)   |
| `atelier_sql_inspect`         | Atelier augmentation                             | Read-only SQL schema/data inspection              |
| `atelier_compact_advise`      | Atelier augmentation over host-native `/compact` | Advise before compaction; provides reinject hints |
| `atelier_lesson_inbox`        | Atelier augmentation                             | List lesson candidates awaiting decision          |
| `atelier_lesson_decide`       | Atelier augmentation                             | Approve or reject a lesson candidate              |

See `integrations/codex/tasks/preflight.md` for how to use memory and `search_read` in the preflight workflow.

## Uninstall

```bash
rm -rf .codex/skills/atelier/
# Remove atelier entry from .codex/mcp.json manually
# Remove or ignore AGENTS.atelier.md
```
