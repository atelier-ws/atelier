# Requirements: Atelier

**Defined:** 2026-06-02
**Core Value:** Achieve the highest solved-rate on frozen terminal-bench-style coding tasks, with non-inferior quality and lower cost where possible.

## v1 Requirements

Requirements for the initial reset release. Each maps to roadmap phases.

### Grounding

- [x] **GRND-01**: User can inspect files, paths, and matches through a Search-first default path without manually choosing between overlapping discovery tools
- [x] **GRND-02**: User can move from Search-first results into precise code-intel answers for symbols, callers, usages, and impact in the same session
- [x] **GRND-03**: User can batch related edits and follow-up reads through a low-roundtrip grounded terminal workflow

### Execution Kernel

- [ ] **EXEC-01**: User can move through explicit explore, plan, execute, and review workflow states inside one session
- [ ] **EXEC-02**: User can approve, revise, or re-run a plan before execution starts
- [ ] **EXEC-03**: User can resume execution with current task state and prior task outputs preserved
- [ ] **EXEC-04**: User can inspect workflow events and task progress without reconstructing the session manually
- [ ] **EXEC-05**: User can only apply benchmark-path edits after the relevant file or code region has been grounded by a read, search, or code-intel step

### Routing

- [ ] **ROUT-01**: User can run Atelier-owned subcalls through an enforced provider/model routing layer
- [ ] **ROUT-02**: User can see which provider/model actually executed each Atelier-owned subcall
- [ ] **ROUT-03**: User can keep the top-level host conversation native while routed execution runs on owned subcalls

### Benchmark Gate

- [ ] **BENC-01**: User can run a frozen paired benchmark set of terminal-bench-style coding tasks that compares the baseline path against Atelier under matched conditions
- [ ] **BENC-02**: User can inspect benchmark artifacts that report solved-rate, quality, token, latency, and cost deltas for each paired run
- [ ] **BENC-03**: User can make milestone decisions from a benchmark summary that rejects invalid or off-topic runs instead of counting them as wins
- [ ] **BENC-04**: User can trace each benchmark claim back to raw run artifacts, judge outputs, and the exact commit under test

### Context & Intelligence

- [x] **INTL-01**: User can keep using Atelier's existing memory and context-recall strengths while the benchmark-first reset ships
- [x] **INTL-02**: User can keep using Atelier's existing code-intel strengths while the default terminal path gets simplified
- [ ] **INTL-03**: User can keep using current tracing, reporting, and host-enforcement surfaces during the reset

## v2 Requirements

Deferred to a later release. Tracked but not in the current roadmap.

### Tooling

- **TOOL-01**: User can use a minified read/edit path that safely reduces token spend for supported languages
- **TOOL-02**: User can see richer savings UX that ties per-session counters back to benchmark-backed truth

### Routing

- **ROUT-04**: User can compare shadow-routed and actively routed execution paths across more providers and hosts
- **ROUT-05**: User can opt into broader host-level routing once subcall routing has proven parity

### Product Shape

- **PROD-01**: User can remove or slim secondary surfaces only after a measured parity review shows they are expendable
- **PROD-02**: User can rely on broader "project brain" positioning only after the underlying workflow/context mechanisms are measurably real

### Intelligence

- **INTL-01**: User can get deeper semantic parity beyond Python, TypeScript, and JavaScript where today's code-intel depth is strongest
- **INTL-02**: User can import and reconstruct prior session traces with parity good enough to support smarter long-horizon project memory

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Clean-slate rewrite | Brownfield retrofit is locked; rewriting would throw away current strengths and delay proof |
| Full provider enforcement for the top-level host chat in v1 | Too risky before Atelier-owned subcall routing is benchmarked and trusted |
| Web-first/dashboard-first expansion | Milestone 1 is about terminal execution quality and cost discipline |
| Removing current CLI/API/UI/SDK/integration surfaces before parity review | Cuts require evidence, not instinct |
| Cost-saving claims based only on session counters | Benchmark-backed quality and spend evidence is the real gate |
| Cloud-hosted multi-tenant Augment-style context platform parity in v1 | Atelier is local-first and milestone 1 is focused on terminal-core quality, not cloud product matching |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| GRND-01 | Phase 1 | Complete |
| GRND-02 | Phase 1 | Complete |
| GRND-03 | Phase 1 | Complete |
| EXEC-01 | Phase 2 | Pending |
| EXEC-02 | Phase 2 | Pending |
| EXEC-03 | Phase 2 | Pending |
| EXEC-04 | Phase 2 | Pending |
| EXEC-05 | Phase 2 | Pending |
| ROUT-01 | Phase 3 | Pending |
| ROUT-02 | Phase 3 | Pending |
| ROUT-03 | Phase 3 | Pending |
| BENC-01 | Phase 4 | Pending |
| BENC-02 | Phase 4 | Pending |
| BENC-03 | Phase 4 | Pending |
| BENC-04 | Phase 4 | Pending |
| INTL-01 | Phase 1 | Complete |
| INTL-02 | Phase 1 | Complete |
| INTL-03 | Phase 2 | Pending |

**Coverage:**
- v1 requirements: 18 total
- Mapped to phases: 18
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-02*
*Last updated: 2026-06-02 after initial definition*
