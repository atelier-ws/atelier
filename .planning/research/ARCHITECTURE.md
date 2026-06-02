# Architecture Research

**Domain:** Terminal-first agent runtime brownfield retrofit
**Researched:** 2026-06-02
**Confidence:** HIGH

## Standard Architecture

### System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                    Host / Terminal Surface                 │
├─────────────────────────────────────────────────────────────┤
│ CLI │ MCP │ Host Hooks │ Optional Service / UI            │
├─────────────────────────────────────────────────────────────┤
│               Search-first Tool Composition Layer          │
├─────────────────────────────────────────────────────────────┤
│ Search │ Edit │ Recall │ Sql │ Code-Intel Escalation      │
├─────────────────────────────────────────────────────────────┤
│                  Session Workflow Kernel                   │
├─────────────────────────────────────────────────────────────┤
│ Plan Review │ Task State │ Carry-forward │ Route Decisions │
├─────────────────────────────────────────────────────────────┤
│                   Runtime / Persistence                    │
├─────────────────────────────────────────────────────────────┤
│ Memory │ Ledger │ Benchmarks │ Providers │ Storage         │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Host / terminal adapters | Accept work from CLI, MCP, hooks, optional service/UI | Existing `gateway/` entry points |
| Search-first tool layer | Provide low-roundtrip default path for discovery/read/edit/recall/db work | Composed tools built on existing MCP/runtime handlers |
| Code-intel layer | Resolve symbols, graph relations, impact, and semantic exploration | Existing code-context engine and MCP surfaces |
| Workflow kernel | Hold session workflow state, explicit task progression, plan review, and outputs | New typed session object reusing Atelier runtime/ledger infrastructure |
| Route execution layer | Turn advisory routing into real owned subcall execution | New provider execution lane using existing router/ranking foundations |
| Persistence / telemetry | Save runtime state, traces, reports, benchmark artifacts | Existing storage, ledger, report, and telemetry systems |

## Recommended Project Structure

```text
src/atelier/
├── gateway/                 # CLI, MCP, host-facing entry points
├── core/
│   ├── capabilities/        # Existing domain capabilities
│   ├── runtime/             # Runtime orchestration
│   ├── workflow/            # New typed workflow-kernel extraction
│   └── routing_exec/        # New provider execution layer
├── infra/                   # Storage, runtime state, provider clients, telemetry
frontend/                    # Optional dashboard / reporting UI
integrations/                # Host/plugin wrappers and hooks
.planning/research/          # Brownfield reset research context
```

### Structure Rationale

- **`gateway/`** remains the host-facing adapter layer; do not move product logic here.
- **`core/workflow/`** should isolate the new workflow kernel from prompt-only orchestration.
- **`core/routing_exec/`** should separate "deciding a route" from "executing the route."
- **`infra/`** remains the place for provider/storage/runtime backends.
- **`frontend/` and `integrations/`** stay, but milestone 1 should treat them as supporting surfaces rather than the primary design center.

## Architectural Patterns

### Pattern 1: Search-First Composition

**What:** one dominant default path for terminal tasks that composes read/search/edit/recall/sql capabilities instead of forcing users to choose from too many surfaces.
**When to use:** high-frequency file discovery, path lookup, content reads, and cheap context gathering.
**Trade-offs:** lowers roundtrips and decision cost, but must not hide the stronger code-intel tools when semantic accuracy matters.

### Pattern 2: Session-Owned Workflow State

**What:** a typed workflow object that persists plan state, current task, task outputs, and review state across the session.
**When to use:** any plan -> execute -> benchmark loop where prompt churn currently comes from reconstructing state on each step.
**Trade-offs:** higher implementation cost than prompt-only orchestration, but it is the clearest path to Eval-level execution quality.

### Pattern 3: Routed Subcall Execution

**What:** route decisions become real only where Atelier owns the sub-invocation, while top-level host chat remains native/shadowed.
**When to use:** planning/execution subcalls, delegated workers, route experiments, benchmarked comparisons.
**Trade-offs:** safer and more measurable than full host override, but not as visually dramatic at first.

## Data Flow

### Request Flow

```text
[User / Host Action]
    ↓
[CLI / MCP / Hook]
    ↓
[Search-first Tool Layer]
    ↓
[Workflow Kernel]
    ↓
[Route Execution Layer] → [Provider / Model]
    ↓
[Ledger / Report / Benchmark Artifacts]
    ↓
[Host / User Response]
```

### State Management

```text
[Session Workflow State]
    ↓
[Task Outputs / Route Decisions / Bench Results]
    ↓
[Ledger / Report / Context Memory]
    ↓
[Next Workflow Step]
```

### Key Data Flows

1. **Terminal task flow:** host request -> Search-first tool path -> workflow task state -> response.
2. **Routed subcall flow:** workflow task -> route selection -> provider execution -> cost/quality artifact capture.
3. **Benchmark proof flow:** repeated runs -> artifact aggregation -> paired quality/cost decision.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-1k users / mostly local | SQLite + file-backed runtime state is fine; optimize ergonomics and correctness first |
| 1k-100k users / service-heavy | Move critical state to Postgres, keep workflow/benchmark artifacts queryable, tighten provider retry/accounting |
| 100k+ users / broad hosted usage | Split service concerns, add stronger queueing/worker isolation, harden route execution and observability |

### Scaling Priorities

1. **First bottleneck:** prompt/context churn in the core loop — solve with workflow state and Search-first composition before adding more infra.
2. **Second bottleneck:** provider execution/accounting consistency — solve with explicit subcall routing contracts before broadening scope.

## Anti-Patterns

### Anti-Pattern 1: Platform Breadth Before Core Loop Quality

**What people do:** keep expanding UI/service/integration breadth while the terminal execution loop remains fragmented.
**Why it's wrong:** the repo gets broader but the main product promise stays weak.
**Do this instead:** make the terminal-first core measurably better before expanding secondary surfaces.

### Anti-Pattern 2: Treat Advisory Routing As Real Routing

**What people do:** count recommendations and simulations as if they were execution ownership.
**Why it's wrong:** benchmark and product claims overstate actual behavior.
**Do this instead:** separate route recommendation from route execution and only claim what is enforced.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| LLM/model vendors | Routed provider execution for Atelier-owned subcalls | Start narrow and measurable |
| Optional memory/telemetry sidecars | Existing infra adapters | Keep fail-open where appropriate |
| Optional frontend/service | FastAPI + React | Treat as support surface, not milestone driver |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `gateway` ↔ `core` | Adapter/runtime calls | Keep entry points thin |
| Search-first layer ↔ code-intel | Direct composition / escalation | Do not flatten semantic tools away |
| Workflow kernel ↔ route execution | Typed internal contracts | This is a new core seam for milestone 1 |
| Workflow/kernel ↔ ledger/report | Event + state persistence | Needed for benchmark proof and traceability |

## Sources

- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/research/RESET-RESEARCH.md`
- `.planning/PROJECT.md`

---
*Architecture research for: terminal-first agent runtime brownfield retrofit*
*Researched: 2026-06-02*
