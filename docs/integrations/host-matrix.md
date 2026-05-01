# Host Matrix

## Runtime Attachment Modes

| Host         | Install Path      | Recommended Interface   | Safe Default |
| ------------ | ----------------- | ----------------------- | ------------ |
| Claude Code  | plugin + MCP      | MCP + host instructions | `suggest`    |
| Codex CLI    | AGENTS.md + MCP   | MCP                     | `suggest`    |
| Copilot      | MCP server config | MCP                     | `suggest`    |
| opencode     | `opencode.jsonc`  | MCP                     | `suggest`    |
| Gemini CLI   | settings + MCP    | MCP                     | `suggest`    |
| OpenHands    | Python SDK        | `OpenHandsAdapter`      | `shadow`     |
| SWE-agent    | Python SDK        | `SWEAgentAdapter`       | `shadow`     |
| Aider        | Python SDK        | `AiderAdapter`          | `suggest`    |
| Continue.dev | Python SDK        | `ContinueAdapter`       | `suggest`    |
| LangGraph    | Python SDK        | `LangGraphAdapter`      | `shadow`     |

## What Atelier Owns

- procedural reasoning reuse
- runtime monitors
- rubric verification
- rescue suggestions
- failure clustering
- benchmark reporting

## What Hosts Still Own

- model choice
- tool execution
- user interaction
- memory and fact persistence
