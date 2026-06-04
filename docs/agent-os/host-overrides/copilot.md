# Copilot override

- Copilot sessions should use `.github/copilot-instructions.md` as the workspace entrypoint.
- Workspace role agents live at `.github/agents/atelier.code.agent.md`, `.github/agents/atelier.execute.agent.md`, and the other `atelier.<role>.agent.md` files.
- Copilot entrypoints must tell the agent to use Atelier MCP tools first for reads, search, edits, and shell work; VS Code native tools are fallback only when Atelier is unavailable or returns `noop`.
- VS Code tasks are the quickest way to expose repeatable preflight, worktree, and evidence loops.
- Projection-aware edits should carry `include_meta=true` read metadata forward and obey `retry_with` reread guidance rather than guessing transformed spans.
- **Subagent spawning**: when `route(op=spawn)` returns `handled=false`, call `task(agent_type="general-purpose", prompt=<spawn_directive.prompt>)` immediately. Note: Copilot's task tool does not reliably support a `model=` override — the `agent_type` controls behaviour. For parallel waves, spawn one task per message.
- Treat the host spawn as **best-effort projection**, not full envelope ownership: Atelier may compute `cache_policy`, `spawn_group_id`, `cache_scope_id`, and `stable_prefix_hash`, but Copilot only receives what its task surface can carry.
- Child execution receipts must record `requested_fields`, `honored_fields`, and `dropped_fields` so cache-reuse claims stay honest when Copilot drops structured spawn metadata or model overrides.
