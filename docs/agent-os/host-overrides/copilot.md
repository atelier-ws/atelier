# Copilot override

- Copilot sessions should use `.github/copilot-instructions.md` as the workspace entrypoint.
- Workspace agent lives at `.github/agents/atelier.agent.md`.
- Copilot entrypoints must tell the agent to use Atelier MCP tools first for reads, search, edits, and shell work; VS Code native tools are fallback only when Atelier is unavailable or returns `noop`.
- VS Code tasks are the quickest way to expose repeatable preflight, worktree, and evidence loops.
- Projection-aware edits should carry `include_meta=true` read metadata forward and obey `retry_with` reread guidance rather than guessing transformed spans.
- **Subagent spawning**: when `route(op=spawn)` returns `handled=false`, call `task(agent_type="general-purpose", prompt=<spawn_directive.prompt>)` immediately. Note: Copilot's task tool does not reliably support a `model=` override — the `agent_type` controls behaviour. For parallel waves, spawn one task per message.
