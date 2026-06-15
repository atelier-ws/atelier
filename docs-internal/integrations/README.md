# Atelier Integrations

Atelier is the reasoning runtime layer that sits between agent hosts and their environments.
It is not the IDE, not the agent, and not the memory system.

## Supported Hosts

| Host            | Install path          | Interface | Guide                                                     |
| --------------- | --------------------- | --------- | --------------------------------------------------------- |
| **Claude Code** | MCP + skills + agents | MCP stdio | [claude-code-install.md](../hosts/claude-code-install.md) |
| **Codex CLI**   | MCP + AGENTS.md       | MCP stdio | [codex-install.md](../hosts/codex-install.md)             |
| **Copilot**     | MCP + instructions    | MCP stdio | [copilot-install.md](../hosts/copilot-install.md)         |
| \*_opencode_    | `opencode.json`       | MCP stdio | [opencode-install.md](../hosts/opencode-install.md)       |
| **Gemini CLI**  | settings + MCP        | MCP stdio | [gemini-cli-install.md](../hosts/gemini-cli-install.md)   |

## Memory Systems

| System          | Module                                                     | Notes                                                                    |
| --------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------ |
| SQLite (native) | `src/atelier/infra/storage/sqlite_memory_store.py`         | Default. Local file, zero-server, fastest. WAL mode for concurrency.     |
| External bridge | `src/atelier/gateway/integrations/`                        | Optional adapters for external memory systems (configured via env vars). |
| Generic vector  | `src/atelier/integrations/memory/generic_vector_memory.py` | Embedding-compatible endpoint for vector similarity search.              |

Memory is facts. Atelier handles procedural reasoning. They complement, not duplicate, each other.

## Safe Modes

All host integrations support:

| Mode      | Behaviour                                   |
| --------- | ------------------------------------------- |
| `shadow`  | Observe and record; never block             |
| `suggest` | Return warnings and rescue guidance         |
| `enforce` | Block plans that fail rubric gates (exit 2) |

Default for all supported hosts: `suggest`.
