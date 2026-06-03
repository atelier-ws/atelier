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

- [x] **EXEC-01**: User can move through explicit explore, plan, execute, and review workflow states inside one session
- [ ] **EXEC-02**: User can approve, revise, or re-run a plan before execution starts
- [x] **EXEC-03**: User can resume execution with current task state and prior task outputs preserved
- [x] **EXEC-04**: User can inspect workflow events and task progress without reconstructing the session manually
- [x] **EXEC-05**: User can only apply benchmark-path edits after the relevant file or code region has been grounded by a read, search, or code-intel step
- [x] **EXEC-06**: User can run an Atelier-owned workflow DAG with agent, tool, and shell steps instead of only receiving advisory workflow state
- [x] **EXEC-07**: User can reuse persistent per-step execution context and fork context from earlier workflow steps for plan -> review -> execute loops
- [x] **EXEC-08**: User can execute safe independent tool work in parallel while writes, shell mutations, and interactive decisions stay serialized
- [x] **EXEC-09**: User can run a dedicated benchmark solver profile with artifact-first, no-repeat-failure, cleanup, and command-discipline rules
- [x] **EXEC-10**: User can reinvoke a failed benchmark attempt with the same task context and harness feedback instead of treating the first attempt as the final outcome
- [x] **EXEC-11**: User can run the owned workflow/solver headlessly with JSON and stream-JSON artifacts that include step outputs, tokens, cache, cost, and duration
- [x] **EXEC-12**: User can install or bootstrap default workflow, solver, agent, skill, and MCP definitions without overwriting project-local user changes
- [x] **EXEC-13**: User can run owned explore/plan/review/execute phases on one generic ("stem") system prompt — with phase changes delivered as user-turn prompts and later steps forking the prior step's conversation — so the provider prompt-cache prefix is preserved across phases instead of invalidated at every boundary
- [x] **EXEC-14**: User can read files through a more aggressive minified reader path (reader-profile only) that collapses intra-line whitespace for non-whitespace-significant languages — beyond today's trailing-whitespace/blank-run transform — with savings attributed through existing minification telemetry and byte-exact reads preserved for writer/execute profiles

### Defaults & Distribution

- [x] **DFLT-01**: User can inspect one canonical default-definition registry that covers agent roles, skills, workflows, prompts, MCP templates, tool policies, model/effort defaults, and benchmark profiles
- [x] **DFLT-02**: User can regenerate Claude, Codex, OpenCode, Antigravity, shared skill, and benchmark-owned runtime surfaces from the canonical defaults without hand-editing generated artifacts
- [x] **DFLT-03**: User can verify generated agent/skill/workflow/MCP surfaces are in sync with canonical defaults before release or benchmark runs
- [x] **DFLT-04**: User can layer project-local defaults over packaged defaults while preserving existing local user changes and reporting created/skipped/changed files

### Routing

- [x] **ROUT-01**: User can run Atelier-owned subcalls through an enforced provider/model routing layer
- [x] **ROUT-02**: User can see which provider/model actually executed each Atelier-owned subcall
- [x] **ROUT-03**: User can keep the top-level host conversation native while routed execution runs on owned subcalls
- [x] **ROUT-04**: User can explicitly select provider and model as a first-class route mode for Atelier-owned subcalls and benchmark runs
- [x] **ROUT-05**: User can choose `auto` mode when they want Atelier to select from task class, quality risk, provider health, price, latency, and cache warmth
- [x] **ROUT-06**: User can preserve provider-side prompt-cache locality across related workflow steps and inspect cache read/write tokens, cache misses, and route-stickiness decisions
- [ ] **ROUT-07**: User can run a shadow-safe local host router bridge for Claude-Code-compatible traffic before opting into broader host-level routing enforcement

### Benchmark Gate

- [x] **BENC-01**: User can run a frozen paired benchmark set of terminal-bench-style coding tasks that compares the baseline path against Atelier under matched conditions
- [x] **BENC-02**: User can inspect benchmark artifacts that report solved-rate, quality, token, latency, and cost deltas for each paired run
- [x] **BENC-03**: User can make milestone decisions from a benchmark summary that rejects invalid or off-topic runs instead of counting them as wins
- [x] **BENC-04**: User can trace each benchmark claim back to raw run artifacts, judge outputs, and the exact commit under test

### Context & Intelligence

- [x] **INTL-01**: User can keep using Atelier's existing memory and context-recall strengths while the benchmark-first reset ships
- [x] **INTL-02**: User can keep using Atelier's existing code-intel strengths while the default terminal path gets simplified
- [x] **INTL-03**: User can keep using current tracing, reporting, and host-enforcement surfaces during the reset

## v2 Requirements

Deferred to a later release. Tracked but not in the current roadmap.

### Tooling

- **TOOL-01**: User can use a minified **edit/write** round-trip path (match-against-minified + formatter-restore) for supported languages — the read-only half is promoted to v1 as EXEC-14; this v2 item is the harder write-side round-trip (Eval's tree-sitter VFS)
- **TOOL-02**: User can see richer savings UX that ties per-session counters back to benchmark-backed truth

### Routing

- **ROUT-08**: User can compare shadow-routed and actively routed execution paths across more providers and hosts
- **ROUT-09**: User can make local host-router enforcement the default once subcall routing and shadow routing have proven parity

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
| EXEC-01 | Phase 2 | Complete |
| EXEC-02 | Phase 2 | Pending |
| EXEC-03 | Phase 2 | Complete |
| EXEC-04 | Phase 2 | Complete |
| EXEC-05 | Phase 2 | Complete |
| EXEC-06 | Phase 2 | Complete |
| EXEC-07 | Phase 2 | Complete |
| EXEC-08 | Phase 2 | Complete |
| EXEC-09 | Phase 2 | Complete |
| EXEC-10 | Phase 2 | Complete |
| EXEC-11 | Phase 2 | Complete |
| EXEC-12 | Phase 2 | Complete |
| EXEC-13 | Phase 2 | Complete |
| EXEC-14 | Phase 2 | Complete |
| DFLT-01 | Phase 2 | Complete |
| DFLT-02 | Phase 2 | Complete |
| DFLT-03 | Phase 2 | Complete |
| DFLT-04 | Phase 2 | Complete |
| ROUT-01 | Phase 3 | Complete |
| ROUT-02 | Phase 3 | Complete |
| ROUT-03 | Phase 3 | Complete |
| ROUT-04 | Phase 3 | Complete |
| ROUT-05 | Phase 3 | Complete |
| ROUT-06 | Phase 3 | Complete |
| ROUT-07 | Phase 3 | Pending |
| BENC-01 | Phase 4 | Complete |
| BENC-02 | Phase 4 | Complete |
| BENC-03 | Phase 4 | Complete |
| BENC-04 | Phase 4 | Complete |
| INTL-01 | Phase 1 | Complete |
| INTL-02 | Phase 1 | Complete |
| INTL-03 | Phase 2 | Complete |

**Coverage:**
- v1 requirements: 32 total
- Mapped to phases: 32
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-02*
*Last updated: 2026-06-03 after parity status reconciliation, defaults bootstrap surfacing, and benchmark gate consumption updates*
