# Roadmap: Atelier

## Overview

This roadmap turns Atelier into a benchmark-first terminal coding agent through four coarse vertical slices: grounded terminal interaction, explicit execution discipline, real routed subcall execution, and an artifact-backed benchmark gate. Each phase exists to improve solved-rate, grounding, execution coherence, or cost-under-parity on frozen terminal-bench-style tasks.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Grounded Terminal Loop MVP** - Search-first default path with semantic escalation (completed 2026-06-02)
- [x] **Phase 2: Execution Kernel MVP** - Owned workflow runner, default definitions, solver loop, explicit plan review, grounded edit discipline, and read-only structural minification (completed 2026-06-03)
- [ ] **Phase 3: Routed Execution MVP** - Explicit or auto provider/model routing for Atelier-owned subcalls, plus prompt-cache affinity and a shadow-safe local host router bridge
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
- [x] 01-01: Compose Search-first grounding over existing read/search/edit/memory surfaces
- [x] 01-02: Preserve code-intel escalation paths inside the simplified terminal loop
- [x] 01-03: Add low-roundtrip ergonomics and batching nudges without regressing existing smart context

### Phase 2: Execution Kernel MVP
**Goal:** As a terminal coding agent user, I want an owned workflow runner with explicit state and benchmark solver discipline, so that multi-step tasks stay coherent from plan through execution and can be retried from harness feedback.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05, EXEC-06, EXEC-07, EXEC-08, EXEC-09, EXEC-10, EXEC-11, EXEC-12, EXEC-13, EXEC-14, DFLT-01, DFLT-02, DFLT-03, DFLT-04, INTL-03
**Success Criteria** (what must be TRUE):
  1. User can move through explicit explore, plan, execute, and review workflow states in one session.
  2. User can approve or revise a plan before execution starts.
  3. User can resume execution with current-task state and prior task outputs preserved.
  4. User can only apply benchmark-path edits after the relevant code has been grounded by read/search/code-intel steps.
  5. User can run an Atelier-owned workflow DAG with persistent/forkable step context, safe tool scheduling, and per-step telemetry.
  6. User can inspect and regenerate default agent, skill, workflow, prompt, MCP, and benchmark-profile definitions from one canonical source.
  7. User can run a benchmark solver profile headlessly, retry from harness feedback, and emit artifact-backed JSON/stream-JSON outputs.
  8. User can run owned explore/plan/review/execute on one generic stem system prompt with phase-pivot user prompts and conversation-forking steps, preserving the prompt-cache prefix across phases.
  9. User can read files through a structural minified reader path that cuts explore-time tokens while writer/execute reads stay byte-exact.
**Plans**: 7 plans

Plans:
- [x] 02-01: Introduce typed session workflow state and task-local carry-forward outputs
- [x] 02-02: Add plan review, progress, and workflow event surfaces through existing tracing/reporting
- [x] 02-03: Enforce grounded edit gates on the benchmark execution path
- [x] 02-04: Add owned workflow DAG execution with persistent/forkable step context
- [x] 02-05: Add canonical default definitions and generated host/runtime surfaces (incl. stem-agent prompt set, phase-pivot prompts, reviewer verdict contract, and Eval solver command-discipline rules)
- [x] 02-06: Add benchmark solver profile, conversation-fork harness-feedback retry, and headless run artifacts
- [x] 02-07: Add read-only structural minification on the explore read path (the read half of Eval's VFS)

### Phase 3: Routed Execution MVP
**Goal:** As a terminal coding agent user, I want Atelier-owned subcalls to run through an explicit provider/model I choose or an auto-selected route, while preserving prompt-cache locality, so that I can control important runs and still let policy choose when appropriate.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: ROUT-01, ROUT-02, ROUT-03, ROUT-04, ROUT-05, ROUT-06, ROUT-07
**Success Criteria** (what must be TRUE):
  1. User can execute Atelier-owned subcalls through enforced provider/model routing rather than advisory-only routing.
  2. User can explicitly select provider and model as a first-class route mode for owned subcalls and benchmarks.
  3. User can choose `auto` mode when they want policy to select from task class, provider health, quality risk, price, latency, and cache warmth.
  4. User can preserve provider-side prompt-cache affinity across explore -> plan -> review -> execute loops when the selected or auto route is cache-compatible.
  5. User can inspect actual provider/model/cache provenance for each routed subcall.
  6. User can keep the top-level host conversation native while routed execution runs safely on owned subcalls.
  7. User can shadow a Claude-Code-compatible local router bridge before opting into broader host-level routing.
**Plans**: 4 plans

Plans:
- [ ] 03-01: Add provider catalog and explicit/auto route selection modes for owned execution
- [ ] 03-02: Add provider execution lanes for Atelier-owned subcalls using existing routing foundations
- [ ] 03-03: Add prompt-cache affinity, cache-token accounting, and warm-route stickiness
- [ ] 03-04: Add a shadow-safe local host router bridge for Claude-Code-compatible traffic

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
| 1. Grounded Terminal Loop MVP | 3/3 | Complete   | 2026-06-02 |
| 2. Execution Kernel MVP | 7/7 | Complete | 2026-06-03 |
| 3. Routed Execution MVP | 0/4 | Not started | - |
| 4. Benchmark Gate MVP | 0/3 | Not started | - |
