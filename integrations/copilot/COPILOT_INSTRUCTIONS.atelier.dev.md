## Atelier — Copilot Instructions


Atelier is the Agent Reasoning Runtime. Use the **3-step process**: call `context` to gather procedures, **Implement** the task (with optional `rescue` and `route`), and call `trace` at completion.

Budget optimizer: before changing files, name the deliverable and summarize the smallest viable plan. Keep context narrow: use only the current goal, relevant files, failing command/output, and known constraints. Restate working context in under 10 bullets before editing or after compaction. If more than 10 minutes pass without an edit, name the expected deliverable or check with the user. If the same approach fails twice, call `rescue` or change approach; do not retry a third time.

All tools are available via MCP (server name: `atelier`). See `atelier/copilot/README.md` for details.

`read` and `search` are Atelier augmentations for bounded, repeated context
reads/searches. If an Atelier MCP tool returns `noop`, is hidden, or is
unavailable, use Copilot or VS Code native file reads, workspace search, shell
`rg`, or `grep`. Always return findings instead of waiting for tool
availability to improve.
