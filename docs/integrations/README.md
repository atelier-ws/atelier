# Atelier Integrations

Atelier is the runtime layer that sits between hosts, memory systems, and domain tools. It is not the IDE, not the agent, and not the memory system.

## Host Categories

### Agent CLIs and IDEs

- Claude Code
- Codex CLI
- VS Code Copilot
- opencode
- Gemini CLI

These hosts typically integrate through MCP plus host-specific install artifacts.

### Embedded Python Hosts

- OpenHands via `OpenHandsAdapter`
- SWE-agent via `SWEAgentAdapter`
- Aider via `AiderAdapter`
- Continue.dev via `ContinueAdapter`
- LangGraph via `LangGraphAdapter`

These hosts integrate through `atelier.sdk` and the adapter layer in `src/atelier/adapters/`.

### Memory Systems

- OpenMemory via `src/atelier/integrations/memory/openmemory.py`
- Mem0 via `src/atelier/integrations/memory/mem0.py`
- Generic vector memory via `src/atelier/integrations/memory/generic_vector_memory.py`

Memory remains facts. Atelier remains reasoning.

## Safe Modes

All ecosystem adapters support:

- `shadow`: observe and report only
- `suggest`: return warnings and rescue guidance
- `enforce`: block bad plans or failed rubric gates
