# Host Integration Matrix

## Supported Hosts

| Host                | Install Path          | Interface           | Safe Default |
| ------------------- | --------------------- | ------------------- | ------------ |
| **Claude Code**     | MCP + skills + agents | MCP stdio           | `suggest`    |
| **Codex CLI**       | MCP + AGENTS.md       | MCP stdio           | `suggest`    |
| **VS Code Copilot** | MCP + instructions    | MCP stdio           | `suggest`    |
| **opencode**        | `opencode.jsonc`      | MCP stdio           | `suggest`    |
| **Gemini CLI**      | settings + MCP        | MCP stdio           | `suggest`    |

## What Atelier Owns

- Procedural reasoning reuse (ReasonBlocks)
- Runtime loop monitoring
- Rubric gate verification
- Failure rescue suggestions
- Failure clustering
- Benchmark reporting and cost ledger

## What Hosts Own

- Model choice
- Tool execution and approval
- User interaction
- Memory and fact persistence (see memory integrations)

## Installing

```bash
make install-agent-clis   # all hosts found on PATH
make verify-agent-clis    # verify each integration

# Individual
make install-claude       # Claude Code
make install-codex        # Codex CLI
make install-opencode     # opencode
make install-copilot      # VS Code Copilot
make install-gemini       # Gemini CLI
```

All installers are idempotent, back up before writing, and skip gracefully if the CLI
is not on PATH. They support `--dry-run`, `--print-only`, and `--strict`.
