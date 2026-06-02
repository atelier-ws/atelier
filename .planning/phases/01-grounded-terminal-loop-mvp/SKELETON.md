# Walking Skeleton — Atelier

**Phase:** 1
**Generated:** 2026-06-02T00:00:00Z

## Capability Proven End-to-End

A terminal coding agent user can start with ranked search grounding, escalate into seeded semantic code-intel, and receive advisory low-roundtrip nudges without losing Atelier's existing memory, tracing, or host-enforcement foundations.

## Canonical Decision IDs

To keep Phase 1 traceable, the locked CONTEXT.md direction is normalized as:

| Decision | Choice |
|---|---|
| D-01 | Reuse existing Atelier strengths instead of rewriting the stack |
| D-02 | Prioritize research and exploration before implementation |
| D-03 | Prefer correct, non-bloated implementation over heavy tightening loops |
| D-04 | Keep the top-level host/tool experience simple while preserving semantic code-intel depth |

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Runtime framework | Keep the existing Atelier brownfield runtime (`gateway -> core -> infra`) | Matches the locked retrofit direction and keeps new behavior in `core`, not in entry-point shells |
| Discovery path | Compose `search_first` over `smart_search` and existing MCP `search` plumbing | Delivers the Search-first default as a composition pass, not a rewrite |
| Semantic escalation | Preserve dedicated `explore` / `node` / `callers` / `callees` / `usages` / `impact` tools over `CodeContextEngine` | Keeps Augment-quality context pressure and Atelier's current code-intel strengths load-bearing |
| Session/context state | Reuse existing session bootstrap, run ledger, and recall/context follow-ups | Satisfies INTL-01 without inventing a new persistence layer in Phase 1 |
| Host ergonomics | Keep Claude/plugin changes advisory and fail-open | Preserves semantic escalation and defers hard workflow enforcement to Phase 2 |
| Directory layout | Continue using existing `src/atelier/core/capabilities`, `src/atelier/gateway/adapters`, `integrations/claude/plugin`, and `tests/` layout | Keeps the phase surgical and aligned with existing brownfield seams |

## Stack Touched in Phase 1

- [x] Existing runtime scaffold — Python/uv, MCP server, hook scripts, targeted pytest surfaces
- [x] MCP discovery route — ranked `search` contract plus explicit follow-up affordances
- [x] Semantic engine path — grounded `seed_files` prioritization and explore/context packing
- [x] Host interaction — Claude advisory nudges, session warm/bootstrap continuity, generated code-mode guidance
- [x] Local full-stack run path — `uv run pytest ...`, `make sync-agent-context`, and `bash scripts/install_claude.sh`

## Source Audit

SOURCE | ID | Feature / Requirement | Plan | Status | Notes
--- | --- | --- | --- | --- | ---
GOAL | — | As a terminal coding agent user, I want a grounded Search-first workflow with semantic escalation, so that I can solve repo tasks faster without losing precision. | 01-01, 01-02, 01-03 | COVERED | Decomposed into grounding, semantic preservation, and ergonomics slices
REQ | GRND-01 | Search-first default path for discovery | 01-01 | COVERED | Search-first composition and MCP contract
REQ | GRND-02 | Semantic escalation in the same session | 01-02 | COVERED | Grounded seed-file routing and explore/search preservation
REQ | GRND-03 | Low-roundtrip batching and follow-up reads | 01-03 | COVERED | Advisory nudges, batching guidance, generated host guidance
REQ | INTL-01 | Preserve memory and context recall strengths | 01-03 | COVERED | Session bootstrap, recall/context nudges stay intact
REQ | INTL-02 | Preserve code-intel strengths while simplifying the default loop | 01-02 | COVERED | Dedicated code-intel tools stay explicit and seeded
RESEARCH | — | Phase 1 stays a composition pass, not a rewrite | 01-01, 01-02, 01-03 | COVERED | D-01 is enforced across all plans
RESEARCH | — | Keep logic in core; gateway changes stay thin | 01-01, 01-02 | COVERED | Search and semantic logic remain core-owned
RESEARCH | — | Preserve semantic escalation as dedicated tools | 01-02 | COVERED | Explore/node/call graph surfaces remain discoverable
RESEARCH | — | Host ergonomics remain advisory only | 01-03 | COVERED | No blocking hook behavior added
RESEARCH | — | No new packages are required | 01-01, 01-02, 01-03 | COVERED | All plans reuse existing repo capabilities
CONTEXT | D-01 | Reuse existing strengths instead of rewriting | 01-01, 01-02, 01-03 | COVERED | Explicitly cited in objectives/actions
CONTEXT | D-02 | Prioritize research and exploration before implementation | 01-01, 01-02, 01-03 | COVERED | Each plan has concrete `read_first` context
CONTEXT | D-03 | Prefer correct, non-bloated implementation | 01-01, 01-02, 01-03 | COVERED | Surgical file lists and thin-scope tasks
CONTEXT | D-04 | Keep host/tool UX simple while preserving semantic depth | 01-01, 01-02, 01-03 | COVERED | Search-first UX plus explicit semantic escalation and advisory hooks

## Out of Scope (Deferred to Later Slices)

- Full host-level routing changes
- Minified read/edit path
- Benchmark gate implementation
- Hard grounded-edit enforcement in hooks
- Gateway-side ranking or orchestration rewrite

## Subsequent Slice Plan

- Phase 2: Explicit execution kernel with plan review, workflow state, and grounded edit discipline
- Phase 3: Routed Atelier-owned subcall execution with provenance
- Phase 4: Artifact-backed paired benchmark gate for solved-rate, quality, and cost
