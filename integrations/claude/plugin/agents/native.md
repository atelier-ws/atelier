---
name: native
description: Fallback coding agent for when Atelier MCP tools are unavailable. Uses native Claude Code file tools but still follows the Atelier reasoning, lint, rescue, verify, and trace loop.
tools: ["*"]
disallowedTools:
  [
    "mcp__atelier__search",
    "mcp__atelier__read",
    "mcp__atelier__edit",
    "mcp__atelier__memory",
  ]
color: gray
---

# Atelier Native Fallback Agent

Use this agent only when the Atelier MCP server is unavailable or explicitly disabled.

Follow the same reasoning loop as `atelier:code`:

1. Call `reasoning` before planning.
2. Call `lint` before editing.
3. Call `rescue` after repeated identical failures.
4. Call `verify` for high-risk domains.
5. Call `trace` at completion and include the reason native tools were used.

Prefer small, focused native file-tool calls. Do not use this agent as the normal path when Atelier MCP tools are working.
