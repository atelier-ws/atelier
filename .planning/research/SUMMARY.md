# Project Research Summary

**Project:** Atelier
**Domain:** Benchmark-first terminal coding agent brownfield retrofit
**Researched:** 2026-06-02
**Confidence:** HIGH

## Executive Summary

The research converges on a narrow but high-leverage reset: Atelier should become a benchmark-first terminal coding agent rather than a broad agent platform. Eval is the reference for execution discipline, Augment is the reference for context quality and benchmark framing, and Atelier's own memory, code-intel, tracing, and host-enforcement strengths are the differentiators to preserve.

The recommended milestone-1 shape is a Search-first grounded terminal path, a typed workflow kernel, routed execution for Atelier-owned subcalls, and a paired benchmark gate with artifact-backed claims. The main risk is breadth drift: expanding UI/platform scope or overclaiming "smartness" before the benchmark loop is actually better.

## Key Findings

### Recommended Stack

Stay on the current Python-first brownfield base: Python + Click + FastAPI + LiteLLM + tree-sitter + SQLite/Postgres, with React/Vite kept as a secondary surface. The important move is not stack replacement, but better composition of the existing runtime, routing, and code-intel layers.

**Core technologies:**
- Python + Click: terminal-first runtime and CLI surface
- LiteLLM: vendor/model abstraction for real routed subcalls
- Tree-sitter: syntax-aware grounding and future minified read/edit paths
- SQLite/Postgres + ledger/report state: artifact-backed benchmark and runtime persistence

### Expected Features

The real v1 must-haves are grounding, execution coherence, routing, and benchmark proof. Search-first ergonomics, explicit workflow state, owned-subcall route execution, and paired benchmark evidence are table stakes for this reset.

**Must have (table stakes):**
- Search-first grounded terminal loop
- Explicit workflow kernel with plan review and task carry-forward
- Routed execution for Atelier-owned subcalls
- Frozen paired benchmark gate with artifact-backed reporting

**Should have (competitive):**
- Better host/tool ergonomics
- Benchmark-backed savings UX

**Defer (v2+):**
- Full top-level host routing
- Cloud-hosted context-engine parity
- Broad "project brain" product claims

### Architecture Approach

The right architecture is layered around the live terminal loop: host/terminal adapters -> Search-first tool composition -> workflow kernel -> route execution -> persistence and benchmark artifacts. This keeps Atelier's current architecture intact while extracting the parts that actually move benchmark performance.

**Major components:**
1. Search-first grounding layer — cheaper default path without losing semantic depth
2. Workflow kernel — explicit plan/task state and grounded edit discipline
3. Route execution layer — enforced provider/model execution for owned subcalls
4. Benchmark gate — frozen paired runs, raw artifacts, and go/no-go evidence

### Critical Pitfalls

1. **Platform breadth before core-loop quality** — keep roadmap phases tied to terminal-bench impact
2. **Advisory routing mistaken for real routing** — claim only enforced owned-subcall behavior
3. **Benchmark claims without paired proof** — require frozen corpus and raw artifacts
4. **Replacing code-intel with generic search** — Search should simplify the default path, not erase semantic tooling

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Grounded Terminal Loop MVP
**Rationale:** Search-first grounding and semantic escalation are the cheapest/highest-leverage benchmark improvements.
**Delivers:** Faster default repo interaction without losing Atelier's code-intel moat.
**Addresses:** Grounding and context/intelligence requirements.
**Avoids:** Search-only regression and breadth drift.

### Phase 2: Execution Kernel MVP
**Rationale:** Eval-style execution discipline is the next load-bearing benchmark lever after grounding.
**Delivers:** Explicit workflow state, plan review, carry-forward outputs, and grounded edit gates.
**Uses:** Existing runtime, ledger, and tracing surfaces.

### Phase 3: Routed Subcall Execution MVP
**Rationale:** Current routing is smarter as advice than as execution; making it real on owned subcalls is the smallest safe parity step.
**Delivers:** Enforced provider/model execution with provenance while keeping the host chat native.

### Phase 4: Benchmark Gate MVP
**Rationale:** The reset is only real if it proves itself on frozen paired benchmark tasks.
**Delivers:** Artifact-backed solved-rate, quality, token, latency, and cost reporting.

### Phase Ordering Rationale

- Grounding first because it improves almost every terminal task immediately.
- Workflow kernel second because execution coherence compounds the grounding gains.
- Routing third because execution ownership should sit on top of a coherent kernel.
- Benchmark gate fourth because it needs the first three capabilities in place to measure the right thing.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3:** provider execution details and host/subcall boundary behavior
- **Phase 4:** benchmark corpus design and judge/invalid-run policy

Phases with standard patterns:
- **Phase 1:** mostly composition of existing tooling and ergonomics
- **Phase 2:** mostly extraction/unification of already-present runtime concepts

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Grounded in the current repo and brownfield constraints |
| Features | HIGH | Strong convergence across Eval, Augment, WOZ, and current Atelier |
| Architecture | HIGH | The missing seams are clear from current runtime structure |
| Pitfalls | HIGH | Repeatedly reinforced by both current code shape and comparative research |

**Overall confidence:** HIGH

### Gaps to Address

- Provider execution details need to be pinned down during phase planning
- Benchmark corpus and acceptance math need to be finalized during the benchmark phase

## Sources

### Primary (HIGH confidence)
- `.planning/research/RESET-RESEARCH.md`
- `.planning/research/AUGMENT-PARITY.md`
- `.planning/research/STACK.md`
- `.planning/research/FEATURES.md`
- `.planning/research/ARCHITECTURE.md`
- `.planning/research/PITFALLS.md`

### Secondary (MEDIUM confidence)
- `docs/plans/context-quality-lift/grounding.md`
- `docs/plans/world-class-atelier/00-deep-audit.md`

---
*Research completed: 2026-06-02*
*Ready for roadmap: yes*
