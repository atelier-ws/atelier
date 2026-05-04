# atelier/integrations/codex

Codex host integration artifacts.

- `install.sh` and `verify.sh` are thin wrappers around `scripts/install_codex.sh` and `scripts/verify_codex.sh`.
- `mcp.json` and `mcp.atelier.example.json` define the Codex MCP server entry.
- `AGENTS.atelier.md` is the workspace context file installed to root.
- `tasks/` contains reusable Codex task prompts for preflight and recovery workflows.
- `references/` stores host-specific notes and examples.

If install/verify behavior changes, update `scripts/install_codex.sh`, `scripts/verify_codex.sh`, and this file together.

## V2 tool posture

The following Atelier MCP tools are available and documented in `tasks/preflight.md`:

- **Memory** (Atelier augmentation): `atelier_memory_upsert_block`, `atelier_memory_get_block`, `atelier_memory_recall`, `atelier_memory_archive`, `atelier_memory_summary`
- **Context savings** (Atelier augmentation): `atelier_search_read`, `atelier_batch_edit`, `atelier_sql_inspect`, `atelier_compact_advise`
- **Lesson pipeline** (Atelier augmentation): `atelier_lesson_inbox`, `atelier_lesson_decide`

All V2 tools are Atelier augmentations. Native Codex `Read`, shell `rg`/`grep`, and `MultiEdit` remain the raw-access and editing defaults.

## Trace confidence

- **Primary:** `mcp_live` + `wrapper_live` — Atelier MCP tool calls and wrapper task start/end are
  captured. capture_sources: `["mcp", "wrapper"]`.
- **Fallback:** `manual` — agent calls `atelier_record_trace` with observable facts only.
- **Missing surfaces in primary mode:** `bash_outputs`, `file_edits`, `native_shell`.
- `full_live` is not available for Codex; `hook_enforced` parity with Claude Code plugin hooks is
  future-only and disabled.

When calling `atelier_record_trace` from a Codex session, include:

```json
"trace_confidence": "mcp_live",
"capture_sources": ["mcp", "wrapper"],
"missing_surfaces": ["bash_outputs", "file_edits"]
```
