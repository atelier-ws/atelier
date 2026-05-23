# Atelier

## What This Is

Atelier is an agent reasoning runtime with MCP tools for code retrieval, search, editing, shell, memory, and workflow orchestration. It is designed to keep agent context efficient while preserving strong recall and execution speed. This milestone focuses on reducing token cost in code/context outputs without weakening retrieval quality.

## Core Value

Atelier should deliver high-recall engineering context with strict token discipline and low latency.

## Current Milestone: v1.1 Atelier Code MCP v2 Parity

**Goal:** Make `mcp__atelier__code` as easy to navigate as CodeGraph while preserving Atelier strengths (budget packing, traceability, and compact defaults).

**Target features:**
- Add `code op="files"` for indexed tree/flat/grouped file discovery without filesystem scans
- Add `code op="explore"` for one-call grouped source + relationship context
- Add `code op="status"` for index health, freshness, and cache visibility
- Add benchmark/docs updates that prove token/latency quality against existing alternatives

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Implement `code op="files"` with token-budgeted indexed file tree output
- [ ] Implement `code op="explore"` with grouped source snippets and relationship map
- [ ] Implement `code op="status"` with index/cache/freshness telemetry
- [ ] Keep responses compact and deterministic under `budget_tokens`
- [ ] Add benchmark/docs coverage for Atelier vs Serena/CodeGraph-style workflows

### Out of Scope

- New top-level MCP tools — extend only `mcp__atelier__code`
- Watcher/autosync implementation — defer until after v2 core ops land
- Framework routes extraction (`op="routes"`) implementation — defer after files/explore/status

## Context

- Existing `code` operations are strong for symbol and impact flows but still require multiple calls for quick structural exploration.
- The design target for this milestone is "CodeGraph-like ergonomics" while preserving Atelier-native strengths: traces, memory, rubric scoring, compact/handover, and rescue/route workflow controls.
- Benchmarks already compare Atelier, Serena, and code-index alternatives; this milestone extends those comparisons to cover new v2 code operations.

## Constraints

- **Surface area:** Extend `mcp__atelier__code` via new `op` values only
- **Token discipline:** All new ops must respect token budgets and deterministic truncation
- **Compatibility:** Preserve existing response contracts for current ops
- **Scope:** No SCIP/routes/watcher buildout unless explicitly requested later

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Expand `code` via `op` values only | Keeps MCP surface stable and avoids migration churn | — Pending |
| Deliver `files` before deeper ops | Indexed tree discovery removes expensive glob/scan loops early | — Pending |
| Defer routes and watcher | v2 parity value comes first from files/explore/status + benchmark proof | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-23 after milestone v1.1 initialization*
