# Atelier

## What This Is

Atelier is a brownfield agent runtime being reset into a terminal-first product: a slimmer execution core that preserves Atelier's strongest context, memory, code-intel, tracing, and host-enforcement capabilities while reducing prompt churn and token spend. The target shape is a hybrid of Eval and WOZ: Eval-grade planning/execution discipline plus WOZ-grade host and tool ergonomics, built as a retrofit on the existing Atelier architecture rather than a rewrite.

## Core Value

Deliver better terminal-task outcomes per token by combining low-roundtrip tools, durable context memory, strong code intelligence, and first-class routed execution.

## Requirements

### Validated

- ✓ Durable recall and context memory already exist and should not regress — current Atelier runtime composes context, memory facts, and archival recall into host-facing flows.
- ✓ Dedicated code-intel UX already exists and should not regress — symbols, node, callers, callees, usages, impact, pattern, and explore are real product strengths.
- ✓ Host-side enforcement, tracing, and runtime telemetry already exist and should not regress — plugin hooks, run ledger, and session/report surfaces are part of the current value.

### Active

- [ ] Turn Atelier into a terminal-first brownfield hybrid of Eval and WOZ without rewriting the existing architecture.
- [ ] Make a combined Search-first default terminal tool path that lowers roundtrips while keeping Atelier's stronger code-intel and memory as the escalation path.
- [ ] Add a typed workflow kernel with explicit plan review, task-local carry-forward state, and lower prompt churn for plan -> execute -> review loops.
- [ ] Make provider routing first-class for Atelier-owned sub-invocations, informed by the installed WOZ router pattern but implemented as an Atelier-native execution layer.
- [ ] Prove milestone-1 success on frozen terminal benchmarks with non-inferior quality and materially lower cost/token spend than the baseline path.

### Out of Scope

- Clean-slate rewrite of Atelier — this reset must reuse the existing platform and retrofit winning mechanisms into it.
- Removing CLI/API/UI/SDK/integration surfaces before a measured parity review — cuts happen only after evidence, not instinct.
- Web-first or dashboard-first repositioning — milestone 1 is about terminal execution quality and cost discipline.
- Full provider enforcement for the user's top-level host conversation on day one — milestone 1 only enforces routing where Atelier truly owns execution.
- Copying Eval or WOZ wholesale — only code-backed mechanisms that improve Atelier's target product should be imported.

## Context

Atelier already spans CLI, MCP, HTTP API, SDK, optional frontend, host integrations, memory systems, tracing, and a large code-intel engine. That breadth gives it stronger memory, code-intel, tracing, and integration foundations than either Eval or WOZ, but it also creates bloat signals: very large multi-responsibility modules, fragmented default tool paths, and a platform shape that is broader than the intended terminal-first core.

The reset direction is informed by four sources: Atelier's current codebase map, Eval's code-backed workflow/session kernel, WOZ's code-backed host/tool ergonomics, and the installed WOZ plugin's dormant but real local router daemon. The installed WOZ plugin materially updates the routing picture: it can rewrite Claude host env to a local router endpoint and serve provider-backed routes, but on this machine it is inactive, so its live value today is still tool redirection, recall, and telemetry rather than active provider routing.

Milestone 1 optimizes for one thing: Eval-level planning/execution quality with materially lower token spend on benchmarked terminal tasks. The benchmark standard must be paired, artifact-backed, and resistant to gaming: same baseline conditions, frozen task set, non-inferior quality threshold, and explicit cost/token deltas.

## Constraints

- **Architecture**: Brownfield retrofit on the existing `gateway -> core -> infra` structure — preserve working foundations and minimize disruptive rewrites.
- **Product**: Terminal-first core — prioritize the default terminal task loop over secondary UI or platform expansion.
- **Quality**: Do not regress current memory, code-intel, tracing, or host-enforcement strengths — those are already real product advantages.
- **Routing**: Enforce routing only where Atelier owns execution first — top-level host chat remains shadow/advisory until parity is measured.
- **Validation**: Success claims require paired benchmark evidence with raw artifacts — UX savings counters alone are not sufficient proof.
- **Scope**: Surface cuts require parity review first — no speculative pruning of existing capabilities.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Reset Atelier as a brownfield retrofit, not a rewrite | Existing Atelier already has stronger memory, code-intel, tracing, and routing foundations than the alternatives | — Pending |
| Make the product terminal-first | The primary goal is better planning/execution quality per token on benchmarked terminal tasks | — Pending |
| Borrow Eval's workflow kernel ideas, not its full product shape | The strongest Eval advantages are code-backed workflow/session mechanics and prompt-churn reduction | — Pending |
| Borrow WOZ's host/tool ergonomics and router pattern, not WOZ wholesale | WOZ contributes decisive Search/Edit/Recall UX and an installed local router pattern, but not a complete reusable architecture by itself | — Pending |
| Keep existing Atelier surfaces until measured parity justifies cuts | The repo is broad, but removal before evidence risks deleting current advantages | — Pending |
| Use benchmarked non-inferior quality + lower spend as the milestone gate | The reset is explicitly about cost reduction without compromising terminal-task outcomes | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check - still the right priority?
3. Audit Out of Scope - reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-02 after brownfield reset research and installed WOZ router review*
