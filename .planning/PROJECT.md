# Atelier Code Intelligence

## What This Is

Atelier Code Intelligence is the active brownfield program for extending Atelier's
existing CLI, MCP, service, and frontend surfaces with precomputed,
budget-aware code intelligence. It upgrades how agents find and change code so
symbol lookup, navigation, and targeted edits become near-zero-token operations
by default instead of repeated live-search work.

This project is for Atelier's agent-assisted coding workflows: first for
Atelier itself, then for repositories where Atelier-backed agents need fast,
deterministic code retrieval and editing primitives that scale better than
session-local LSP workflows.

## Core Value

Agents can find and change code through budget-aware, precomputed intelligence
with near-zero token overhead by default.

## Requirements

### Validated

- ✓ Atelier already exposes CLI, MCP, HTTP API, and frontend entry points over a
  shared runtime and persistent store — existing
- ✓ Atelier already ships MCP tools for `context`, `route`, `rescue`, `trace`,
  `verify`, `memory`, `read`, `edit`, `sql`, `code`, `search`, `compact`, and
  `shell` — existing
- ✓ `CodeContextEngine` already supports `index`, `search`, `symbol`, `outline`,
  `context`, and `impact` operations that can be extended in place — existing
- ✓ Atelier already records traces, telemetry, and smart-read savings, giving a
  baseline for measuring code-intel cost reductions — existing

### Active

- [ ] Add shared retrieval cache and token-budget packing to existing `code`
  operations so cache metadata, provenance, and savings are first-class
- [ ] Add routed symbol intelligence backends behind the existing `code`
  surface, starting with SCIP and later layering structural, semantic, git, and
  scale-oriented retrieval
- [ ] Extend the current tool surface with the planned code-intel behaviors from
  `docs/plans/active/code-intel/` M0-M18 without breaking existing entry points
- [ ] Deliver the roadmap until Atelier's default code/search/edit workflows are
  near-zero-token, budget-aware, traceable, and validated end to end

### Out of Scope

- Serena or live LSP-per-session as the primary architecture — the grounded
  plan explicitly prefers precomputed artifacts over session-local language
  servers
- Replacing Atelier's existing `search` tool for text and regex workflows — it
  remains the complement when symbol-first retrieval is not the right fit
- New non-MCP delivery surfaces such as IDE plugins — the project stays within
  Atelier's current runtime, host integrations, and service/UI stack
- Full cross-language/runtime analysis beyond the planned partial static edges —
  the active plan deliberately limits this to confidence-scored common cases
- Megarepo infrastructure beyond the Zoekt-scale target — the plan explicitly
  defers ultra-large sharded search systems

## Context

This is a brownfield initialization over the existing Atelier repository. The
current product already provides a shared runtime with CLI, MCP, HTTP, and UI
entry points, plus a `CodeContextEngine` that handles indexing, symbol lookup,
outline, context packing, and impact analysis.

The project source of truth for new work is `docs/plans/active/code-intel/`,
especially `index.md` and `grounding.md`. That plan defines a full M0-M18
program focused on cost-optimal code intelligence, requires extending existing
MCP tool ops instead of adding top-level tools by default, and treats token
savings as the main justification for every milestone.

The freshly generated brownfield codebase map under `.planning/codebase/`
captures the current architecture, conventions, testing, and concerns and
should be treated as the reference for implementation planning.

## Constraints

- **Architecture**: Extend existing MCP tools and internal runtime modules
  before introducing new top-level tool registrations — `grounding.md` is the
  tie-breaker when milestone docs drift
- **Cost**: Every milestone must improve or protect token efficiency; outline
  first, cache aggressively, and make budgets explicit
- **Validation**: Milestones are not done without tests, benchmark evidence,
  validation-matrix coverage, and trace recording
- **Compatibility**: New code-intel behavior must fit Atelier's current
  Python/FastAPI/MCP/React architecture and preserve existing public entry
  points
- **Sequencing**: The full program scope is M0-M18, and the build-vs-integrate
  checkpoint in M18 must gate M16

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Extend existing `code`, `edit`, `memory`, and related MCP ops instead of adding new top-level tools | Keeps the agent surface stable and matches the grounded landing map | — Pending |
| Prefer precomputed code intelligence artifacts over live LSP/Serena-style session workflows | The north star is lower latency and lower token cost on coding tasks | — Pending |
| Treat the full `docs/plans/active/code-intel/` M0-M18 program as active scope | The user directed project initialization to follow that full plan set | — Pending |
| Define success as near-zero-token default code/search/edit flows, not feature parity with other tools | Matches both the code-intel north star and the user's definition of done | — Pending |

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
*Last updated: 2026-05-18 after initialization*
