# Claude override

- Claude plugin agent files can carry frontmatter for tools and display metadata.
- Claude entrypoints should prefer Atelier MCP tools for reads, search, edits, and shell work whenever those tools are exposed in the agent frontmatter.
- Claude-native file tools remain the raw-access fallback only when Atelier tools are unavailable or return `noop`.
- The main coding persona lives in `integrations/claude/plugin/agents/code.md`.
- **Subagent spawning**: when `route(op=spawn)` returns `handled=false`, call `Agent(agent_type="general-purpose", model=<spawn_directive.model>, prompt=<spawn_directive.prompt>)` immediately. Pass `run_in_background=True` for parallel waves. Omit `model=` entirely when it is `"inherit"`.
- Treat the host spawn as **best-effort projection**, not full envelope ownership: Atelier may compute `cache_policy`, `spawn_group_id`, `cache_scope_id`, and `stable_prefix_hash`, but Claude only receives what its spawn surface can carry.
- Child execution receipts must record `requested_fields`, `honored_fields`, and `dropped_fields` so cache behavior is measured honestly when the host strips structured spawn metadata.
