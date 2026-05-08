---
description: "Use when: starting or coordinating an Atelier task loop from context retrieval through trace recording."
allowed-tools: "mcp__atelier__reasoning, mcp__atelier__lint, mcp__atelier__rescue, mcp__atelier__verify, mcp__atelier__trace"
---

Run the Atelier task loop.

1. Call `reasoning` with task, files, domain, tools, and errors.
2. Draft a short plan and call `lint`.
3. If blocked, revise from the suggested plan and re-check.
4. Use `rescue` after repeated identical failures.
5. Use `verify` for required rubrics.
6. Call `trace` at completion with observable facts only.

Keep the loop explicit and concise.