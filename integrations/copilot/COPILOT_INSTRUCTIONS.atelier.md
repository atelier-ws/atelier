## Atelier — Copilot Instructions

Atelier is the Agent Reasoning Runtime. Before every coding task, call `reasoning` with your task, domain, and tools. Before executing a plan, call `lint` — status `blocked` means a known dead end was detected. On failure, call `rescue`. After completing a task, call `trace`.

All tools are available via MCP (server name: `atelier`). See `atelier/copilot/README.md` for details.
