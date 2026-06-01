# Cursor override

- Cursor loads `integrations/cursor/AGENTS.atelier.md` as the workspace entrypoint (generated from `docs/agent-os/README.md`).
- Two `.cursor/rules/` files are always active: `coding-guidelines.mdc` (applied to every request) and `tool-selection.mdc` (Atelier-first tool selection rules); keep those files aligned with the shared docs tree.
- The MCP server is wired via `integrations/cursor/mcp.atelier.template.json`; Cursor exposes Atelier tools under the standard `mcp__atelier__` prefix.
- Cursor entrypoints must explicitly prefer Atelier MCP tools for reads, search, code intelligence, edits, and shell work; Cursor or VS Code native file reads, workspace search, shell `rg`, or `grep` are fallback only when Atelier is unavailable or returns `noop`.
- Keep the shared workflow, tool-substitution rules, and fallback rules aligned with the rest of the generated entrypoints.
