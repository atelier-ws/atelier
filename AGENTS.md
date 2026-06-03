# Atelier — Agent Context

This project is an MCP server + SDK middleware that gives coding agents
shared procedures, failure rescue, loop detection, cost tracking, and
cross-vendor routing.

## Core domains

- **capabilities** — context reuse, failure analysis, loop detection, tool supervision,
  model routing, memory & recall, context compression, lesson promotion, governance
- **infrastructure** — code intelligence (SCIP, tree-sitter, Zoekt, ast-grep),
  embeddings, storage (SQLite, Postgres/pgvector), runtime plumbing
- **gateway** — CLI, MCP server, host integrations (Claude Code, Codex, Copilot,
  opencode, Antigravity, Cursor, Hermes), session parsers
- **host integrations** — per-host install scripts, hooks, agent skills, and
  workflow templates under `integrations/`

## Supported hosts

Claude Code · Codex CLI · Copilot · opencode · Antigravity · Cursor IDE · Hermes Agent

## License

Apache 2.0
