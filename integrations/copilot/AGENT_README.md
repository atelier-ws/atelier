# atelier/integrations/copilot

Copilot host integration artifacts for VS Code.

- `install.sh` and `verify.sh` delegate to `scripts/install_copilot.sh` and `scripts/verify_copilot.sh`.
- `mcp.atelier.example.json` provides MCP server wiring examples.
- `COPILOT_INSTRUCTIONS.atelier.md` contains append-only instruction fragment.
- `chatmodes/atelier.chatmode.md` is installed to workspace `.github/chatmodes/`.
- `tasks.json` provides Atelier task presets merged into workspace `.vscode/tasks.json`.

Keep docs, installer behavior, and verification checks aligned when changing any artifact here.

## V2 tool posture

Smart-tool cache posture: `smart_read`, `smart_search`, and `cached_grep` are
default-on Atelier augmentations for repeated context reads/searches. Do not
remove host-native file reads, VS Code search, shell `rg`, or `grep`; those
remain the raw-access fallback. Use `ATELIER_CACHE_DISABLED=1` to disable the
Atelier cache.

Additional V2 Atelier augmentations available via MCP:

- **Memory**: `atelier_memory_upsert_block`, `atelier_memory_get_block`, `atelier_memory_recall`, `atelier_memory_archive`, `atelier_memory_summary`
- **Context savings**: `atelier_search_read`, `atelier_batch_edit`, `atelier_sql_inspect`, `atelier_compact_advise`
- **Lesson pipeline**: `atelier_lesson_inbox`, `atelier_lesson_decide`

All V2 tools are Atelier augmentations. VS Code Copilot native tools (file reads, search, edit) remain the defaults.

## Trace confidence

- **Primary:** `mcp_live` — Atelier MCP tool calls and VS Code task outputs are captured.
  capture_sources: `["mcp"]`.
- **Fallback:** `manual` — agent calls `atelier_record_trace` with observable facts only.
- **Missing surfaces in primary mode:** `native_chat_edits`, `file_edits`.
- `full_live` and `hook_enforced` are not available for VS Code Copilot; hard blocking of
  model/tool calls and `provider_enforced` are future-only and disabled.

When calling `atelier_record_trace` from a Copilot session, include:

```json
"trace_confidence": "mcp_live",
"capture_sources": ["mcp"],
"missing_surfaces": ["native_chat_edits", "file_edits"]
```
