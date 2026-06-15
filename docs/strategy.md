# Atelier Strategy

> Status: living doc. Last revised 2026-06-15.

## One-line positioning

**The open-source runtime engineering platform for AI agents — routing, cost tracking, memory, and audit trail across every tool in your stack.**

## What Atelier is

Atelier is not an AI model. It is a runtime that sits between you and the AI tools you already use, providing:

- **Per-turn model routing** — automatically selects the cheapest or best model for each request based on task type, session phase, and cost-quality tradeoffs
- **Dynamic context compaction** — optimizes prompt context using task-aware hints (type, risk level, must-keep tokens) to reduce waste
- **Persistent memory** — stores, retrieves, and manages facts across sessions with inspectable attribution and rollback
- **Cost tracking & honest reporting** — per-session cost breakdowns, counterfactual estimates, and aggregate savings
- **Code intelligence** — SCIP-indexed symbol search, call graphs, usages, AST pattern matching, and semantic retrieval
- **Outcome capture** — every routing and compaction decision gets an observable outcome score, enabling continuous optimization
- **Cross-machine sync** — encrypted sync of memory and session state across machines

## What Atelier is not

- An AI model or provider
- An IDE or editor plugin
- A replacement for your existing AI CLI

## Architecture principle

Atelier is organized into four layers:

| Layer | Purpose |
| --- | --- |
| `core/` | Domain models, rules, capability logic, service contracts |
| `infra/` | Storage, runtime plumbing, persistence, adapters |
| `gateway/` | CLI, MCP, host integrations, service wiring |
| `frontend/` | Dashboard UI and browser-side client logic |

Direction: `core` does not depend on `gateway`. `infra` does not depend on `gateway`. Host-specific behavior lives in `gateway/hosts` or `integrations/`.

## Current capabilities

| Capability | Status |
|---|---|
| Per-turn model routing (ModelRouter) with session-phase awareness | Shipped |
| Dynamic context compaction with LLM hints | Shipped |
| Workspace state persistence | Shipped |
| Runtime memory store (SQLite/PostgreSQL) with recall | Shipped |
| Symbol-first code intelligence (SCIP, ast-grep, call graph) | Shipped |
| OpenAI-compatible gateway server | Shipped |
| CLI: runs, ledger, swarm, lessons, benchmarks, savings | Shipped |
| Background services with auto-update | Shipped |
| Telemetry (OTel → PostHog, local-first, opt-out) | Shipped |
| Host integrations: Claude Code, Codex, Copilot, OpenCode, Cursor, Antigravity, Hermes | Shipped |
| MCP server surface with local and remote modes | Shipped |
| Cross-machine encrypted sync | Shipped |
| Outcome capture (feedback loop foundation) | Shipped |
| Per-session cost reports with counterfactual | Shipped |
| `atelier insights` weekly summary | Shipped |
| Public benchmark publication pipeline | Shipped |

Out of scope (not planned):

- Custom models, fine-tuning, or provider-owned embeddings
- IDE plugin before CLI adoption proves the need
- Enterprise sales motion before Team tier is repeating
