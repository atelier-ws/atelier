## Atelier — Copilot Instructions

Atelier is the Beseam reasoning runtime. Before every coding task, call `atelier_get_reasoning_context` with your task, domain, and tools. Before executing a plan, call `atelier_check_plan` — status `blocked` means a known dead end was detected. On failure, call `atelier_rescue_failure`. After completing a task, call `atelier_record_trace`.

All tools are available via MCP (server name: `atelier`). See `atelier/copilot/README.md` for details.
