# Roadmap: Atelier

## Overview

This roadmap turns Atelier into a benchmark-first terminal coding agent through four coarse vertical slices: grounded terminal interaction, explicit execution discipline, real routed subcall execution, and an artifact-backed benchmark gate. Each phase exists to improve solved-rate, grounding, execution coherence, or cost-under-parity on frozen terminal-bench-style tasks.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Grounded Terminal Loop MVP** - Search-first default path with semantic escalation
- [ ] **Phase 2: Execution Kernel MVP** - Explicit workflow state, plan review, and grounded edit discipline
- [ ] **Phase 3: Routed Subcall Execution MVP** - Enforced provider/model routing for Atelier-owned subcalls
- [ ] **Phase 4: Benchmark Gate MVP** - Frozen paired benchmarks and artifact-backed proof

## Phase Details

### Phase 1: Grounded Terminal Loop MVP
**Goal:** As a terminal coding agent user, I want a grounded Search-first workflow with semantic escalation, so that I can solve repo tasks faster without losing precision.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: GRND-01, GRND-02, GRND-03, INTL-01, INTL-02
**Success Criteria** (what must be TRUE):
  1. User can use a Search-first default path for file/path/match discovery without manually picking among overlapping tools.
  2. User can escalate grounded results into precise symbol, caller, usage, and impact answers in the same session.
  3. User can batch related edits and follow-up reads while existing memory and code-intel strengths still work.
**Plans**: 3 plans

Plans:
- [ ] 01-01: Compose Search-first grounding over existing read/search/edit/memory surfaces
- [ ] 01-02: Preserve code-intel escalation paths inside the simplified terminal loop
- [ ] 01-03: Add low-roundtrip ergonomics and batching nudges without regressing existing smart context

### Phase 2: Execution Kernel MVP
**Goal:** As a terminal coding agent user, I want explicit workflow state and grounded edit discipline, so that multi-step tasks stay coherent from plan through execution.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05, INTL-03
**Success Criteria** (what must be TRUE):
  1. User can move through explicit explore, plan, execute, and review workflow states in one session.
  2. User can approve or revise a plan before execution starts.
  3. User can resume execution with current-task state and prior task outputs preserved.
  4. User can only apply benchmark-path edits after the relevant code has been grounded by read/search/code-intel steps.
**Plans**: 3 plans

Plans:
- [ ] 02-01: Introduce typed session workflow state and task-local carry-forward outputs
- [ ] 02-02: Add plan review, progress, and workflow event surfaces through existing tracing/reporting
- [ ] 02-03: Enforce grounded edit gates on the benchmark execution path

### Phase 3: Routed Subcall Execution MVP
**Goal:** As a terminal coding agent user, I want Atelier-owned subcalls to route through the right provider and model while my host chat stays native, so that hard tasks use better execution paths without destabilizing the host loop.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: ROUT-01, ROUT-02, ROUT-03
**Success Criteria** (what must be TRUE):
  1. User can execute Atelier-owned subcalls through enforced provider/model routing rather than advisory-only routing.
  2. User can inspect actual provider/model provenance for each routed subcall.
  3. User can keep the top-level host conversation native while routed execution runs safely on owned subcalls.
**Plans**: 2 plans

Plans:
- [ ] 03-01: Add provider execution lanes for Atelier-owned subcalls using existing routing foundations
- [ ] 03-02: Record route provenance and preserve shadow-safe top-level host behavior

### Phase 4: Benchmark Gate MVP
**Goal:** As a benchmark-driven maintainer, I want paired artifact-backed terminal benchmarks, so that Atelier can prove higher solved-rate with non-inferior quality and lower cost where possible.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: BENC-01, BENC-02, BENC-03, BENC-04
**Success Criteria** (what must be TRUE):
  1. User can run a frozen paired benchmark set under matched baseline and treatment conditions.
  2. User can inspect raw run artifacts, judge outputs, and the exact commit under test for every benchmark claim.
  3. User can reject invalid or off-topic runs instead of counting them as wins.
  4. User can use a benchmark summary that reports solved-rate, quality, token, latency, and cost deltas to decide whether the reset succeeded.
**Plans**: 3 plans

Plans:
- [ ] 04-01: Freeze benchmark corpus and matched baseline protocol for terminal-bench-style tasks
- [ ] 04-02: Capture paired run artifacts, judge outputs, and benchmark summaries
- [ ] 04-03: Gate milestone claims on solved-rate, quality, and cost-under-parity

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Grounded Terminal Loop MVP | 0/3 | Not started | - |
| 2. Execution Kernel MVP | 0/3 | Not started | - |
| 3. Routed Subcall Execution MVP | 0/2 | Not started | - |
| 4. Benchmark Gate MVP | 0/3 | Not started | - |
